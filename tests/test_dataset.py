import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from ocr.prepare_rxhandbd import ROOT, prepare, read_cases


class DatasetImportTests(unittest.TestCase):
    def archive(self, *, test_name='P0001.jpg', train_name='P1116.jpg', text='25 mg'):
        # Packaging fixture uses an existing image; no evaluation images are generated.
        image = (ROOT / 'data/clinocr/images/template_8_sample_2_normal.jpg').read_bytes()
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('Test_Labels.csv', f'Images,Text\n{test_name},{text}\n')
            archive.writestr('Train_Label.csv', f'Images,Text\n{train_name},75 mg\n')
            archive.writestr(f'Test_Set/{test_name}', image)
            archive.writestr(f'Train_Set/{train_name}', image)
        buffer.seek(0)
        return zipfile.ZipFile(buffer)

    def test_upstream_labels_splits_and_image_bytes_are_preserved(self):
        with self.archive() as archive:
            cases = read_cases(archive)
            self.assertEqual([case['split'] for case, _ in cases], ['test', 'train'])
            self.assertEqual([case['text'] for case, _ in cases], ['25 mg', '75 mg'])
            self.assertEqual(cases[0][1], archive.read('Test_Set/P0001.jpg'))
            self.assertNotIn('fields', cases[0][0])

    def test_unsafe_paths_blank_labels_and_cross_split_ids_are_rejected(self):
        for options in (dict(test_name='../P0001.jpg'), dict(text=' '), dict(train_name='P0001.jpg')):
            with self.subTest(options=options), self.archive(**options) as archive:
                with self.assertRaises(ValueError):
                    read_cases(archive)

    def test_wrong_publisher_checksum_fails_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'wrong.zip'
            path.write_bytes(b'wrong archive')
            destination = root / 'dataset'
            with self.assertRaises(ValueError):
                prepare(path, destination)
            self.assertFalse(destination.exists())


if __name__ == '__main__':
    unittest.main()
