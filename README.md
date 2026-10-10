# PillSpark · Fax to Fill

Prescription order workflow demo and OCR benchmark viewer, built with React, TypeScript, Vite, and a Python extraction pipeline.

**Live demo:** https://molgorithmo.github.io/hackathon-nyc/

The GitHub Pages demo includes illustrative prescription workflows and saved OCR benchmark results. It does not run the Python API or accept live uploads. This is an experimental demo, not a clinically validated dispensing system. Benchmark scores measure agreement with upstream references; word-label quality remains unresolved.

## Run locally

```sh
npm ci
npm run dev
```

For live extraction, follow [Python setup](ocr/README.md), configure the local `.env`, and run `.venv/bin/python -m ocr.api` in a separate terminal. API keys stay on the server. Never commit `.env`, private receipts, or real patient documents.

## Check and build

```sh
npm run lint
npm run test:ui
npm run build
```

## Publish

Push to `main` to deploy via `.github/workflows/pages.yml`. The workflow builds for the repository subpath and publishes only `dist/`. `public/run/` contains the reviewed public benchmark snapshot and selected images; raw model receipts, local jobs, and source datasets remain ignored.

The included benchmark images originate from [ClinOCR-Bench](https://github.com/ClinOCR-Bench/ClinOCR-Bench) (synthetic documents, MIT; [license](data/clinocr/LICENSE)) and [RxHandBD Zenodo v1](https://zenodo.org/records/18478741) (word crops, record declares MIT). See [ClinOCR notes](data/clinocr/README.md) and [RxHandBD notes](data/rxhandbd/README.md) for provenance and limitations.
