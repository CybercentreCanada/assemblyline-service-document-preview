from doctest import Example
import json
import os
import subprocess

from natsort import natsorted
from pdf2image import convert_from_path

from assemblyline_v4_service.common.base import ServiceBase
from assemblyline_v4_service.common.result import BODY_FORMAT, Result, ResultImageSection, ResultJSONSection, Heuristic, ResultTextSection
from assemblyline_v4_service.common.extractor.ocr import ocr_detections

from document_preview.helper.emlrender import processEml as eml2image
from document_preview.helper.outlookmsgfile import load as msg2eml


class DocumentPreview(ServiceBase):
    def __init__(self, config=None):
        super(DocumentPreview, self).__init__(config)

    def start(self):
        self.log.debug("Document preview service started")

    def stop(self):
        self.log.debug("Document preview service ended")

    def libreoffice_conversion(self, file, convert_to="pdf"):
        subprocess.check_output(
            f"libreoffice --headless --convert-to {convert_to} --outdir " + self.working_directory + " " + file,
            shell=True)

        converted_file = [s for s in os.listdir(self.working_directory) if f".{convert_to}" in s][0]

        if converted_file:
            return (True, converted_file)
        else:
            return (False, None)

    def office_conversion(self, file, orientation="portrait", page_range_end=2):
        subprocess.check_output(
            f"unoconv -f pdf -e PageRange=1-{page_range_end} -e PaperOrientation={orientation} -o {self.working_directory}/ {file}",
            shell=True)

        converted_file = [s for s in os.listdir(self.working_directory) if f".pdf" in s]

        if converted_file:
            return (True, converted_file[0])
        else:
            return (False, None)

    def pdf_to_images(self, file):
        pages = convert_from_path(file)

        i = 0
        for page in pages:
            page.save(self.working_directory + "/output_" + str(i) + ".jpeg")
            i += 1

    def render_documents(self, file_type, file, file_contents, max_pages=1):
        # Word/Excel/Powerpoint
        if any(file_type == f'document/office/{ms_product}' for ms_product in ['word', 'excel', 'powerpoint']):
            orientation = "landscape" if file_type.endswith('excel') else "portrait"
            converted = self.office_conversion(file, orientation, max_pages)
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
        elif file_type.endswith('emf'):
            self.libreoffice_conversion(file, convert_to="png")

    def execute(self, request):
        result = Result()

        # Attempt to render documents given and dump them to the working directory
        max_pages = request.get_param('max_pages_rendered')
        try:
            self.render_documents(request.file_type, request.file_path, request.file_contents, max_pages)
        except Exception as e:
            # Unable to complete analysis after unexpected error, give up
            self.log.error(e)
            request.result = result
            return
        # Create an image gallery section to show the renderings
        if any("output" in s for s in os.listdir(self.working_directory)):
            previews = [s for s in os.listdir(self.working_directory) if "output" in s]
            image_section = ResultImageSection(request,  "Successfully extracted the preview.")
            [image_section.add_image(f"{self.working_directory}/{preview}",
                                     name=f"preview_{i}.jpeg", description=f"Here's the preview for page {i}",
                                     ocr_heuristic_id=1)
             for i, preview in enumerate(natsorted(previews))]

            result.add_section(image_section)
        request.result = result
