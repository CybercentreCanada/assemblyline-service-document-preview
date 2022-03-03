import json
import os
import pytesseract
import re
import shutil
import subprocess

from natsort import natsorted
from pdf2image import convert_from_path
from PIL import Image

from assemblyline_v4_service.common.base import ServiceBase
from assemblyline_v4_service.common.result import BODY_FORMAT, Result, ResultImageSection, ResultSection, Heuristic

from document_preview.helper.emlrender import processEml as eml2image
from document_preview.helper.outlookmsgfile import load as msg2eml

# TODO: Would prefer this mapping to be dynamic from trusted sources (ie. import from library), but will copy-paste for now
INDICATORS_MAPPING = {
    ('ransomware', 1):   re.compile('|'.join([
        # https://github.com/cuckoosandbox/community/blob/master/modules/signatures/windows/ransomware_message.py
        "your files", "your data", "your documents", "restore files",
        "restore data", "restore the files", "restore the data", "recover files",
        "recover data", "recover the files", "recover the data", "has been locked",
        "pay fine", "pay a fine", "pay the fine", "decrypt", "encrypt",
        "recover files", "recover data", "recover them", "recover your",
        "recover personal", "bitcoin", "secret server", "secret internet server",
        "install tor", "download tor", "tor browser", "tor gateway",
        "tor-browser", "tor-gateway", "torbrowser", "torgateway", "torproject.org",
        "ransom", "bootkit", "rootkit", "payment", "victim", "AES128", "AES256",
        "AES 128", "AES 256", "AES-128", "AES-256", "RSA1024", "RSA2048",
        "RSA4096", "RSA 1024", "RSA 2048", "RSA 4096", "RSA-1024", "RSA-2048",
        "RSA-4096", "private key", "personal key", "your code", "private code",
        "personal code", "enter code", "your key", "unique key"
    ])),
    ('macros', 2): re.compile('|'.join([
        # https://github.com/cuckoosandbox/community/blob/17d57d46ccbca0327a8299cb93abba8604b74df7/modules/signatures/windows/office_enablecontent_ocr.py
        "enable macro",
        "enable content",
        "enable editing",
    ]))
}


class DocumentPreview(ServiceBase):
    def __init__(self, config=None):
        super(DocumentPreview, self).__init__(config)

    def start(self):
        self.log.debug("Document preview service started")

    def stop(self):
        self.log.debug("Document preview service ended")

    def libreoffice_conversion(self, file):
        subprocess.check_output(
            "libreoffice --headless --convert-to pdf --outdir " + self.working_directory + " " + file, shell=True)

        pdf_file = [s for s in os.listdir(self.working_directory) if ".pdf" in s][0]

        if pdf_file:
            return (True, pdf_file)
        else:
            return False

    def pdf_to_images(self, file):
        pages = convert_from_path(file)

        i = 0
        for page in pages:
            page.save(self.working_directory + "/output_" + str(i) + ".jpeg")
            i += 1

    def render_documents(self, file_type, file, file_contents):
        # Word/Excel/Powerpoint
        if any(file_type == f'document/office/{ms_product}' for ms_product in ['word', 'excel', 'powerpoint']):
            converted = self.libreoffice_conversion(file)
            if converted[0]:
                self.pdf_to_images(self.working_directory + "/" + converted[1])
        # PDF
        elif file_type == 'document/pdf':
            self.pdf_to_images(file)
        # EML/MSG
        elif file_type.endswith('email'):
            # Convert MSG to EML where applicable
            file_contents = msg2eml(file).as_bytes() if file_type == 'document/office/email' else file_contents

            # Render EML as PNG
            eml2image(file_contents, self.working_directory, self.log)

        # Images don't required to be rendered, however could still be useful for OCR analysis
        elif file_type.startswith('image'):
            shutil.move(file, os.path.join(self.working_directory, 'output_0'))

    def execute(self, request):
        result = Result()

        # Attempt to render documents given and dump them to the working directory
        self.render_documents(request.file_type, request.file_path, request.file_contents)
        images = list()

        # Create an image gallery section to show the renderings
        if any("output" in s for s in os.listdir(self.working_directory)):
            image_section = ResultImageSection(request, "Successfully extracted the preview.")

            i = 0
            previews = [s for s in os.listdir(self.working_directory) if "output" in s]
            for preview in natsorted(previews):
                image_path = f"{self.working_directory}/{preview}"
                images.append(image_path)
                title = f"preview_{i}.jpeg"
                desc = f"Here's the preview for page {i}"
                image_section.add_image(image_path, title, desc)
                i += 1

            result.add_section(image_section)

        # Proceed with analysis of output images
        for image_path in images:
            ocr_output = ''
            with Image.open(image_path) as img:
                ocr_output = pytesseract.image_to_string(img)
            parent = ResultSection(f'OCR Analyis on {os.path.basename(image_path)}')
            for indicator, regex_exp in INDICATORS_MAPPING.items():
                search_results = regex_exp.findall(ocr_output) + regex_exp.findall(ocr_output.lower())
                if search_results:
                    self.log.info(f'Found {indicator[0]}')
                    body = {
                        term: [line for line in ocr_output.split('\n') + ocr_output.lower().split('\n') if term in line]
                        for term in set(search_results)}
                    ResultSection(
                        f'OCR Detection: {indicator[0]}', body=json.dumps(body),
                        body_format=BODY_FORMAT.JSON,
                        heuristic=Heuristic(heur_id=indicator[1],
                                            frequency=len(search_results)),
                        parent=parent)
            if parent.subsections:
                result.add_section(parent)

        request.result = result
