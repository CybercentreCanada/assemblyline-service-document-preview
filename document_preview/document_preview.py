import os
import subprocess
import tempfile
from base64 import b64decode, b64encode
from hashlib import sha256
from io import StringIO
from time import time
from typing import List, Optional, Tuple
from zipfile import BadZipFile, ZipFile

import pandas
from assemblyline.common import forge
from assemblyline.common.exceptions import RecoverableError
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
from multidecoder.decoders.network import find_emails, find_urls
from natsort import natsorted
from selenium.common.exceptions import NoAlertPresentException, WebDriverException
from selenium.webdriver import Chrome, ChromeOptions, ChromeService
from selenium.webdriver.common.print_page_options import PrintOptions

from document_preview.helper.emlrender import processEml as eml2image

PDFTOPPM_DPI = os.environ.get("PDFTOPPM_DPI", "150")
IDENTIFY = forge.get_identify(use_cache=os.environ.get("PRIVILEGED", "false").lower() == "true")


def pdfinfo_from_path(fp: str):
    pdfinfo = {}
    for info in subprocess.run(["pdfinfo", fp], capture_output=True).stdout.strip().decode().split("\n"):
        k, v = info.split(":", 1)
        # Clean up spacing
        v = v.lstrip()
        pdfinfo[k] = v
    return pdfinfo


def convert_from_path(fp: str, output_directory: str, first_page=1, last_page=None, context="original"):
    pdf_conv_command = ["pdftoppm", "-r", PDFTOPPM_DPI, "-png", "-f", str(first_page)]
    if last_page:
        pdf_conv_command += ["-l", str(last_page)]
    subprocess.run(
        pdf_conv_command + [fp, os.path.join(output_directory, f"output_{context}")],
        capture_output=True,
    )


class DocumentPreview(ServiceBase):
    def __init__(self, config=None):
        super(DocumentPreview, self).__init__(config)
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
        self.log.debug("Document preview service started")

    def stop(self):
        self.log.debug("Document preview service ended")

    def extract_pdf_text(self, path: str, max_pages: int) -> str:
        output_path = os.path.join(self.working_directory, "extracted_text")
        subprocess.run(
            ["pdftotext", "-f", "1", "-l", str(max_pages), path, output_path],
            capture_output=True,
        )

        if os.path.exists(output_path):
            return output_path

    def extract_pdf_images(self, path: str, max_pages: int) -> List[str]:
        output_path_prefix = os.path.join(self.working_directory, "extracted_image")
        subprocess.run(
            [
                "pdfimages",
                "-f",
                "1",
                "-l",
                str(max_pages),
                "-png",
                path,
                output_path_prefix,
            ],
            capture_output=True,
        )

        return [
            os.path.join(self.working_directory, f)
            for f in os.listdir(self.working_directory)
            if f.startswith("extracted_image")
        ]

    def ebook_conversion(self, request: Request):
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

    def html_render(self, file_contents, max_pages=1) -> str:
        if b"window.location.href = " in file_contents:
            # Document contains code that will cause a redirect, something we likely can't follow
            return

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_pdf:
            # Load base64'd HTML contents directly into new window of browser
            self.browser.switch_to.new_window()
            self.browser.get(f"data:text/html;base64,{b64encode(file_contents).decode()}")

            # Execute command and save PDF content to disk for image conversion
            print_opt = PrintOptions()
            print_opt.page_ranges = [1, max_pages]

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
                tmp_pdf.write(b64decode(self.browser.print_page(print_opt)))
                tmp_pdf.flush()
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
        convert_from_path(file, self.working_directory, first_page=1, last_page=max_pages, context=context)

    def render_documents(self, request: Request, max_pages=1) -> Optional[List[Tuple[str, str]]]:
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
            eml2image(
                file_contents,
                self.working_directory,
                self.log,
                load_ext_images=False,
                load_images=request.get_param("load_email_images"),
            )
        # HTML
        elif request.file_type == "code/html":
            # Render the original HTML first
            pdf_files = []
            pdf_files.append(("original", self.html_render(request.file_contents, max_pages)))

            # Render the HTML with scripts removed
            bsoup = BeautifulSoup(request.file_contents, "html.parser")
            [s.extract() for s in bsoup("script")]
            scriptless_html = str(bsoup).encode()
            pdf_files.append(("scriptless", self.html_render(scriptless_html, max_pages)))

            # Render the HTML with styling removed (we'll use this version for OCR)
            [s.extract() for s in bsoup("style")]
            styleless_html = str(bsoup).encode()
            pdf_files.append(("styleless", self.html_render(styleless_html, max_pages)))
            return pdf_files

    def tag_network_iocs(self, section: ResultSection, ocr_content: str) -> None:
        [section.add_tag("network.email.address", node.value) for node in find_emails(ocr_content.encode())]
        [section.add_tag("network.static.uri", node.value) for node in find_urls(ocr_content.encode())]

    def execute(self, request):
        start = time()
        result = Result()

        # Attempt to render documents given and dump them to the working directory
        max_pages = int(request.get_param("max_pages_rendered"))
        save_ocr_output = request.get_param("save_ocr_output").lower()
        try:
            pdf_paths = self.render_documents(request, max_pages)
            if pdf_paths:
                # Convert PDF to images for ImageSection
                for context, pdf_path in pdf_paths:
                    self.pdf_to_images(pdf_path, max_pages, context=context)
        except Exception as e:
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
                with open(os.path.join(self.working_directory, preview), "rb") as f:
                    preview_hash = sha256(f.read()).hexdigest()
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
                pg_no = pg_no[:-4]

                img_name = f"page_{pg_no.zfill(3)}_{context}.png"
                fp = os.path.join(self.working_directory, preview)
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
                    extracted_text_path = self.extract_pdf_text(pdf_path, max_pages)
                    if extracted_text_path is not None:
                        extracted_text += open(extracted_text_path, "r").read()
                        # Add all images to section
                        attach_images_to_section()

                        # We were able to extract content, perform term detection
                        detections = indicator_detections(extracted_text)

                        # Try to extract any images from the page range and run them through OCR
                        for image_path in self.extract_pdf_images(pdf_path, max_pages):
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
                    add_params = dict(
                        path=extracted_text_fh.name,
                        name="ocr_output_dump",
                        description="OCR Output",
                    )
                    if save_ocr_output == "as_extracted":
                        request.add_extracted(**add_params)
                    elif save_ocr_output == "as_supplementary":
                        request.add_supplementary(**add_params)
                    else:
                        self.log.warning(f"Unknown save method for OCR given: {save_ocr_output}")

            # Check to see if we're dealing with a suspicious PDF
            if request.file_type == "document/pdf":
                try:
                    if pdfinfo_from_path(request.file_path)["Pages"] == 1 and "click" in extracted_text.lower():
                        # Suspected document is part of a phishing campaign
                        ResultTextSection(
                            "Suspected Phishing",
                            body='Single-paged document containing the term "click"',
                            heuristic=Heuristic(2),
                            parent=result,
                        )
                except Exception:
                    # There was a problem fetching the page count from the PDF, move on..
                    pass
        image_section.promote_as_screenshot()
        result.add_section(image_section)
        request.result = result
        self.log.debug(f"Runtime: {time() - start}s")
