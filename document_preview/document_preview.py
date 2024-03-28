import os
import subprocess
import tempfile
from time import time

from assemblyline_v4_service.common.base import ServiceBase
from assemblyline_v4_service.common.request import ServiceRequest as Request
from assemblyline_v4_service.common.result import (
    Heuristic,
    Result,
    ResultImageSection,
    ResultTextSection,
    ResultKeyValueSection,
)
from assemblyline_v4_service.common.ocr import detections as indicator_detections
from assemblyline_v4_service.common.utils import extract_passwords

from base64 import b64decode, b64encode
from selenium.webdriver import Chrome, ChromeOptions, ChromeService
from natsort import natsorted

from document_preview.helper.emlrender import processEml as eml2image

PDFTOPPM_DPI = os.environ.get("PDFTOPPM_DPI", "150")


def pdfinfo_from_path(fp: str):
    pdfinfo = {}
    for info in subprocess.run(["pdfinfo", fp], capture_output=True).stdout.strip().decode().split("\n"):
        k, v = info.split(":", 1)
        # Clean up spacing
        v = v.lstrip()
        pdfinfo[k] = v
    pdfinfo


def convert_from_path(fp: str, output_directory: str, first_page=1, last_page=None):
    pdf_conv_command = ["pdftoppm", "-r", PDFTOPPM_DPI, "-jpeg", "-f", str(first_page)]
    if last_page:
        pdf_conv_command += ["-l", str(last_page)]
    subprocess.run(pdf_conv_command + [fp, os.path.join(output_directory, "output")], capture_output=True)


