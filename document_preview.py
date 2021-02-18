import subprocess, os
from natsort import natsorted
from pdf2image import convert_from_path

from assemblyline_v4_service.common.base import ServiceBase
from assemblyline_v4_service.common.result import Result, ResultSection


class DocumentPreview(ServiceBase):
		def __init__(self, config=None):
			super(DocumentPreview, self).__init__(config)

		def start(self):
			self.log.debug("Document preview service started")

		def stop(self):
			self.log.debug("Document preview service ended")

		def libreoffice_conversion(self, file):
			subprocess.check_output("libreoffice --headless --convert-to pdf --outdir " + self.working_directory + " " + file, shell=True)

			pdf_file = [s for s in os.listdir(self.working_directory) if ".pdf" in s][0]

			if pdf_file:
				return (True, pdf_file)
			else:
				return False

		def pdf_to_images(self, file, max_pages):
			pages = convert_from_path(file, last_page=int(max_pages))

			i = 0
			for page in pages:
				page.save(self.working_directory + "/output_" + str(i) + ".jpeg")
				i += 1

		def execute(self, request):
			result = Result()

			file = request.file_path
			file_type = request.file_type
			max_pages = request.get_param('max_pages')

			if file_type == 'document/office/word' or file_type == 'document/office/excel' or file_type == 'document/office/powerpoint':
				converted = self.libreoffice_conversion(file)
				if converted[0]:
					self.pdf_to_images(self.working_directory + "/" + converted[1], max_pages)
			elif file_type == 'document/pdf':
				self.pdf_to_images(file, max_pages)
			else:
				try:
					converted = self.libreoffice_conversion(file)
					if converted[0]:
						self.pdf_to_images(self.working_directory + "/" + converted[1], max_pages)
				except:
					# Conversion not successfull
					pass

			if any("output" in s for s in os.listdir(self.working_directory)):
				text_section = ResultSection("Successfully extracted the preview.")
				result.add_section(text_section)

				i = 0
				previews = [s for s in os.listdir(self.working_directory) if "output" in s]
				for preview in natsorted(previews):
					request.add_extracted(self.working_directory + '/' + preview, "preview_" + str(i) + ".jpeg", 'Here\'s the preview for page ' + str(i))
					i += 1

			request.result = result