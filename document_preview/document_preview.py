"""Main service module."""

import email
import functools
import os
import re
import subprocess
import tempfile
from base64 import b64decode, b64encode
from hashlib import sha256
from io import BytesIO, StringIO
from tempfile import NamedTemporaryFile
from time import time
from zipfile import BadZipFile, ZipFile

import fitz
import pandas
from assemblyline.common import forge
from assemblyline.common.exceptions import RecoverableError
from assemblyline.odm.base import FULL_URI
from assemblyline_v4_service.common.base import ServiceBase
from assemblyline_v4_service.common.ocr import detections as indicator_detections
from assemblyline_v4_service.common.ocr import ocr_detections
from assemblyline_v4_service.common.request import ServiceRequest as Request
from assemblyline_v4_service.common.result import (
    Heuristic,
    Result,
    ResultImageSection,
    ResultKeyValueSection,
    ResultSection,
    ResultTextSection,
)
from assemblyline_v4_service.common.utils import extract_passwords
from bs4 import BeautifulSoup
from documentbuilder.docbuilder import CDocBuilder
from eml2pdf.libeml2pdf import _Header as Header
from eml2pdf.libeml2pdf import _walk_eml as walk_eml
from multidecoder.decoders.network import find_emails, find_urls
from natsort import natsorted
from PIL import Image, ImageOps
from selenium.common.exceptions import NoAlertPresentException, WebDriverException
from selenium.webdriver import Chrome, ChromeOptions, ChromeService

PDF_DPI = int(os.environ.get("PDF_DPI", 150))
IDENTIFY = forge.get_identify(use_cache=os.environ.get("PRIVILEGED", "false").lower() == "true")


@functools.lru_cache(maxsize=32)
def _read_file_bytes(fp: str) -> bytes:
    """Read and cache file contents.

    Args:
        fp (str): The file path to read.

    Returns:
        bytes: The contents of the file as bytes.

    """
    with open(fp, "rb") as f:
        return f.read()


@functools.lru_cache(maxsize=8)
def _open_fitz_doc(fp: str) -> fitz.Document:
    """Open and cache a PyMuPDF document.

    Args:
        fp (str): The file path to the PDF document.

    Returns:
        fitz.Document: The opened PyMuPDF document.

    """
    return fitz.open(fp)


def _clear_caches():
    """Clear all file-level LRU caches between analysis runs."""
    _read_file_bytes.cache_clear()
    _open_fitz_doc.cache_clear()


def eml2html(file_contents: bytes) -> str:
    """Convert an EML file to HTML format.

    This is derived from the eml2pdf's `processs_eml` function but omits attachment handling since we're only
    interested in rendering the email body for previewing.

    Args:
        file_contents (bytes): The content of the EML document.

    Returns:
        str: The HTML content as a string.

    """
    # Open and parse the .eml file
    msg = email.message_from_bytes(file_contents)

    email_header = Header(msg, "<in-memory>")
    html_content, _ = walk_eml(msg, "<in-memory>")

    if html_content and isinstance(html_content, str):
        # Add UTF-8 meta tag and email header if not present
        return f"""
    <meta charset="UTF-8">
    <meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
    {email_header.html}
    <hr>
    {html_content}
    """


def pdf_page_count(fp: str) -> int:
    """Extract PDF metadata information using PyMuPDF.

    Args:
        fp (str): The file path to the PDF document.

    Returns:
        int: The number of pages in the PDF document.

    """
    doc = _open_fitz_doc(fp)
    return doc.page_count


def convert_from_path(
    fp: str, output_directory: str, first_page: int = 1, last_page: int | None = None, context: str = "original"
) -> None:
    """Convert PDF to images using PyMuPDF.

    Args:
        fp (str): The file path to the PDF document.
        output_directory (str): The directory where the output images will be saved.
        first_page (int, optional): The first page to convert. Defaults to 1.
        last_page (int, optional): The last page to convert. Defaults to None, which means all pages.
        context (str, optional): A context string to include in the output file names. Defaults to "original".

    """
    doc = _open_fitz_doc(fp)
    end_page = min(last_page, doc.page_count) if last_page else doc.page_count
    for page_num in range(first_page - 1, end_page):
        page = doc[page_num]
        zoom = PDF_DPI / 72  # 72 is the default DPI for PDFs
        matrix = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=matrix)
        output_path = os.path.join(output_directory, f"output_{context}-{page_num + 1}.png")
        pix.save(output_path)


