# ClinOCR starter evaluation set

Source: [ClinOCR-Bench](https://github.com/ClinOCR-Bench/ClinOCR-Bench), release v1.0, MIT license (see LICENSE).

The authors created synthetic clinical documents, including handwriting fonts and physical scan defects. These are not real patient prescriptions. We downloaded existing images; we did not generate evaluation images. The source images are unchanged and checksummed in manifest.json.

Our ten selected cases cover normal, handwriting, poor-quality, rotated, and mixed artifacts, two per subset. Every case is an upstream eval example, not an exemplar. The selected documents are visit notes, referrals, and a pathology report. Medication mentions are historical/contextual; order-specific fields are expected to remain null.

labels.json contains agent annotations based on the upstream audited transcriptions. Patient names include explicit alternate header orderings. Independent human review of field legibility is pending. This set evaluates identity reading and non-prescription rejection; it cannot establish medication extraction accuracy or critical-ambiguity recall.

Raw downloads are ignored by Git. Recreate them with:

```sh
.venv/bin/python -m ocr.prepare_clinocr
```

The manifest pins image and archive hashes. Keep labels separate from prompts.

Positive-prescription candidate: [Bangladesh prescription image dataset](https://data.mendeley.com/datasets/k62rfd23kz/1), DOI 10.17632/k62rfd23kz.1. Its publisher describes 182 real de-identified images under CC BY 4.0; this differs from the NLM catalog count. Direct download returned HTTP 403 in this session. No files or full-field ground truth have been verified locally, and it is not part of these benchmark scores.
