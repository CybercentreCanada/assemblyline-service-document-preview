import math
import os
import subprocess
import tempfile
from time import time

from natsort import natsorted
from pdf2image import convert_from_path

from assemblyline_v4_service.common.base import ServiceBase
from assemblyline_v4_service.common.result import Result, ResultImageSection

from document_preview.helper.emlrender import processEml as eml2image
from PIL import Image

WEBP_MAX_SIZE = 16383


class DocumentPreview(ServiceBase):
    def __init__(self, config=None):
        super(DocumentPreview, self).__init__(config)

    def start(self):
        subprocess.Popen(["unoconv", "--listener"])
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
            f"unoconv -f pdf -e PageRange=1-{page_range_end} -P PaperOrientation={orientation} -P PaperFormat=A3 -o {self.working_directory}/ {file}",
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
            if file_type == 'document/office/email':
                with tempfile.NamedTemporaryFile() as tmp:
                    subprocess.run(['msgconvert', '-outfile', tmp.name, file])
                    tmp.seek(0)
                    file_contents = tmp.read()

            # Render EML as PNG
            # If we have internet access, we'll attempt to load external images
            output_image = eml2image(file_contents, self.working_directory, self.log,
                                     load_images=self.service_attributes.docker_config.allow_internet_access)
            img = Image.open(output_image)
            img_dim = img.size
            if img_dim[1] > WEBP_MAX_SIZE:
                pos_y, index = 0, 0
                # Split up image into smaller pieces
                while pos_y < img_dim[1]:
                    height = WEBP_MAX_SIZE
                    if pos_y + height > img_dim[1]:
                        height = img_dim[1] - pos_y
                    box = (0, pos_y, img_dim[0], pos_y + height)
                    slice = img.crop(box)
                    slice.save(f"{output_image}_{index}", "PNG")
                    index += 1
                    pos_y = index * WEBP_MAX_SIZE

                os.remove(output_image)

        elif file_type.endswith('emf'):
            self.libreoffice_conversion(file, convert_to="png")

    def execute(self, request):
        start = time()
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
                                     name=f"page_{str(i).zfill(3)}.jpeg", description=f"Here's the preview for page {i}",
                                     ocr_heuristic_id=1)
             for i, preview in enumerate(natsorted(previews))]

            result.add_section(image_section)
        request.result = result
        self.log.debug(f"Runtime: {time() - start}s")
