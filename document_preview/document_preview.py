import json
import os
import subprocess

from natsort import natsorted
from pdf2image import convert_from_path

from assemblyline_v4_service.common.base import ServiceBase
from assemblyline_v4_service.common.result import BODY_FORMAT, Result, ResultImageSection, ResultJSONSection, Heuristic
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

    def execute(self, request):
        result = Result()

        # Attempt to render documents given and dump them to the working directory
        self.render_documents(request.file_type, request.file_path, request.file_contents)
        max_pages = request.get_param('max_pages_rendered')
        images = list()

        # Create an image gallery section to show the renderings
        if any("output" in s for s in os.listdir(self.working_directory)):
            previews = [s for s in os.listdir(self.working_directory) if "output" in s]
            total_pages = len(previews)
            image_section = ResultImageSection(request,
                                               "Successfully extracted the preview. "
                                               f"Displaying {min(max_pages, total_pages)} of {total_pages}.")
            for i, preview in enumerate(natsorted(previews)):
                if i >= max_pages:
                    break
                image_path = f"{self.working_directory}/{preview}"
                images.append(image_path)
                title = f"preview_{i}.jpeg"
                desc = f"Here's the preview for page {i}"
                image_section.add_image(image_path, title, desc)

            result.add_section(image_section)

        # Proceed with analysis of output images
        for i, image_path in enumerate(images):
            if i >= max_pages:
                break

            detections = ocr_detections(image_path)
            if any(v for v in detections.values()):
                result.add_section(
                    ResultJSONSection(f'OCR Analysis on {os.path.basename(image_path)}',
                                      body=json.dumps(detections),
                                      heuristic=Heuristic(1, signatures={k: len(v) for k, v in detections.items()}))
                )
        request.result = result
