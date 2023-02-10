ARG branch=latest
FROM cccs/assemblyline-v4-service-base:$branch

ENV SERVICE_PATH document_preview.document_preview.DocumentPreview

USER root

RUN mkdir -p /usr/share/man/man1mkdir -p /usr/share/man/man1
RUN apt-get update && apt-get install -y wget tesseract-ocr libemail-outlook-message-perl libgdiplus unzip
RUN wget https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6-1/wkhtmltox_0.12.6-1.buster_amd64.deb
RUN apt-get install -y poppler-utils ./wkhtmltox_0.12.6-1.buster_amd64.deb --no-install-recommends
RUN pip install pdf2image Pillow natsort imgkit compoundfiles compressed_rtf pytesseract

# Install Aspose Suite for handling documents
RUN pip install aspose-cells-python aspose-words==22.10 aspose.Slides

# Install Wine to run OneNoteAnalyzer (C# app using Aspose)
RUN dpkg --add-architecture i386 && mkdir -pm755 /etc/apt/keyrings && \
    wget -O /etc/apt/keyrings/winehq-archive.key https://dl.winehq.org/wine-builds/winehq.key
RUN wget -NP /etc/apt/sources.list.d/ https://dl.winehq.org/wine-builds/debian/dists/buster/winehq-buster.sources && \
    apt update && apt install -y --install-recommends winehq-stable

RUN wget https://github.com/knight0x07/OneNoteAnalyzer/releases/download/OneNoteAnalyzer/OneNoteAnalyzer.zip && \
    unzip OneNoteAnalyzer.zip -d /opt/al_service/OneNoteAnalyzer && rm -f OneNoteAnalyzer.zip
RUN wget -O /opt/al_service/dotNetFx40_Full_x86_x64.exe 'http://download.microsoft.com/download/9/5/A/95A9616B-7A37-4AF6-BC36-D6EA96C8DAAE/dotNetFx40_Full_x86_x64.exe'

USER assemblyline

WORKDIR /opt/al_service
# Install dotnet under the AL user in Wine
RUN wine dotNetFx40_Full_x86_x64.exe /q

COPY . .

ARG version=4.0.0.dev1
USER root
RUN rm -f dotNetFx40_Full_x86_x64.exe
RUN sed -i -e "s/\$SERVICE_TAG/$version/g" service_manifest.yml

USER assemblyline
