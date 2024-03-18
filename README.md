# Document preview service
This repository is a self-developed Assemblyline service based on a [FAME's module](https://github.com/certsocietegenerale/fame_modules/tree/master/processing/document_preview).
It was created by [x1mus](https://github.com/x1mus) with support from [Sorakurai](https://github.com/Sorakurai) and [reynas](https://github.com/reynas) at [NVISO](https://github.com/NVISOsecurity).

This also contains modified source code from the following repositories:
- [XME's emlrender](https://github.com/xme/emlrender)
- [JoshData's convert-outlook-msg-file](https://github.com/JoshData/convert-outlook-msg-file)

## OCR Configuration
In this service, you're allowed to override the default OCR terms from the [service base](https://github.com/CybercentreCanada/assemblyline-v4-service/blob/master/assemblyline_v4_service/common/ocr.py) using `ocr` key in the `config` block of the service manifest.

### Simple Term Override (Legacy)
Let's say, I want to use a custom set of terms for `ransomware` detection. Then I can set the following:

```yaml
config:
    ocr:
        ransomware: ['bad1', 'bad2', ...]
```

This will cause the service to **only** use the terms I've specified when looking for `ransomware` terms. This is still subject to the hit threshold defined in the service base.

### Advanced Term Override
Let's say, I want to use a custom set of terms for `ransomware` detection and I want to set the hit threshold to `1` instead of `2` (default). Then I can set the following:

```yaml
config:
    ocr:
        ransomware:
            terms: ['bad1', 'bad2', ...]
            threshold: 1
```

This will cause the service to **only** use the terms I've specified when looking for `ransomware` terms and is subject to the hit threshold I've defined.

### Term Inclusion/Exclusion
Let's say, I want to add/remove a set of terms from the default set for `ransomware` detection. Then I can set the following:

```yaml
config:
    ocr:
        ransomware:
            include: ['bad1', 'bad2', ...]
            exclude: ['bank account']
```

This will cause the service to add the terms listed in `include` and remove the terms in `exclude` when looking for `ransomware` terms in OCR detection with the default set.