class DocumentPreview(ServiceBase):
    def __init__(self, config=None):
        super(DocumentPreview, self).__init__(config)

        browser_options = ChromeOptions()

        # Set brower options depending on service configuration
        browser_cfg = config.get("browser_options", {})
        [browser_options.add_argument(arg) for arg in browser_cfg.get("arguments", [])]
        [browser_options.set_capability(cap_n, cap_v) for cap_n, cap_v in browser_cfg.get("capabilities", {}).items()]

        # Run browser in offline mode only
        self.browser = Chrome(options=browser_options, service=ChromeService(executable_path="/usr/bin/chromedriver"))
        self.browser.set_network_conditions(offline=True, latency=5, throughput=500 * 1024)

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

    def office_conversion(self, file, orientation="portrait", page_range_end=2):
        output_path = os.path.join(self.working_directory, "converted.pdf")
        subprocess.run(
            [
                "unoconv",
                "-f",
                "pdf",
                "-e",
                f"PageRange=1-{page_range_end}",
                "-P",
                f"PaperOrientation={orientation}",
                "-P",
                "PaperFormat=A3",
                "-o",
                output_path,
                file,
            ],
            capture_output=True,
        )
        if os.path.exists(output_path):
            return output_path

    def html_render(self, file_contents) -> str:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_pdf:
            # Load base64'd contents directly into browser as HTML
            self.browser.get(f"data:text/html;base64,{b64encode(file_contents).decode()}")

            # Execute command and save PDF content to disk for image conversion
            tmp_pdf.write(b64decode(self.browser.print_page()))
            tmp_pdf.flush()

            # Page browser back to the beginning (in theory we shouldn't have to go far but just in case)
            while self.browser.current_url != "data:,":
                self.browser.back()

            return tmp_pdf.name

    def pdf_to_images(self, file, max_pages=None):
        convert_from_path(file, self.working_directory, first_page=1, last_page=max_pages)

    def render_documents(self, request: Request, max_pages=1) -> str:
        # Word/Excel/Powerpoint/RTF
        if any(
            request.file_type == f"document/office/{ms_product}"
            for ms_product in ["word", "excel", "powerpoint", "rtf"]
        ):
            orientation = (
                "landscape" if any(request.file_type.endswith(type) for type in ["excel", "powerpoint"]) else "portrait"
            )
            return self.office_conversion(request.file_path, orientation, max_pages)
        # PDF
        elif request.file_type == "document/pdf":
            return request.file_path
        elif request.file_type in ["document/epub", "document/mobi"]:
            return self.ebook_conversion(request)
        # EML/MSG
        elif request.file_type.endswith("email"):
            file_contents = request.file_contents
            # Convert MSG to EML where applicable
            if request.file_type == "document/office/email":
                with tempfile.NamedTemporaryFile() as tmp:
                    subprocess.run(
                        ["msgconvert", "-outfile", tmp.name, request.file_path],
                        capture_output=True,
                    )
                    tmp.seek(0)
                    file_contents = tmp.read()
            elif request.file_type == "document/email" and request.file_contents.startswith(b"<html"):
                # We're dealing with an HTML-formatted email
                return self.html_render(request.file_contents)
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
            return self.html_render(request.file_contents)

    def execute(self, request):
        start = time()
        result = Result()

        # Attempt to render documents given and dump them to the working directory
        max_pages = int(request.get_param("max_pages_rendered"))
        save_ocr_output = request.get_param("save_ocr_output").lower()
        try:
            pdf_path = self.render_documents(request, max_pages)
            if pdf_path:
                # Convert PDF to images for ImageSection
                self.pdf_to_images(pdf_path, max_pages)
        except Exception as e:
            # Unable to complete analysis after unexpected error, give up
            self.log.error(e)
            request.result = result
            return
        # Create an image gallery section to show the renderings
        image_section = ResultImageSection(request, "Preview Image(s)")
        run_ocr_on_first_n_pages = request.get_param("run_ocr_on_first_n_pages")
        previews = [s for s in os.listdir(self.working_directory) if "output" in s]

        if not run_ocr_on_first_n_pages:
            # Add all images to section (no need to run OCR)
            for i, preview in enumerate(natsorted(previews)):
                img_name = f"page_{str(i).zfill(3)}.jpeg"
                fp = os.path.join(self.working_directory, preview)
                image_section.add_image(
                    fp,
                    name=img_name,
                    description=f"Here's the preview for page {i}",
                )
        else:
            # If we have a PDF at our disposal,
            # try to extract the text from that rather than relying on OCR for everything
            extracted_text_path = self.extract_pdf_text(pdf_path, max_pages) if pdf_path else None
            extracted_text = ""
            if extracted_text_path is not None:
                extracted_text = open(extracted_text_path, "r").read()
                # Add all images to section
                for i, preview in enumerate(natsorted(previews)):
                    img_name = f"page_{str(i).zfill(3)}.jpeg"
                    fp = os.path.join(self.working_directory, preview)
                    image_section.add_image(
                        fp,
                        name=img_name,
                        description=f"Here's the preview for page {i}",
                    )

                    if request.get_param("analyze_render"):
                        request.add_extracted(
                            fp,
                            name=img_name,
                            description=f"Here's the preview for page {i}",
                        )

                # We were able to extract content, perform term detection
                detections = indicator_detections(extracted_text)

                if detections:
                    # If we were able to detect potential passwords, add it to the submission's password list
                    if detections.get("password"):
                        pw_list = set(self.temp_submission_data.get("passwords", []))
                        [pw_list.update(extract_passwords(pw_string)) for pw_string in detections["password"]]
                        self.temp_submission_data["passwords"] = sorted(pw_list)

                    heuristic = Heuristic(1, signatures={f"{k}_strings": len(v) for k, v in detections.items()})
                    ocr_section = ResultKeyValueSection(
                        f"Suspicious strings found during OCR analysis on file {request.file_name}"
                    )
                    ocr_section.set_heuristic(heuristic)
                    for k, v in detections.items():
                        ocr_section.set_item(k, v)
                    image_section.add_subsection(ocr_section)
            else:
                # Unable to extract text from PDF, run it through Tesseract for term detection
                for i, preview in enumerate(natsorted(previews)):
                    # Trigger OCR on the first N pages as specified in the submission
                    # Otherwise, just add the image without performing OCR analysis
                    ocr_heur_id = 1 if request.deep_scan or (i < run_ocr_on_first_n_pages) else None
                    ocr_io = tempfile.NamedTemporaryFile("w", delete=False)
                    img_name = f"page_{str(i).zfill(3)}.jpeg"
                    image_section.add_image(
                        f"{self.working_directory}/{preview}",
                        name=img_name,
                        description=f"Here's the preview for page {i}",
                        ocr_heuristic_id=ocr_heur_id,
                        ocr_io=ocr_io,
                    )

                    if request.get_param("analyze_render"):
                        request.add_extracted(
                            f"{self.working_directory}/{preview}",
                            name=img_name,
                            description=f"Here's the preview for page {i}",
                        )

                    extracted_text += f"{ocr_io.read()}\n\n"

            # Write OCR output as specified by submissions params
            if save_ocr_output == "no":
                pass
            else:
                with tempfile.NamedTemporaryFile("w", delete=False) as extracted_text_fh:
                    extracted_text_fh.write(extracted_text)
                    extracted_text_fh.flush()

                    # Write content to disk to be uploaded
                    add_params = dict(path=extracted_text_fh.name, name="ocr_output_dump", description="OCR Output")
                    if save_ocr_output == "as_extracted":
                        request.add_extracted(**add_params)
                    elif save_ocr_output == "as_supplementary":
                        request.add_supplementary(**add_params)
                    else:
                        self.log.warning(f"Unknown save method for OCR given: {save_ocr_output}")

            # Check to see if we're dealing with a suspicious PDF
            if request.file_type == "document/pdf":
                with open(ocr_io.name, "r") as fp:
                    ocr_content = fp.read()
                try:
                    if pdfinfo_from_path(request.file_path)["Pages"] == 1 and "click" in ocr_content.lower():
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
