import json
import re
import unittest

import cv2
import numpy as np
from pydantic import ValidationError

from ocr.benchmark import ROOT, load_cases
from ocr.council import (
    COUNCIL_MODELS, REVIEW_ALLOWED_FILES, REVIEW_QUESTION, aggregate_rankings, parse_ranking,
    project_context, synthesis_prompt,
)
from ocr.evaluate import normalized, text_metrics
from ocr.preprocess import enhance, source_polygon
from ocr.schema import Extraction, ExtractedField, FIELD_KEYS


def missing():
    return dict(value=None, status='missing', sourceText=None,
                confidence=None, candidates=[], reason='Absent from source')


class SchemaTests(unittest.TestCase):
    def test_blank_evidence_and_contradictory_candidate_are_rejected(self):
        field = dict(value='25 mg', status='extracted', sourceText='25 mg',
                     confidence=None, candidates=[], reason='Read from source')
        for change in (
            dict(sourceText='   '),
            dict(candidates=[dict(value='75 mg', sourceText='75 mg')]),
            dict(candidates=[dict(value='25 mg', sourceText='   ')]),
            dict(value=None, status='needs-review',
                 candidates=[dict(value='   ', sourceText='?5 mg')]),
        ):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                ExtractedField.model_validate({**field, **change})
        field['candidates'] = [dict(value='25 mg', sourceText='25 mg')]
        self.assertEqual(ExtractedField.model_validate(field).value, '25 mg')

    def test_multiple_candidates_cannot_be_silently_resolved(self):
        field = dict(value='25 mg', status='extracted', sourceText='?5 mg',
                     confidence=.9, reason='Unclear first digit', candidates=[
                         dict(value='25 mg', sourceText='?5 mg'),
                         dict(value='75 mg', sourceText='?5 mg')])
        with self.assertRaises(ValidationError):
            ExtractedField.model_validate(field)
        field.update(value=None, status='needs-review')
        self.assertIsNone(ExtractedField.model_validate(field).value)

    def test_missing_does_not_become_zero_and_confirmation_is_for_humans(self):
        field = missing()
        for change in (dict(value='0'), dict(status='confirmed'), dict(confidence=1.1)):
            with self.assertRaises(ValidationError):
                ExtractedField.model_validate({**field, **change})

    def test_medication_history_does_not_create_a_prescription(self):
        doc = dict(documentType='clinical-other', transcription='Medication history',
                   fields={key: missing() for key in FIELD_KEYS}, notes=[])
        Extraction.model_validate(doc)
        doc['fields']['drug'] = dict(value='Example', status='extracted', sourceText='Example',
                                     confidence=None, candidates=[], reason='Historical mention')
        with self.assertRaises(ValidationError):
            Extraction.model_validate(doc)

    def test_python_and_typescript_field_names_agree(self):
        source = (ROOT / 'src/domain/types.ts').read_text()
        block = source.split('export const FIELD_KEYS = [', 1)[1].split('] as const', 1)[0]
        self.assertEqual(tuple(re.findall(r"'([^']+)'", block)), FIELD_KEYS)


class PreprocessingTests(unittest.TestCase):
    def test_blank_page_preserves_coordinates_and_size(self):
        page = np.full((100, 160, 3), 255, dtype=np.uint8)
        enhanced, metadata = enhance(page)
        json.dumps(metadata)
        self.assertEqual(enhanced.shape, (100, 160))
        polygon = [[3., 4.], [15., 4.], [15., 20.], [3., 20.]]
        np.testing.assert_allclose(source_polygon(polygon, metadata), polygon, atol=1e-6)

    def test_deskew_inverse_maps_source_evidence(self):
        page = np.full((300, 400, 3), 255, dtype=np.uint8)
        for y in range(50, 250, 30):
            cv2.line(page, (30, y), (350, y + 30), (0, 0, 0), 2)
        _, metadata = enhance(page)
        points = np.array([[[30., 50.], [350., 80.], [350., 180.], [30., 150.]]])
        forward = cv2.transform(points, np.asarray(metadata['source_to_processed']))[0]
        np.testing.assert_allclose(source_polygon(forward, metadata), points[0], atol=1e-6)

    def test_invalid_image_is_rejected(self):
        with self.assertRaises(ValueError):
            enhance(None)


class EvaluationTests(unittest.TestCase):
    def test_missing_results_stay_in_denominator(self):
        case = dict(id='test', subset='normal', transcription='data/clinocr/transcriptions/template_8_sample_2_normal.txt')
        result = text_metrics([case], {}, lambda c, r: '')
        self.assertEqual(result['character_error_rate'], 1)

    def test_digit_errors_survive_normalization(self):
        self.assertNotEqual(normalized('25 mg'), normalized('75 mg'))

    def test_manifest_labels_and_unchanged_images_agree(self):
        cases = load_cases()
        labels = json.loads((ROOT / 'data/clinocr/labels.json').read_text())
        self.assertEqual(len(cases), 10)
        self.assertEqual(set(labels['cases']), {c['id'] for c in cases})
        self.assertTrue(all(c['split'] == 'eval' for c in cases))


class CouncilTests(unittest.TestCase):
    def test_council_has_five_distinct_models(self):
        self.assertEqual(len(COUNCIL_MODELS), 5)
        self.assertEqual(len(set(COUNCIL_MODELS)), 5)

    def test_context_is_explicitly_allowlisted(self):
        context = project_context()
        self.assertIn('FILE: context/context.md', context)
        self.assertIn('FILE: context/frontend-approach.md', context)
        self.assertIn('FILE: artifacts/baseline/metrics.json', context)
        self.assertNotIn('FILE: .env\n', context)
        review = project_context(REVIEW_ALLOWED_FILES)
        self.assertIn('FILE: src/services/liveExtractionService.ts', review)
        self.assertIn('FILE: tests/test_api.py', review)
        self.assertNotIn('FILE: context/todo-context.md', review)

    def test_anonymous_rankings_are_parsed_and_aggregated(self):
        text = 'Review\nFINAL RANKING:\n1. Response B\n2. Response A\n'
        self.assertEqual(parse_ranking(text), ['Response B', 'Response A'])
        rankings = [dict(parsed_ranking=['Response B', 'Response A']),
                    dict(parsed_ranking=['Response A', 'Response B'])]
        result = aggregate_rankings(rankings, {'Response A': 'one', 'Response B': 'two'})
        self.assertEqual(result, [
            {'model': 'two', 'average_rank': 1.5, 'rankings_count': 2},
            {'model': 'one', 'average_rank': 1.5, 'rankings_count': 2},
        ])

    def test_current_review_requests_an_audit_and_includes_live_verification(self):
        prompt = synthesis_prompt('context', REVIEW_QUESTION, 'proposals', 'reviews', [],
                                  '67 tests, build, and lint pass')
        self.assertIn('final current-state audit', prompt)
        self.assertIn('67 tests, build, and lint pass', prompt)
        self.assertNotIn('Choose one runtime approach', prompt)


if __name__ == '__main__':
    unittest.main()
