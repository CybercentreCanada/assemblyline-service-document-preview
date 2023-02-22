ARG branch=latest
FROM cccs/assemblyline-v4-service-base:$branch

ENV SERVICE_PATH document_preview.document_preview.DocumentPreview
ENV LIBRE_VERSION=7.4
ENV LIBRE_BUILD_VERSION=${LIBRE_VERSION}.4

USER root

RUN mkdir -p /usr/share/man/man1mkdir -p /usr/share/man/man1
RUN apt-get update && apt-get install -y wget tesseract-ocr libemail-outlook-message-perl libgdiplus unzip
RUN wget https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6-1/wkhtmltox_0.12.6-1.buster_amd64.deb
RUN apt-get install -y poppler-utils ./wkhtmltox_0.12.6-1.buster_amd64.deb --no-install-recommends &&\
    rm -f ./wkhtmltox_0.12.6-1.buster_amd64.deb
RUN pip install pdf2image Pillow natsort imgkit compoundfiles compressed_rtf pytesseract

# Install Libreoffice
RUN pip install unoconv
RUN wget https://tdf.mirror.rafal.ca/libreoffice/stable/${LIBRE_BUILD_VERSION}/deb/x86_64/LibreOffice_${LIBRE_BUILD_VERSION}_Linux_x86-64_deb.tar.gz
RUN tar zxvf LibreOffice_${LIBRE_BUILD_VERSION}_Linux_x86-64_deb.tar.gz && rm -f LibreOffice_${LIBRE_BUILD_VERSION}_Linux_x86-64_deb.tar.gz
RUN dpkg -i LibreOffice_${LIBRE_BUILD_VERSION}*/DEBS/*.deb && rm -rf LibreOffice_${LIBRE_BUILD_VERSION}*
RUN apt-get install -y libdbus-1-3 libcups2 libsm6 libice6
RUN ln -n -s /opt/libreoffice${LIBRE_VERSION} /usr/lib/libreoffice

# Install Chrome for headless rendering of HTML documents
RUN wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb && \
    apt install -y ./google-chrome-stable_current_amd64.deb && rm -f ./google-chrome-stable_current_amd64.deb

# Switch to assemblyline user
USER assemblyline

# Copy DocPreview service code
WORKDIR /opt/al_service
COPY . .

ARG version=4.0.0.dev1
USER root
RUN sed -i -e "s/\$SERVICE_TAG/$version/g" service_manifest.yml
RUN unoconv --listener &

USER assemblyline
