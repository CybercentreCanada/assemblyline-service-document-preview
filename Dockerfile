ARG branch=latest
FROM cccs/assemblyline-v4-service-base:$branch

ENV SERVICE_PATH document_preview.document_preview.DocumentPreview
ENV LIBRE_VERSION=7.6
ENV LIBRE_BUILD_VERSION=${LIBRE_VERSION}.3

USER root

RUN apt-get update && apt-get install -y wget gnupg libreoffice

# Edit sources for Tesseract 5.0.x
RUN echo "deb https://notesalexp.org/tesseract-ocr5/buster/ buster main" \
    | tee /etc/apt/sources.list.d/notesalexp.list > /dev/null
RUN wget -O - https://notesalexp.org/debian/alexp_key.asc | apt-key add -
RUN apt-get update

RUN mkdir -p /usr/share/man/man1mkdir -p /usr/share/man/man1
RUN apt-get install -y tesseract-ocr libemail-outlook-message-perl libgdiplus unzip
RUN wget https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6-1/wkhtmltox_0.12.6-1.buster_amd64.deb
RUN apt-get install -y poppler-utils ./wkhtmltox_0.12.6-1.buster_amd64.deb --no-install-recommends &&\
    rm -f ./wkhtmltox_0.12.6-1.buster_amd64.deb
RUN pip install Pillow==9.5.0 natsort imgkit compoundfiles compressed_rtf pytesseract unoserver

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
# Add uno package to PYTHONPATH
ENV PYTHONPATH $PYTHONPATH:/usr/lib/python3/dist-packages/

USER assemblyline
