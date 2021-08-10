FROM cccs/assemblyline-v4-service-base:stable

ENV SERVICE_PATH document_preview.DocumentPreview

USER root

RUN mkdir -p /usr/share/man/man1mkdir -p /usr/share/man/man1
RUN apt update
RUN apt install -y poppler-utils libreoffice --no-install-recommends
RUN pip3 install pdf2image Pillow natsort

USER assemblyline

WORKDIR /opt/al_service
COPY . .

ARG version=4.0.0.dev1
USER root
RUN sed -i -e "s/\$SERVICE_TAG/$version/g" service_manifest.yml

USER assemblyline
