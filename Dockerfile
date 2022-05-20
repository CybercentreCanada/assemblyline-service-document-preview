ARG branch=latest
FROM cccs/assemblyline-v4-service-base:$branch

ENV SERVICE_PATH document_preview.document_preview.DocumentPreview

USER root

RUN mkdir -p /usr/share/man/man1mkdir -p /usr/share/man/man1
RUN apt-get update && apt-get install -y wget tesseract-ocr libemail-outlook-message-perl
RUN wget https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6-1/wkhtmltox_0.12.6-1.buster_amd64.deb
RUN apt-get install -y poppler-utils ./wkhtmltox_0.12.6-1.buster_amd64.deb --no-install-recommends
RUN pip install pdf2image Pillow natsort imgkit compoundfiles compressed_rtf pytesseract
RUN pip install git+https://github.com/unoconv/unoconv.git

# Install Libreoffice
RUN wget https://tdf.mirror.rafal.ca/libreoffice/stable/7.3.3/deb/x86_64/LibreOffice_7.3.3_Linux_x86-64_deb.tar.gz
RUN tar zxvf LibreOffice_7.3.3_Linux_x86-64_deb.tar.gz && rm -f LibreOffice_7.3.3_Linux_x86-64_deb.tar.gz
RUN dpkg -i LibreOffice_7.3.3.2_Linux_x86-64_deb/DEBS/*.deb && rm -rf LibreOffice_7.3.3_Linux_x86-64_deb
RUN apt-get install -y libdbus-1-3 libcups2 libsm6 libice6
RUN ln -n -s /opt/libreoffice7.3 /usr/lib/libreoffice

USER assemblyline

WORKDIR /opt/al_service
COPY . .

ARG version=4.0.0.dev1
USER root
RUN sed -i -e "s/\$SERVICE_TAG/$version/g" service_manifest.yml
RUN unoconv --listener &

USER assemblyline
