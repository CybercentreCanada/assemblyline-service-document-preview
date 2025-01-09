ARG branch=latest
FROM cccs/assemblyline-v4-service-base:$branch

# Python path to the service class from your service directory
ENV SERVICE_PATH document_preview.document_preview.DocumentPreview
ENV DOCBUILDER_VERSION 8.2.0

# Install apt dependencies
USER root

COPY pkglist.txt /tmp/setup/
RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
    $(grep -vE "^\s*(#|$)" /tmp/setup/pkglist.txt | tr "\n" " ") && \
    rm -f /tmp/setup/pkglist.txt

WORKDIR /tmp

# Install OnlyOffice's DocBuilder to convert documents to PDF
RUN wget -O ./onlyoffice-documentbuilder.deb https://github.com/ONLYOFFICE/DocumentBuilder/releases/download/v${DOCBUILDER_VERSION}/onlyoffice-documentbuilder_amd64.deb && \
    apt install -y ./onlyoffice-documentbuilder.deb && \
    rm -f ./onlyoffice-documentbuilder.deb

# Add onlyoffice to PYTHONPATH
ENV PYTHONPATH $PYTHONPATH:/opt/onlyoffice

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

RUN rm -rf /var/lib/apt/lists/*

# Install python dependencies
USER assemblyline
COPY requirements.txt requirements.txt
RUN pip install \
    --no-cache-dir \
    --user \
    --requirement requirements.txt && \
    rm -rf ~/.cache/pip

# Copy service code
WORKDIR /opt/al_service
COPY . .

# Patch version in manifest
ARG version=1.0.0.dev1
USER root
RUN sed -i -e "s/\$SERVICE_TAG/$version/g" service_manifest.yml
# Add uno package to PYTHONPATH
ENV PYTHONPATH $PYTHONPATH:/usr/lib/python3/dist-packages/

# From @kam193's OOPreview service - fixes the issue where DocBuilder fails at conversion unless first used by root
# Ref: https://github.com/kam193/assemblyline-services/blob/main/oo-preview/service/finish_installation.py
RUN python -c "from documentbuilder.docbuilder import CDocBuilder; builder = CDocBuilder()"

# Switch to assemblyline user
USER assemblyline
