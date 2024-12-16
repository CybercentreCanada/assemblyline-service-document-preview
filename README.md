[![Discord](https://img.shields.io/badge/chat-on%20discord-7289da.svg?sanitize=true)](https://discord.gg/GUAy9wErNu)
[![](https://img.shields.io/discord/908084610158714900)](https://discord.gg/GUAy9wErNu)
[![Static Badge](https://img.shields.io/badge/github-assemblyline-blue?logo=github)](https://github.com/CybercentreCanada/assemblyline)
[![Static Badge](https://img.shields.io/badge/github-assemblyline\_service\_document\_preview-blue?logo=github)](https://github.com/CybercentreCanada/assemblyline-service-document-preview)
[![GitHub Issues or Pull Requests by label](https://img.shields.io/github/issues/CybercentreCanada/assemblyline/service-document-preview)](https://github.com/CybercentreCanada/assemblyline/issues?q=is:issue+is:open+label:service-document-preview)
[![License](https://img.shields.io/github/license/CybercentreCanada/assemblyline-service-document-preview)](./LICENSE)
# DocumentPreview Service

This Assemblyline service renders documents for preview and performs OCR analysis for malicious content.

## Service Details

### OCR
This uses OCR for it's analysis, you can find information about OCR configurations [here](https://cybercentrecanada.github.io/assemblyline4_docs/administration/service_management/#ocr-configuration).

## Accreditation / Contributions
This Assemblyline service is based on [FAME's module](https://github.com/certsocietegenerale/fame_modules/tree/master/processing/document_preview).
It was originally created by [x1mus](https://github.com/x1mus) with support from [Sorakurai](https://github.com/Sorakurai) and [reynas](https://github.com/reynas) at [NVISO](https://github.com/NVISOsecurity).

This also contains modified source code from the following repositories:
- [XME's emlrender](https://github.com/xme/emlrender)
- [JoshData's convert-outlook-msg-file](https://github.com/JoshData/convert-outlook-msg-file)

## Image variants and tags

Assemblyline services are built from the [Assemblyline service base image](https://hub.docker.com/r/cccs/assemblyline-v4-service-base),
which is based on Debian 11 with Python 3.11.

Assemblyline services use the following tag definitions:

| **Tag Type** | **Description**                                                                                  |      **Example Tag**       |
| :----------: | :----------------------------------------------------------------------------------------------- | :------------------------: |
|    latest    | The most recent build (can be unstable).                                                         |          `latest`          |
|  build_type  | The type of build used. `dev` is the latest unstable build. `stable` is the latest stable build. |     `stable` or `dev`      |
|    series    | Complete build details, including version and build type: `version.buildType`.                   | `4.5.stable`, `4.5.1.dev3` |

## Running this service

This is an Assemblyline service. It is designed to run as part of the Assemblyline framework.

If you would like to test this service locally, you can run the Docker image directly from the a shell:

    docker run \
        --name DocumentPreview \
        --env SERVICE_API_HOST=http://`ip addr show docker0 | grep "inet " | awk '{print $2}' | cut -f1 -d"/"`:5003 \
        --network=host \
        cccs/assemblyline-service-document-preview

To add this service to your Assemblyline deployment, follow this
[guide](https://cybercentrecanada.github.io/assemblyline4_docs/developer_manual/services/run_your_service/#add-the-container-to-your-deployment).

## Documentation

General Assemblyline documentation can be found at: https://cybercentrecanada.github.io/assemblyline4_docs/

# Service DocumentPreview

Ce service d'Assemblyline rend les documents pour prévisualisation et effectue une analyse OCR pour détecter les contenus malveillants.


## Détails du service

### OCR
Ce service utilise l'OCR pour son analyse, vous pouvez trouver des informations sur les configurations de l'OCR [ici] (https://cybercentrecanada.github.io/assemblyline4_docs/administration/service_management/#ocr-configuration).

## Accréditation / Contributions
Ce service Assemblyline est basé sur le module [FAME] (https://github.com/certsocietegenerale/fame_modules/tree/master/processing/document_preview).
Il a été créé à l'origine par [x1mus](https://github.com/x1mus) avec le soutien de [Sorakurai](https://github.com/Sorakurai) et [reynas](https://github.com/reynas) à [NVISO](https://github.com/NVISOsecurity).

Il contient également du code source modifié provenant des dépôts suivants :
- [emlrender de XME](https://github.com/xme/emlrender)
- [convert-outlook-msg-file de JoshData](https://github.com/JoshData/convert-outlook-msg-file)

## Variantes et étiquettes d'image

Les services d'Assemblyline sont construits à partir de l'image de base [Assemblyline service](https://hub.docker.com/r/cccs/assemblyline-v4-service-base),
qui est basée sur Debian 11 avec Python 3.11.

Les services d'Assemblyline utilisent les définitions d'étiquettes suivantes:

| **Type d'étiquette** | **Description**                                                                                                |  **Exemple d'étiquette**   |
| :------------------: | :------------------------------------------------------------------------------------------------------------- | :------------------------: |
|   dernière version   | La version la plus récente (peut être instable).                                                               |          `latest`          |
|      build_type      | Type de construction utilisé. `dev` est la dernière version instable. `stable` est la dernière version stable. |     `stable` ou `dev`      |
|        série         | Détails de construction complets, comprenant la version et le type de build: `version.buildType`.              | `4.5.stable`, `4.5.1.dev3` |

## Exécution de ce service

Il s'agit d'un service d'Assemblyline. Il est optimisé pour fonctionner dans le cadre d'un déploiement d'Assemblyline.

Si vous souhaitez tester ce service localement, vous pouvez exécuter l'image Docker directement à partir d'un terminal:

    docker run \
        --name DocumentPreview \
        --env SERVICE_API_HOST=http://`ip addr show docker0 | grep "inet " | awk '{print $2}' | cut -f1 -d"/"`:5003 \
        --network=host \
        cccs/assemblyline-service-document-preview

Pour ajouter ce service à votre déploiement d'Assemblyline, suivez ceci
[guide](https://cybercentrecanada.github.io/assemblyline4_docs/fr/developer_manual/services/run_your_service/#add-the-container-to-your-deployment).

## Documentation

La documentation générale sur Assemblyline peut être consultée à l'adresse suivante: https://cybercentrecanada.github.io/assemblyline4_docs/
