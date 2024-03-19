ARG branch=latest
FROM cccs/assemblyline-v4-service-base:$branch

ENV SERVICE_PATH document_preview.document_preview.DocumentPreview

USER root

RUN apt-get update && apt-get install -y wget gnupg libreoffice

RUN mkdir -p /usr/share/man/man1mkdir -p /usr/share/man/man1
RUN apt-get install -y tesseract-ocr libemail-outlook-message-perl libgdiplus unzip
RUN apt-get install -y poppler-utils wkhtmltopdf
RUN pip install Pillow==9.5.0 natsort imgkit compoundfiles compressed_rtf pytesseract selenium unoserver

# Install Chrome for headless rendering of HTML documents
RUN wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb && \
    apt install -o DPkg::Options::="--force-confnew" -y ./google-chrome-stable_current_amd64.deb && rm -f ./google-chrome-stable_current_amd64.deb

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