class DocumentPreview(ServiceBase):
    """Service to render document previews and extract text/images from documents."""

    def __init__(self, config=None):
        """Initialize the DocumentPreview service."""
        super().__init__(config)
        browser_options = ChromeOptions()

        # Set brower options depending on service configuration
        browser_cfg = self.config.get("browser_options", {})
        [browser_options.add_argument(arg) for arg in browser_cfg.get("arguments", [])]
        [browser_options.set_capability(cap_n, cap_v) for cap_n, cap_v in browser_cfg.get("capabilities", {}).items()]

        # Run browser in offline mode only
        service = None
        if os.path.exists("/usr/bin/chromedriver"):
            service = ChromeService(executable_path="/usr/bin/chromedriver")
        self.browser = Chrome(options=browser_options, service=service)
        self.browser.set_network_conditions(offline=True, latency=5, throughput=500 * 1024)
        self.browser.set_window_size(1080, 1920)

    def start(self):
        """Start the DocumentPreview service."""
        self.log.debug("Document preview service started")

    def stop(self):
        """Stop the DocumentPreview service."""
        self.log.debug("Document preview service ended")

    def extract_pdf_text(self, path: str, max_pages: int) -> None | str:
        """Extract text from a PDF document.

        Args:
            path (str): The path to the PDF document.
            max_pages (int): The maximum number of pages to extract.

        Returns:
            str: The path to the extracted text file.
        """
        output_path = os.path.join(self.working_directory, "extracted_text")
        doc = _open_fitz_doc(path)
        text = ""
        for page_num in range(min(max_pages, doc.page_count)):
            text += doc[page_num].get_text()

        if text.strip():
            with open(output_path, "w") as f:
                f.write(text)
            return output_path

    def extract_pdf_images(self, path: str, max_pages: int) -> list[str]:
        """Extract images from a PDF document.

        Args:
            path (str): The path to the PDF document.
            max_pages (int): The maximum number of pages to extract.

        Returns:
            list[str]: A list of paths to the extracted image files.
        """
        image_paths = []
        doc = _open_fitz_doc(path)
        img_index = 0
        for page_num in range(min(max_pages, doc.page_count)):
            for img_ref in doc[page_num].get_images(full=True):
                xref = img_ref[0]
                base_image = doc.extract_image(xref)
                if base_image:
                    ext = base_image["ext"]
                    image_data = base_image["image"]
                    output_path = os.path.join(self.working_directory, f"extracted_image-{img_index:03d}.{ext}")
                    with open(output_path, "wb") as f:
                        f.write(image_data)
                    image_paths.append(output_path)
                    img_index += 1
        return image_paths

    def ebook_conversion(self, request: Request) -> None | str:
        """Convert eBooks (EPUB/MOBI) to PDF format using the `ebook-convert` command-line tool.

        Args:
            request (Request): The service request object containing parameters and file information.

        Returns:
            str: The path to the converted PDF file, or None if conversion failed.

        """
        ext = request.file_type.replace("document/", "")
        with tempfile.NamedTemporaryFile(suffix=f".{ext}") as tmp:
            tmp.write(request.file_contents)
            tmp.flush()

            output_path = os.path.join(self.working_directory, "converted.pdf")
            subprocess.run(
                ["ebook-convert", tmp.name, output_path],
                capture_output=True,
            )

            if os.path.exists(output_path):
                return output_path

    def office_conversion(self, file: str, request: Request) -> str:
        """Convert Office document to PDF and extract any media if possible.

        Args:
            file (str): The path to the Office document to convert.
            request (Request): The service request object containing parameters and file information.

        Returns:
            str: The path to the converted PDF file, or None if conversion failed.

        """
        # Extract all media from the Office document if they're an image
        if request.file_type != "text/csv":
            try:
                with ZipFile(file, "r") as zf:
                    extracted_images_dir = os.path.join(self.working_directory, "extracted_media")
                    for media in zf.filelist:
                        if media.is_dir():
                            # Skipping directories
                            continue
                        elif "/media/" not in media.filename:
                            # Not a media file, skip
                            continue

                        # Extract the media file
                        zf.extract(media, extracted_images_dir)
                        media_path = os.path.join(extracted_images_dir, media.filename)
                        # Ensure the media extracted is an image
                        if IDENTIFY.fileinfo(
                            media_path,
                            generate_hashes=False,
                            skip_fuzzy_hashes=True,
                            calculate_entropy=False,
                        )["type"].startswith("image/"):
                            request.add_extracted(
                                media_path,
                                name=media.filename,
                                description="Extracted media from Office document",
                            )
            except BadZipFile:
                # Can't extract media from the file, likely not a valid Office document
                pass

        # Convert Office documents to PDF using CDocBuilder
        # Ref: https://api.onlyoffice.com/docs/office-api/get-started/overview/
        output_path = os.path.join(self.working_directory, "converted.pdf")
        builder = CDocBuilder()
        builder.OpenFile(file, "")

        if request.file_type == "document/office/excel" or request.file_type == "text/csv":
            # Adjust the orientation of spreadsheets before conversion
            api = builder.GetContext().GetGlobal()["Api"]
            spreadsheet = api.Call("GetActiveSheet")
            spreadsheet.SetProperty("PageOrientation", "xlLandscape")

        builder.SaveFile("pdf", output_path)
        builder.CloseFile()
        if os.path.exists(output_path):
            return output_path

    def html_render(self, file_contents: bytes, max_pages: int = 1) -> None | str:
        """Render HTML content in a browser and save as PDF.

        Args:
            file_contents (bytes): The HTML content to render.
            max_pages (int): The maximum number of pages to render.

        Returns:
            None | str: The path to the rendered PDF file, or None if rendering failed.
        """
        if b"window.location.href = " in file_contents:
            # Document contains code that will cause a redirect, something we likely can't follow
            return

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_pdf:
            # Load base64'd HTML contents directly into new tab
            self.browser.switch_to.new_window("tab")
            self.browser.get(f"data:text/html;base64,{b64encode(file_contents).decode()}")

            # Check to see if there's an alert raised on page load
            try:
                # If there is any alert, dismiss it before continuing render
                while True:
                    alert = self.browser.switch_to.alert
                    alert.dismiss()
            except NoAlertPresentException:
                # No alert raised, continue with render
                pass

            try:
                # Use Chrome's Developer Protocol directly
                result = self.browser.execute_cdp_cmd(
                    "Page.printToPDF",
                    {
                        "pageRanges": f"1-{max_pages}",
                        "printBackground": True,
                        "transferMode": "ReturnAsStream",
                    },
                )

                # Read the PDF stream in chunks and write to file
                stream_handle = result["stream"]
                while True:
                    chunk = self.browser.execute_cdp_cmd("IO.read", {"handle": stream_handle, "size": 65536})
                    tmp_pdf.write(b64decode(chunk["data"]) if chunk.get("base64Encoded") else chunk["data"].encode())
                    if chunk.get("eof"):
                        # We've reached the end of the stream
                        break
                self.browser.execute_cdp_cmd("IO.close", {"handle": stream_handle})
                return tmp_pdf.name
            except WebDriverException:
                # We aren't able to print the page to PDF, take a screenshot instead
                self.browser.save_screenshot(os.path.join(self.working_directory, "output_screenshot-1.png"))
                return
            finally:
                # Reset browser for next run by closing all windows (except for the first one which we created)

                # Check to see if the current window handle was deleted
                if self.browser.current_window_handle not in self.browser.window_handles:
                    # Set current window to the last that was created
                    self.browser.switch_to.window(self.browser.window_handles[-1])

                while len(self.browser.window_handles) > 1:
                    # In the event we load JS that spawns a bunch of windows, let's clean them up
                    self.browser.close()
                    self.browser.switch_to.window(self.browser.window_handles[-1])

    def pdf_to_images(self, file, max_pages=None, context="original"):
        """Convert PDF to images for previewing.

        Args:
            file (str): The path to the PDF file.
            max_pages (int, optional): The maximum number of pages to convert. Defaults to None.
            context (str, optional): The context for the conversion. Defaults to "original".
        """
        convert_from_path(file, self.working_directory, first_page=1, last_page=max_pages, context=context)

    def render_documents(self, request: Request, max_pages=1) -> list[tuple[str, str]] | None:
        """Render documents based on their file type.

        Args:
            request (Request): The request object containing file information.
            max_pages (int, optional): The maximum number of pages to render. Defaults to 1.

        Returns:
            list[tuple[str, str]] | None: A list of tuples containing the context and path to the rendered PDF,
            or None if rendering failed.
        """
        # Word/Excel/Powerpoint/RTF/ODT
        if request.file_type.startswith("document/odt") or any(
            request.file_type == f"document/office/{ms_product}"
            for ms_product in ["word", "excel", "powerpoint", "rtf"]
        ):
            return [("original", self.office_conversion(request.file_path, request))]
        # CSV
        elif request.file_type == "text/csv":
            with tempfile.NamedTemporaryFile(dir=self.working_directory) as tmp:
                with pandas.ExcelWriter(tmp) as writer:
                    # Convert CSV to Excel spreadsheet, then render
                    df = pandas.read_csv(request.file_path, on_bad_lines="skip")
                    df.to_excel(writer, index=False)
                    worksheet = writer.sheets["Sheet1"]

                    # Expand columns
                    # Ref: https://stackoverflow.com/questions/17326973/is-there-a-way-to-auto-adjust-excel-column-widths-with-pandas-excelwriter
                    for idx, col in enumerate(df):  # loop through all columns
                        series = df[col]
                        max_len = (
                            max(
                                (
                                    series.astype(str).map(len).max(),  # len of largest item
                                    len(str(series.name)),  # len of column name/header
                                )
                            )
                            + 1
                        )  # adding a little extra space
                        worksheet.set_column(idx, idx, max_len)  # set column width

                return [("original", self.office_conversion(tmp.name, request))]

        # PDF
        elif request.file_type == "document/pdf":
            return [("original", request.file_path)]
        elif request.file_type in ["document/epub", "document/mobi"]:
            return [("original", self.ebook_conversion(request))]
        # EML/MSG
        elif request.file_type.endswith("email"):
            file_contents = request.file_contents
            file_contents_peek = file_contents[:30].lower()
            # Convert MSG to EML where applicable
            if request.file_type == "document/office/email":
                with tempfile.NamedTemporaryFile(suffix=".eml") as tmp:
                    subprocess.run(
                        ["msgconvert", "-outfile", tmp.name, request.file_path],
                        capture_output=True,
                    )
                    tmp.seek(0)
                    file_contents = tmp.read()
            elif request.file_type == "document/email" and (
                b"<html" in file_contents_peek or b"<!doctype html" in file_contents_peek
            ):
                # We're dealing with an HTML-formatted email
                return [("original", self.html_render(request.file_contents, max_pages))]

            # Render EML as PNG
            # If we have internet access, we'll attempt to load external images
            return [("original", self.html_render(eml2html(file_contents).encode(), max_pages))]
        # HTML
        elif request.file_type == "code/html":
            # Render the original HTML first
            pdf_files = []
            bsoup = BeautifulSoup(request.file_contents, "html.parser")
            pdf_files.append(("original", self.html_render(request.file_contents, max_pages)))

            # Render the HTML with scripts removed
            has_scripts = bool(bsoup("script"))
            if has_scripts:
                [s.extract() for s in bsoup("script")]
                scriptless_html = str(bsoup).encode()
                pdf_files.append(("scriptless", self.html_render(scriptless_html, max_pages)))

            # Render the HTML with styling removed (we'll use this version for OCR)
            has_styles = bool(bsoup("style"))
            if has_styles:
                [s.extract() for s in bsoup("style")]
                styleless_html = str(bsoup).encode()
                pdf_files.append(("styleless", self.html_render(styleless_html, max_pages)))
            return pdf_files

    def tag_network_iocs(self, section: ResultSection, ocr_content: str) -> None:
        """Tag any network IOCs found in OCR output.

        Args:
            section (ResultSection): The result section to add tags to.
            ocr_content (str): The OCR-extracted text content to scan for IOCs.
        """
        [section.add_tag("network.email.address", node.value) for node in find_emails(ocr_content.encode())]
        [section.add_tag("network.static.uri", node.value) for node in find_urls(ocr_content.encode())]

    def scan_for_QR_codes(self, image: Image) -> str:
        """Scan the given image for QR codes and return the decoded content if found.

        Args:
            image (Image): The image to scan for QR codes.

        Returns:
            str: The decoded content of the QR code if found, otherwise an empty string.
        """
        # Try scanning the image as-is for QR codes
        with NamedTemporaryFile() as tmp_qr:
            image.save(tmp_qr.name, format="PNG")
            qr_results = subprocess.run(
                ["zbarimg", "-q", tmp_qr.name],
                capture_output=True,
                text=True,
            ).stdout.strip()

            if qr_results:
                # We were able to decode a QR code without any image manipulation, return the result
                return qr_results
            else:
                # Try scanning with a color invert of the image
                tmp_qr.seek(0)
                ImageOps.invert(image.convert("RGB")).save(tmp_qr.name, format="PNG")
                return subprocess.run(
                    ["zbarimg", "-q", tmp_qr.name],
                    capture_output=True,
                    text=True,
                ).stdout.strip()

    def execute(self, request):
        """Main execution point for the service.

        Args:
            request (Request): The service request object containing parameters and file information.

        Raises:
            RecoverableError: If an error occurs during processing that should trigger a retry of the analysis.
        """
        _clear_caches()
        start = time()
        result = Result()

        # Attempt to render documents given and dump them to the working directory
        max_pages = int(request.get_param("max_pages_rendered"))
        save_ocr_output = request.get_param("save_ocr_output").lower()
        try:
            pdf_paths = self.render_documents(request, max_pages)
            if pdf_paths:
                pdf_paths = [(ctx, path) for ctx, path in pdf_paths if path]
                # Convert PDF to images for ImageSection
                for context, pdf_path in pdf_paths:
                    self.pdf_to_images(pdf_path, max_pages, context=context)
        except Exception as e:  # noqa: BLE001
            # If we run into an error with no message, raise as a recoverable error to try again
            if not str(e):
                raise RecoverableError("No explicit error message provided, retrying analysis..")
            else:
                # Unable to complete analysis after unexpected error, log exception and give up
                self.log.error(e)
                request.result = result
                return
        # Create an image gallery section to show the renderings
        image_section = ResultImageSection(request, "Preview Image(s)")
        run_ocr_on_first_n_pages = request.get_param("run_ocr_on_first_n_pages")
        previews = [s for s in os.listdir(self.working_directory) if "output" in s]
        preview_hashes = []

        if not previews:
            # No previews found, unable to proceed
            request.result = result
            return

        def attach_images_to_section(run_ocr=False) -> str:
            extracted_text = ""
            for i, preview in enumerate(natsorted(previews)):
                fp = os.path.join(self.working_directory, preview)
                file_bytes = _read_file_bytes(fp)
                preview_hash = sha256(file_bytes).hexdigest()
                if preview_hash in preview_hashes:
                    # We've already added this image, skip it
                    continue
                else:
                    preview_hashes.append(preview_hash)

                ocr_heur_id, ocr_io = None, None
                if run_ocr:
                    # Trigger OCR on the first N pages as specified in the submission
                    ocr_heur_id = 1 if request.deep_scan or (i < run_ocr_on_first_n_pages) else None
                    ocr_io = StringIO()

                context, pg_no = preview[7:].split("-")
                pg_no = pg_no[:-4].zfill(3)

                # Analyze the preview to check if there's any QR code we can extract from it
                qr_result = self.scan_for_QR_codes(Image.open(BytesIO(_read_file_bytes(fp))))
                if qr_result:
                    code_type, code_value = qr_result.split(":", 1)
                    if re.match(FULL_URI, code_value):
                        # Tag URI
                        image_section.add_tag("network.static.uri", code_value)
                    else:
                        # Write data to file
                        with NamedTemporaryFile(dir=self.working_directory, delete=False, mode="w") as fh:
                            fh.write(code_value)

                        request.add_extracted(
                            fh.name,
                            name=f"embedded_code_page_{pg_no}_{context}",
                            description=f"Decoded {code_type} content on page {pg_no}",
                            safelist_interface=self.api_interface,
                        )

                img_name = f"page_{pg_no}_{context}.png"
                image_section.add_image(
                    fp,
                    name=img_name,
                    description=f"Here's the preview for {context} page {pg_no}",
                    ocr_heuristic_id=ocr_heur_id,
                    ocr_io=ocr_io,
                )

                if request.get_param("analyze_render"):
                    request.add_extracted(
                        fp,
                        name=img_name,
                        description=f"Here's the preview for page {i}",
                    )
                if run_ocr:
                    extracted_text += f"{ocr_io.read()}\n\n"
            return extracted_text

        if not run_ocr_on_first_n_pages:
            # Add all images to section (no need to run OCR)
            attach_images_to_section()
        else:
            # If we have a PDF at our disposal,
            # try to extract the text from that rather than relying on OCR for everything
            extracted_text = ""
            pw_list = set(request.temp_submission_data.get("passwords", []))
            if pdf_paths:
                for _, pdf_path in pdf_paths:
                    embedded_image_paths = self.extract_pdf_images(pdf_path, max_pages)
                    extracted_text_path = self.extract_pdf_text(pdf_path, max_pages)

                    # Check if we can extract any hyperlinked content from the PDF
                    doc = _open_fitz_doc(pdf_path)
                    for page in doc:
                        for link in page.get_links():
                            link_uri = link.get("uri", "")
                            if not link_uri:
                                continue
                            if link_uri.startswith("mailto:"):
                                # Tag email address
                                image_section.add_tag("network.email.address", link_uri[7:])
                            else:
                                # Assume this is a URI
                                image_section.add_tag("network.static.uri", link_uri)

                    if extracted_text_path is not None:
                        with open(extracted_text_path, "r") as fh:
                            extracted_text += fh.read()
                        # Add all images to section
                        attach_images_to_section()

                        # We were able to extract content, perform term detection
                        detections = indicator_detections(extracted_text)

                        # Try to extract any images from the page range and run them through OCR
                        for image_path in embedded_image_paths:
                            d = ocr_detections(image_path)

                            # Merge indicator detections
                            for k in set(list(d.keys()) + list(detections.keys())):
                                detections[k] = list(set(detections.get(k, []) + d.get(k, [])))

                        if detections:
                            # If we were able to detect potential passwords, add it to the submission's password list
                            if detections.get("password"):
                                [pw_list.update(extract_passwords(pw_string)) for pw_string in detections["password"]]

                            heuristic = Heuristic(
                                1,
                                signatures={f"{k}_strings": len(v) for k, v in detections.items()},
                            )
                            ocr_section = ResultKeyValueSection(
                                f"Suspicious strings found during OCR analysis on file {request.file_name}"
                            )
                            ocr_section.set_heuristic(heuristic)
                            for k, v in detections.items():
                                ocr_section.set_item(k, v)
                            image_section.add_subsection(ocr_section)
                    else:
                        # Unable to extract text from PDF, run it through Tesseract for term detection
                        extracted_text += attach_images_to_section(run_ocr=True)

                    # Check for the presence of any QR codes embedded in the document
                    embedded_images = [Image.open(image_path) for image_path in embedded_image_paths]
                    qr_code_detections = []
                    for index, image in enumerate(embedded_images):
                        ratio = image.size[0] / image.size[1]
                        if image.size[0] == image.size[1]:
                            # Image is a perfect square, let's check if it's a QR code
                            qr_result = self.scan_for_QR_codes(image)
                            if qr_result:
                                qr_code_detections.append(qr_result)

                        # Check if the ratio between the height and width is 1:2 or vice-versa
                        # This could be a technique to deter tools that scan images in a document for QR codes,
                        elif ratio in [0.5, 2.0]:
                            # Image has a 1:2 or 2:1 ratio, let's check if we can find their other half

                            # Make sure we're not going out of bounds of the embedded images
                            # when looking for the other half
                            if index + 1 >= len(embedded_images):
                                continue

                            for other_half in embedded_images[index + 1 :]:
                                if image.size == other_half.size:
                                    # We found the other half, let's combine them and check if it's a QR code
                                    size = max(image.size[0], image.size[1])
                                    combined_image = Image.new("RGB", (size, size))
                                    if ratio == 0.5:
                                        # Image is taller than it is wider, stack them side-by-side
                                        combined_image.paste(image, (0, 0))
                                        combined_image.paste(other_half, (image.size[0], 0))
                                    else:
                                        # Image is wider than it is taller, stack them top-to-bottom
                                        combined_image.paste(image, (0, 0))
                                        combined_image.paste(other_half, (0, image.size[1]))

                                    qr_result = self.scan_for_QR_codes(combined_image)
                                    if qr_result:
                                        qr_code_detections.append(qr_result)
                                    break

                    # If there are QR code detections, include it as part of the output
                    for i, detection in enumerate(qr_code_detections):
                        code_type, code_value = detection.split(":", 1)
                        if re.match(FULL_URI, code_value):
                            # Tag URI
                            image_section.add_tag("network.static.uri", code_value)
                        else:
                            # Write data to file
                            with NamedTemporaryFile(dir=self.working_directory, delete=False, mode="w") as fh:
                                fh.write(code_value)

                            request.add_extracted(
                                fh.name,
                                name=f"embedded_code_{i}",
                                description=f"Decoded {code_type} content",
                                safelist_interface=self.api_interface,
                            )

            else:
                # Extract text via OCR for non-PDF documents (images)
                attach_images_to_section(run_ocr=True)

            # Check the extracted text for any potential passwords as well
            # Let's make the assumption that a password in a phishing document is likely to be a weak password
            # Ref: https://www.bleepingcomputer.com/news/security/virustotal-finds-hidden-malware-phishing-campaign-in-svg-files/amp/
            pw_list.update(
                {pw for pw in extract_passwords(extracted_text) if 3 <= len(pw) <= 20 and pw.isupper() and pw.isalnum()}
            )

            if pw_list:
                request.temp_submission_data["passwords"] = sorted(pw_list)

            # Tag any network IOCs found in OCR output
            self.tag_network_iocs(image_section, extracted_text)

            # Write OCR output as specified by submissions params
            if save_ocr_output == "no":
                pass
            else:
                with tempfile.NamedTemporaryFile("w", delete=False, suffix=".txt") as extracted_text_fh:
                    extracted_text_fh.write(extracted_text)
                    extracted_text_fh.flush()

                    # Write content to disk to be uploaded
                    add_params = {
                        "path": extracted_text_fh.name,
                        "name": "ocr_output_dump",
                        "description": "OCR Output",
                    }
                    if save_ocr_output == "as_extracted":
                        request.add_extracted(**add_params)
                    elif save_ocr_output == "as_supplementary":
                        request.add_supplementary(**add_params)
                    else:
                        self.log.warning(f"Unknown save method for OCR given: {save_ocr_output}")

            # Check to see if we're dealing with a suspicious PDF
            if request.file_type == "document/pdf":
                try:
                    if pdf_page_count(request.file_path) == 1 and "click" in extracted_text.lower():
                        # Suspected document is part of a phishing campaign
                        ResultTextSection(
                            "Suspected Phishing",
                            body='Single-paged document containing the term "click"',
                            heuristic=Heuristic(2),
                            parent=result,
                        )
                except Exception:  # noqa: BLE001, S110
                    # There was a problem fetching the page count from the PDF, move on..
                    pass
        image_section.promote_as_screenshot()
        result.add_section(image_section)
        request.result = result
        self.log.debug(f"Runtime: {time() - start}s")
