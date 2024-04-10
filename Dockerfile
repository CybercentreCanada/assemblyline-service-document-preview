ARG branch=latest
FROM cccs/assemblyline-v4-service-base:$branch

ENV SERVICE_PATH document_preview.document_preview.DocumentPreview

USER root

RUN apt-get update && apt-get install -y wget libreoffice unzip && apt-get install --no-install-recommends -y calibre

RUN mkdir -p /usr/share/man/man1mkdir -p /usr/share/man/man1
RUN apt-get install -y tesseract-ocr libemail-outlook-message-perl libgdiplus unzip
RUN apt-get install -y poppler-utils wkhtmltopdf
RUN pip install Pillow==9.5.0 natsort imgkit compoundfiles compressed_rtf pytesseract selenium unoconv multidecoder

WORKDIR /tmp

# Find out what is the latest version of the chrome-for-testing/chromedriver available
RUN VERS=$(wget -q -O - https://googlechromelabs.github.io/chrome-for-testing/LATEST_RELEASE_STABLE) && \
    # Download + Install google-chrome with the version matching the latest chromedriver
    wget -O ./google-chrome-stable_amd64.deb https://dl.google.com/linux/chrome/deb/pool/main/g/google-chrome-stable/google-chrome-stable_$VERS-1_amd64.deb && \
    apt install -y ./google-chrome-stable_amd64.deb && \
    # Download + unzip the latest chromedriver
    wget -O ./chromedriver-linux64.zip https://storage.googleapis.com/chrome-for-testing-public/$VERS/linux64/chromedriver-linux64.zip && \
    unzip ./chromedriver-linux64.zip chromedriver-linux64/chromedriver && \
    rm -f ./google-chrome-stable_current_amd64.deb ./chromedriver-linux64.zip && \
    mv ./chromedriver-linux64/chromedriver /usr/bin/chromedriver && \
    # Cleanup
    rm -rf /tmp/*

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
