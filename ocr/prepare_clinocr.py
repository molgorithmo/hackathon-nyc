"""Select existing benchmark files; never generate evaluation images."""

import argparse
import csv
import hashlib
import json
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE = 'https://github.com/ClinOCR-Bench/ClinOCR-Bench/releases/download/v1.0/ClinOCR-Bench-v1.0.zip'
# Two cases per artifact; avoid the sample-1 exemplars in the first four subsets.
SELECTION = (
    ('normal', 4, 2), ('normal', 8, 2),
    ('handwriting', 4, 3), ('handwriting', 8, 3),
    ('poor', 4, 4), ('poor', 8, 4),
    ('rotated', 4, 5), ('rotated', 8, 5),
    ('mixed', 7, 4), ('mixed', 8, 7),
)


def prepare(archive: Path):
    dest = ROOT / 'data/clinocr'
    for folder in ('images', 'transcriptions', 'upstream'):
        (dest / folder).mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        lookup_name = next(n for n in z.namelist() if n.endswith('oneshot_lookup.csv'))
        roles = {(r['subset'], int(r['template']), int(r['sample'])): r['role']
                 for r in csv.DictReader(z.read(lookup_name).decode().splitlines())}
        cases = []
        for subset, template, sample in SELECTION:
            if roles[subset, template, sample] != 'eval':
                raise ValueError('Evaluation selection includes an upstream exemplar')
            case_id = f'template_{template}_sample_{sample}_{subset}'
            image = z.read(f'ClinOCR-Bench/scans/{subset}/{case_id}.jpg')
            text = z.read(f'ClinOCR-Bench/ground_truth/{subset}/{case_id}.txt')
            (dest / 'images' / f'{case_id}.jpg').write_bytes(image)
            (dest / 'transcriptions' / f'{case_id}.txt').write_bytes(text)
            cases.append(dict(
                id=case_id, subset=subset, template=template,
                image=f'data/clinocr/images/{case_id}.jpg',
                transcription=f'data/clinocr/transcriptions/{case_id}.txt',
                sha256=hashlib.sha256(image).hexdigest(),
                documentType='clinical-other',
                split='eval',
            ))
        # Preserve upstream split roles rather than assuming every sample is test.
        (dest / 'upstream/oneshot_lookup.csv').write_bytes(z.read(lookup_name))
    with archive.open('rb') as handle:
        archive_digest = hashlib.file_digest(handle, 'sha256').hexdigest()
    (dest / 'manifest.json').write_text(json.dumps(dict(
        source=RELEASE, archive_sha256=archive_digest,
        license='MIT', synthetic=True, cases=cases,
        limitation='Clinical notes/referrals only; zero positive prescription orders. This is a smoke test, not a prescription accuracy benchmark.',
    ), indent=2) + '\n')
    print(f'Prepared {len(cases)} unchanged ClinOCR images and transcriptions')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, default=Path('/tmp/ClinOCR-Bench-v1.0.zip'))
    args = parser.parse_args()
    if not args.archive.exists():
        urllib.request.urlretrieve(RELEASE, args.archive)
    prepare(args.archive)
