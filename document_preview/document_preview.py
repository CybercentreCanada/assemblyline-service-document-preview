import imgkit
import os
import subprocess
import tempfile
from time import time

from natsort import natsorted
from pdf2image import convert_from_path

from assemblyline_v4_service.common.base import ServiceBase
from assemblyline_v4_service.common.result import Result, ResultImageSection
from assemblyline_v4_service.common.request import ServiceRequest as Request

from document_preview.helper.emlrender import processEml as eml2image
from aspose.cells import SaveFormat as WorkbookSaveFormat, Workbook
from aspose.slides import Presentation
from aspose.slides.export import SaveFormat as PresentationSaveFormat

from aspose.words import Document, SaveFormat as WordsSaveFormat


WEBP_MAX_SIZE = 16383


class DocumentPreview(ServiceBase):
    def __init__(self, config=None):
        super(DocumentPreview, self).__init__(config)

    def start(self):
        self.log.debug("Document preview service started")

    def stop(self):
        self.log.debug("Document preview service ended")

    def libreoffice_conversion(self, file, convert_to="pdf"):
        subprocess.run(["/usr/lib/libreoffice/program/soffice.bin", "--headless",
                        "--convert-to", convert_to,
                        "--outdir", self.working_directory, file], capture_output=True)

        converted_file = [s for s in os.listdir(self.working_directory) if f".{convert_to}" in s][0]

        if converted_file:
            return (True, converted_file)
        else:
            return (False, None)

    def office_conversion(self, file, orientation="portrait", page_range_end=2):
        subprocess.run(["unoconv", "-f", "pdf",
                        "-e", f"PageRange=1-{page_range_end}",
                        "-P", f"PaperOrientation={orientation}",
                        "-P", "PaperFormat=A3",
                        "-o", f"{self.working_directory}/", file], capture_output=True)

        converted_file = [s for s in os.listdir(self.working_directory) if ".pdf" in s]

        if converted_file:
            return (True, converted_file[0])
        else:
            return (False, None)

    def pdf_to_images(self, file, max_pages=None):
        pages = convert_from_path(file, first_page=1, last_page=max_pages)

        i = 0
        for page in pages:
            page.save(self.working_directory + "/output_" + str(i) + ".jpeg")
            i += 1

    def render_documents(self, request: Request, max_pages=1):

        if request.file_type == 'document/pdf':
            # PDF
            self.pdf_to_images(request.file_path, max_pages)
        # EML/MSG
        elif request.file_type.endswith('email'):
            file_contents = request.file_contents
            # Convert MSG to EML where applicable
            if request.file_type == 'document/office/email':
                with tempfile.NamedTemporaryFile() as tmp:
                    subprocess.run(['msgconvert', '-outfile', tmp.name, request.file_path])
                    tmp.seek(0)
                    file_contents = tmp.read()

            # Render EML as PNG
            # If we have internet access, we'll attempt to load external images
            eml2image(file_contents, self.working_directory, self.log,
                      load_ext_images=self.service_attributes.docker_config.allow_internet_access,
                      load_images=request.get_param('load_email_images'))
        else:
            # Word/Excel/Powerpoint
            aspose_cls, save_format_cls = {
                'document/office/excel': (Workbook, WorkbookSaveFormat),
                'document/office/word': (Document, WordsSaveFormat),
                'document/office/powerpoint': (Presentation, PresentationSaveFormat),
            }.get(request.file_type, (None, None))

            if not aspose_cls and request.file_type.startswith('document/office'):
                self.log.warning(f'Aspose unable to handle: {request.file_type}')
                return

            with tempfile.NamedTemporaryFile() as tmp_file:
                doc = aspose_cls(request.file_path)
                doc.save(tmp_file.name, save_format_cls.PDF)
                tmp_file.seek(0)
                self.pdf_to_images(tmp_file.name, max_pages)

    def execute(self, request):
        start = time()
        result = Result()

        # Attempt to render documents given and dump them to the working directory
        max_pages = int(request.get_param('max_pages_rendered'))
        try:
            self.render_documents(request, max_pages)
        except Exception as e:
            # Unable to complete analysis after unexpected error, give up
            self.log.error(e)
            request.result = result
            return
        # Create an image gallery section to show the renderings
        if any("output" in s for s in os.listdir(self.working_directory)):
            previews = [s for s in os.listdir(self.working_directory) if "output" in s]
            image_section = ResultImageSection(request,  "Successfully extracted the preview.")
            heur_id = 1 if request.deep_scan or request.get_param('run_ocr') else None
            [image_section.add_image(f"{self.working_directory}/{preview}",
                                     name=f"page_{str(i).zfill(3)}.jpeg", description=f"Here's the preview for page {i}",
                                     ocr_heuristic_id=heur_id)
             for i, preview in enumerate(natsorted(previews))]

            result.add_section(image_section)
        request.result = result
        self.log.debug(f"Runtime: {time() - start}s")
