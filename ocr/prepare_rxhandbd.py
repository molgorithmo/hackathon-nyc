"""Import unchanged RxHandBD v1 word crops with upstream labels and split roles."""

import argparse
import csv
import hashlib
import io
import json
import re
import urllib.request
import zipfile
from collections import Counter
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'https://zenodo.org/records/18478741'
METADATA_URL = 'https://zenodo.org/api/records/18478741'
DOWNLOAD = METADATA_URL + '/files/RxHandBD.zip/content'
ARCHIVE_MD5 = 'c096859fcccb33655edaf34e4c1e7a06'
SPLITS = (('test', 'Test_Labels.csv', 'Test_Set'), ('train', 'Train_Label.csv', 'Train_Set'))


def read_cases(archive):
    """Validate all label references before writing any dataset files."""
    cases, seen = [], set()
    for split, labels, folder in SPLITS:
        reader = csv.DictReader(io.StringIO(archive.read(labels).decode('utf-8-sig')))
        if reader.fieldnames != ['Images', 'Text']:
            raise ValueError('Unexpected upstream label columns')
        for row in reader:
            name, text = row.get('Images'), row.get('Text')
            if (not isinstance(name, str) or not re.fullmatch(r'P\d{4}\.jpg', name)
                    or not isinstance(text, str) or not text.strip() or None in row):
                raise ValueError('Invalid image path or word label')
            if name in seen:
                raise ValueError('Duplicate image ID within or across splits')
            seen.add(name)
            member = f'{folder}/{name}'
            data = archive.read(member)
            with Image.open(io.BytesIO(data)) as image:
                if image.format != 'JPEG':
                    raise ValueError('Expected original JPEG crop')
                width, height = image.size
                image.verify()
            case = dict(id=Path(name).stem, split=split, upstream_image=member,
                        image=f'images/{split}/{name}', text=text,
                        sha256=hashlib.sha256(data).hexdigest(), width=width, height=height)
            cases.append((case, data))
    listed = {case['upstream_image'] for case, _ in cases}
    if listed != {name for name in archive.namelist() if name.endswith('.jpg')}:
        raise ValueError('Images and upstream label references differ')
    return cases


def prepare(archive_path, destination=ROOT / 'data/rxhandbd', metadata_path=None):
    with archive_path.open('rb') as handle:
        if hashlib.file_digest(handle, 'md5').hexdigest() != ARCHIVE_MD5:
            raise ValueError('RxHandBD archive does not match the pinned publisher checksum')
    with archive_path.open('rb') as handle:
        archive_sha256 = hashlib.file_digest(handle, 'sha256').hexdigest()
    with zipfile.ZipFile(archive_path) as archive:
        cases = read_cases(archive)
        counts = dict(Counter(case['split'] for case, _ in cases))
        if counts != {'test': 1115, 'train': 4463}:
            raise ValueError('Unexpected upstream split counts')
        upstream = destination / 'upstream'
        upstream.mkdir(parents=True, exist_ok=True)
        for case, data in cases:
            target = destination / case['image']
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        for _, labels, _ in SPLITS:
            (upstream / labels).write_bytes(archive.read(labels))
    if metadata_path is not None:
        (upstream / 'metadata.json').write_bytes(metadata_path.read_bytes())
    split_hashes = {split: {c['sha256'] for c, _ in cases if c['split'] == split}
                    for split, _, _ in SPLITS}
    manifest = dict(
        source=SOURCE, doi='10.5281/zenodo.18478741', version=1,
        download=DOWNLOAD, license='MIT', license_source=METADATA_URL,
        archive_md5=ARCHIVE_MD5, archive_sha256=archive_sha256,
        task='handwritten-word-recognition', images_generated_locally=False,
        counts=counts, positive_complete_prescription_orders=0,
        cross_split_exact_duplicate_hashes=len(split_hashes['train'] & split_hashes['test']),
        limitation='Word crops only; not prescription orders or fax pages. Upstream text labels '
                   'are unreviewed locally. Writer/source-prescription independence is unknown.',
        cases=[case for case, _ in cases],
    )
    (destination / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    print(f'Prepared {len(cases)} unchanged word crops: {counts}; no model calls')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, default=Path('/tmp/RxHandBD-zenodo-v1.zip'))
    parser.add_argument('--metadata', type=Path, default=Path('/tmp/RxHandBD-zenodo-v1-metadata.json'))
    args = parser.parse_args()
    if not args.archive.exists():
        urllib.request.urlretrieve(DOWNLOAD, args.archive)
    if not args.metadata.exists():
        urllib.request.urlretrieve(METADATA_URL, args.metadata)
    prepare(args.archive, metadata_path=args.metadata)
