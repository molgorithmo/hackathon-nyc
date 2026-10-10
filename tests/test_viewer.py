import json
import unittest

from ocr.export_viewer import ocr_view, vision_view


class ViewerExportTests(unittest.TestCase):
    def test_raw_rejected_suggestions_do_not_become_accepted(self):
        raw = {'choices': [{'message': {'content': json.dumps({
            'documentType': 'clinical-other', 'fields': {'drug': {'value': 'example'}},
            'transcription': 'source text'})}}]}
        result = vision_view({'status': 'error', 'error': 'ValidationError'}, raw)
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['error'], 'ValidationError')
        self.assertEqual(result['fields']['drug']['value'], 'example')
        self.assertEqual(result['transcription'], 'source text')

    def test_validated_extraction_takes_priority_and_secrets_are_excluded(self):
        result = vision_view({'status': 'ok', 'secret': 'must not export',
                              'extraction': {'transcription': 'validated'}}, {})
        self.assertEqual(result['transcription'], 'validated')
        self.assertNotIn('secret', result)

    def test_missing_or_malformed_output_stays_unavailable(self):
        result = vision_view(None, {'choices': []})
        self.assertEqual(result['status'], 'unavailable')
        self.assertIsNone(result['fields'])
        self.assertIsNone(ocr_view(None))


if __name__ == '__main__':
    unittest.main()
