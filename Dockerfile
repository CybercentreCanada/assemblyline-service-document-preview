ARG branch=latest
FROM cccs/assemblyline-v4-service-base:$branch

ENV SERVICE_PATH document_preview.document_preview.DocumentPreview

USER root

RUN mkdir -p /usr/share/man/man1mkdir -p /usr/share/man/man1
RUN apt-get update && apt-get install -y wget
RUN wget https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6-1/wkhtmltox_0.12.6-1.buster_amd64.deb
RUN apt-get install -y poppler-utils libreoffice  ./wkhtmltox_0.12.6-1.buster_amd64.deb --no-install-recommends
RUN pip install pdf2image Pillow natsort imgkit compoundfiles compressed_rtf

# Install Image/Science libraries for Python & Tesseract OCR engine/ Language plug-ins
RUN apt-get install -y libjpeg-dev zlib1g-dev imagemagick tesseract-ocr && rm -rf /var/lib/apt/lists/*
RUN pip install numpy scipy matplotlib pytesseract

USER assemblyline

WORKDIR /opt/al_service
COPY . .

ARG version=4.0.0.dev1
USER root
RUN sed -i -e "s/\$SERVICE_TAG/$version/g" service_manifest.yml

USER assemblyline
