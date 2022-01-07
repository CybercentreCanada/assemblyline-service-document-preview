import os
import subprocess

from natsort import natsorted
from pdf2image import convert_from_path

from assemblyline_v4_service.common.base import ServiceBase
from assemblyline_v4_service.common.result import Heuristic, Result, ResultImageSection

from helper.emlrender import processEml as eml2image
from helper.outlookmsgfile import load as msg2eml


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

    def execute(self, request):
        result = Result()

        file = request.file_path
        file_type = request.file_type

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
            file_contents = msg2eml(file).as_bytes() if file_type == 'document/office/email' else request.file_contents

            # Render EML as PNG
            eml2image(file_contents, self.working_directory, self.log)

        # Attempt to preview unknown document format
        else:
            try:
                converted = self.libreoffice_conversion(file)
                if converted[0]:
                    self.pdf_to_images(self.working_directory + "/" + converted[1])
            except:
                # Conversion not successfull
                pass

        if any("output" in s for s in os.listdir(self.working_directory)):
            image_section = ResultImageSection(request, "Successfully extracted the preview.")

            i = 0
            previews = [s for s in os.listdir(self.working_directory) if "output" in s]
            for preview in natsorted(previews):
                image_path = f"{self.working_directory}/{preview}"
                title = f"preview_{i}.jpeg"
                desc = f"Here's the preview for page {i}"
                if request.get_param('analyze_output'):
                    request.add_extracted(image_path, title, desc)
                image_section.add_image(image_path, title, desc)
                i += 1

            result.add_section(image_section)

        request.result = result
