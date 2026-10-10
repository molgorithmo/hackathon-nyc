# RxHandBD handwriting dataset

Source: [author's Zenodo v1 record](https://zenodo.org/records/18478741), DOI 10.5281/zenodo.18478741. The record's API declares `mit-license`; its metadata is retained locally in `upstream/metadata.json`. This is a separate published version from [Mendeley v3](https://data.mendeley.com/datasets/dsb5r6vskg/3), which declares CC BY 4.0 and 512×512 images. Do not substitute versions silently.

These are existing cropped handwritten prescription words, not whole prescriptions or fax pages. Source labels support word recognition evaluation, not patient/drug/dose/directions extraction or automatic-release accuracy. Images are copied unchanged. No evaluation images are generated and no model labels replace upstream labels.

Imported: **5,578** images with nonblank upstream labels (**4,463 train / 1,115 test**). All test crops and 4,462 training crops are 128×128; one training crop is 170×90 and is preserved as supplied. There are zero exact SHA-256 image duplicates across splits. This does not prove writer or source-prescription independence. Per-image paths, labels, dimensions, split roles, and hashes are in `manifest.json`; paths resolve relative to this directory.

Preserve the upstream train/test split. Use test crops only for OCR evaluation; do not put test labels into model prompts or use them to select readings. The split has not been verified to separate writers or source prescriptions. Word recognition improvements do not establish dependable whole-order extraction.

Recreate the local dataset with:

```sh
.venv/bin/python -m ocr.prepare_rxhandbd
```

The importer verifies the publisher's archive checksum, records per-image SHA-256 hashes, and preserves the source CSV labels. Image files and upstream metadata/CSVs are ignored by Git. The ten-case ClinOCR baseline and its metrics remain separate. Preparation makes no model calls.

A frozen 100-crop test sample is recorded in `benchmark-sample-v1.json`. Results against upstream labels: GPT-4.1-mini 34% exact match / 42.4% CER, GPT-4.1 36% / 41.8%, Paddle English recognizer 19% / 45.7%. Failures and abstentions stay in the denominator. See [benchmark instructions](../../ocr/README.md) and `artifacts/words/rxwords-v1-paced/metrics.json`. The initial rate-limited run is preserved separately; the final comparison uses explicit paced recovery. These are word-recognition results, not complete-order or fax accuracy.

**Reference quality is unresolved:** an agent spot-check found apparent image/label mismatches in P0049 and P0164; see [review notes](label-review-notes.md). Scores measure upstream-label agreement and do not establish trusted OCR accuracy. No labels have been corrected; independent adjudication is pending.
