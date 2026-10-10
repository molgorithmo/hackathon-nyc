import json
import unittest
from pathlib import Path

from pydantic import ValidationError

from ocr.release import (
    RELEASE_POLICY_VERSION, ReleaseDecision, ReleaseSignals, evaluate_release,
    normalize_field,
)
from ocr.schema import APPROVAL_REQUIRED_FIELDS, Candidate, Extraction

FIXTURE = Path(__file__).parent / 'fixtures/release_prescription.json'


def prescription():
    return Extraction.model_validate_json(FIXTURE.read_text())


def checked_signals(**changes):
    return ReleaseSignals(**{
        'primary_complete': True, 'verifier_complete': True,
        'primary_order_count': 1, 'verifier_order_count': 1,
        'independent_verification': True, 'ocr_checked': True,
        'image_quality_passed': True, 'document_supported': True,
        'in_distribution': True, **changes,
    })


def codes(decision):
    return {r.code for r in decision.document_reasons} | {
        r.code for reasons in decision.field_reasons.values() for r in reasons}


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.primary = prescription()
        self.verifier = prescription()

    def gate(self, **signal_changes):
        decision = evaluate_release(self.primary, self.verifier,
                                    signals=checked_signals(**signal_changes))
        if decision.status != 'auto-released':
            self.assertTrue(codes(decision))
            self.assertIsNone(decision.accepted_order)
            self.assertTrue(all(r.detail.strip() for r in decision.document_reasons))
            self.assertTrue(all(r.detail.strip() for rs in decision.field_reasons.values() for r in rs))
        return decision

    def test_complete_matching_readings_release_all_fields_with_policy_version(self):
        decision = self.gate()
        self.assertEqual(decision.status, 'auto-released')
        self.assertEqual(decision.policy_version, RELEASE_POLICY_VERSION)
        self.assertEqual(set(decision.accepted_order.model_dump()), set(APPROVAL_REQUIRED_FIELDS))
        self.assertEqual(decision.accepted_order.refills, '0')
        self.assertFalse(codes(decision))
        self.assertEqual(ReleaseDecision.model_validate_json(decision.model_dump_json()), decision)

    def test_drug_strength_directions_and_identity_conflicts_enter_exception(self):
        for key, value in (('drug', 'Othermed'), ('strength', '75 mg'),
                           ('directions', 'Take 2 tablets daily'), ('patientName', 'Other Person')):
            with self.subTest(field=key):
                self.verifier = prescription()
                getattr(self.verifier.fields, key).value = value
                getattr(self.verifier.fields, key).sourceText = value
                decision = self.gate()
                self.assertEqual(decision.status, 'exception')
                self.assertIn('PRIMARY_VERIFIER_CONFLICT', {r.code for r in decision.field_reasons[key]})

    def test_every_required_field_is_checked_in_both_readings(self):
        for source in ('primary', 'verifier'):
            for key in APPROVAL_REQUIRED_FIELDS:
                with self.subTest(source=source, field=key):
                    self.primary, self.verifier = prescription(), prescription()
                    field = getattr(getattr(self, source).fields, key)
                    field.value, field.sourceText, field.status = None, None, 'missing'
                    decision = self.gate()
                    self.assertEqual(decision.status, 'exception')
                    self.assertIn('MISSING_REQUIRED_FIELD', {r.code for r in decision.field_reasons[key]})

    def test_multiple_candidates_abstain_and_enter_exception(self):
        field = self.primary.fields.strength
        field.value, field.status = None, 'needs-review'
        field.candidates = [Candidate(value=v, sourceText='?5 mg') for v in ('25 mg', '75 mg')]
        Extraction.model_validate_json(self.primary.model_dump_json())
        decision = self.gate()
        self.assertEqual(decision.status, 'exception')
        self.assertIn('AMBIGUOUS_FIELD', codes(decision))
        self.assertIsNone(self.primary.fields.strength.value)

    def test_even_one_candidate_or_review_status_blocks_release(self):
        self.primary.fields.strength.candidates = [Candidate(value='25 mg', sourceText='25 mg')]
        self.assertIn('AMBIGUOUS_FIELD', codes(self.gate()))
        self.primary.fields.strength.candidates = []
        self.primary.fields.strength.status = 'needs-review'
        self.assertEqual(self.gate().status, 'exception')

    def test_missing_evidence_or_blank_value_never_releases_mutated_models(self):
        # Extraction normally rejects these; the gate also checks mutable model inputs.
        for source in ('primary', 'verifier'):
            for change in ({'sourceText': None}, {'sourceText': '   '}, {'value': '  '}):
                with self.subTest(source=source, change=change):
                    self.primary, self.verifier = prescription(), prescription()
                    field = getattr(self, source).fields.drug
                    for key, value in change.items():
                        setattr(field, key, value)
                    decision = self.gate()
                    self.assertEqual(decision.status, 'exception')
                    expected = 'MISSING_EVIDENCE' if 'sourceText' in change else 'MISSING_REQUIRED_FIELD'
                    self.assertIn(expected, codes(decision))

    def test_ocr_contradiction_is_field_specific_and_does_not_select_a_value(self):
        decision = self.gate(ocr_contradictions={'strength': 'OCR reads a different strength; inspect the source.'})
        self.assertEqual(decision.status, 'exception')
        self.assertEqual(decision.field_reasons['strength'][0].code, 'OCR_CONTRADICTION')
        self.assertEqual(self.primary.fields.strength.value, '25 mg')

    def test_quality_distribution_and_support_checks_enter_exception(self):
        for flag, code in (('image_quality_passed', 'LOW_IMAGE_QUALITY'),
                           ('in_distribution', 'OUT_OF_DISTRIBUTION'),
                           ('document_supported', 'UNSUPPORTED_DOCUMENT')):
            with self.subTest(flag=flag):
                decision = self.gate(**{flag: False})
                self.assertEqual(decision.status, 'exception')
                self.assertIn(code, codes(decision))

    def test_unassessed_checks_and_incomplete_responses_fail_closed(self):
        for flag in ('primary_complete', 'verifier_complete', 'primary_order_count',
                     'verifier_order_count', 'ocr_checked', 'image_quality_passed',
                     'document_supported', 'in_distribution'):
            with self.subTest(flag=flag):
                decision = self.gate(**{flag: None})
                self.assertEqual(decision.status, 'exception')
                self.assertIn('INCOMPLETE_RESPONSE', codes(decision))
        for flag in ('primary_complete', 'verifier_complete', 'ocr_checked'):
            self.assertIn('INCOMPLETE_RESPONSE', codes(self.gate(**{flag: False})))
        for source in ('primary', 'verifier'):
            self.primary, self.verifier = prescription(), prescription()
            setattr(self, source, None)
            self.assertIn('INCOMPLETE_RESPONSE', codes(self.gate()))
        self.assertEqual(evaluate_release(None, None, signals=ReleaseSignals()).status, 'exception')

    def test_independence_requires_explicit_attestation_and_distinct_objects(self):
        for independent in (False, None):
            self.assertIn('VERIFICATION_NOT_INDEPENDENT', codes(self.gate(independent_verification=independent)))
        self.verifier = self.primary
        self.assertEqual(self.gate().status, 'exception')

    def test_non_prescription_rejected_without_order_fields(self):
        payload = json.loads(FIXTURE.read_text())
        payload['documentType'] = 'clinical-other'
        for field in payload['fields'].values():
            field.update(value=None, sourceText=None, status='missing')
        self.primary, self.verifier = Extraction.model_validate(payload), Extraction.model_validate(payload)
        decision = self.gate(primary_order_count=0, verifier_order_count=0)
        self.assertEqual(decision.status, 'rejected')
        self.assertIn('NOT_A_PRESCRIPTION', codes(decision))
        self.assertIsNone(decision.accepted_order)

    def test_unknown_document_enters_exception_even_with_single_order_signals(self):
        payload = json.loads(FIXTURE.read_text())
        payload['documentType'] = 'unknown'
        for field in payload['fields'].values():
            field.update(value=None, sourceText=None, status='missing')
        self.primary = Extraction.model_validate(payload)
        decision = self.gate()
        self.assertEqual(decision.status, 'exception')
        self.assertIn('OUT_OF_DISTRIBUTION', codes(decision))
        self.assertIn('PRIMARY_VERIFIER_CONFLICT', {r.code for r in decision.document_reasons})

    def test_blank_transcription_cannot_claim_complete_output(self):
        self.verifier.transcription = '  '
        decision = self.gate()
        self.assertEqual(decision.status, 'exception')
        self.assertIn('INCOMPLETE_RESPONSE', codes(decision))

    def test_multiple_orders_rejected_in_either_reading(self):
        for source in ('primary', 'verifier'):
            with self.subTest(source=source):
                decision = self.gate(**{source + '_order_count': 2})
                self.assertEqual(decision.status, 'rejected')
                self.assertIn('UNSUPPORTED_MULTI_ORDER', codes(decision))
                self.assertIn('PRIMARY_VERIFIER_CONFLICT', {r.code for r in decision.document_reasons})

    def test_normalization_is_conservative_and_output_preserves_primary(self):
        self.primary.fields.patientName.value = '  Test   Person  '
        self.verifier.fields.patientName.value = 'TEST PERSON'
        decision = self.gate()
        self.assertEqual(decision.status, 'auto-released')
        self.assertEqual(decision.accepted_order.patientName, '  Test   Person  ')
        for key, left, right in (
            ('strength', '25 mg', '75 mg'), ('strength', '25 mg', '0.025 g'),
            ('strength', '1 mL', '1 ML'), ('directions', '1.0 tablet', '10 tablets'),
            ('directions', 'once daily', 'QD'), ('dateOfBirth', '01/02/1990', '1990-01-02'),
            ('drug', 'Example-med', 'Examplemed'), ('quantity', '1 0', '10'),
        ):
            with self.subTest(field=key, left=left, right=right):
                self.assertNotEqual(normalize_field(key, left), normalize_field(key, right))

    def test_confidence_never_approves_or_blocks(self):
        for value in (None, 0.0, 1.0):
            for key in APPROVAL_REQUIRED_FIELDS:
                getattr(self.primary.fields, key).confidence = value
                getattr(self.verifier.fields, key).confidence = value
            self.assertEqual(self.gate().status, 'auto-released')
        self.verifier.fields.strength.value = '75 mg'
        self.assertEqual(self.gate().status, 'exception')

    def test_inputs_unchanged_and_accepted_order_is_detached(self):
        for contradiction in ({}, {'drug': 'Resolve the OCR discrepancy.'}):
            signals = checked_signals(ocr_contradictions=contradiction)
            before = [r.model_dump_json() for r in (self.primary, self.verifier, signals)]
            decision = evaluate_release(self.primary, self.verifier, signals=signals)
            if decision.accepted_order:
                decision.accepted_order.drug = 'Output-only edit'
            self.assertEqual(before, [r.model_dump_json() for r in (self.primary, self.verifier, signals)])

    def test_reason_and_signal_contracts_reject_invalid_shapes(self):
        for changes in ({'primary_order_count': True}, {'primary_complete': 'true'},
                        {'verifier_order_count': -1}, {'ocr_contradictions': {'invented': 'Conflict'}},
                        {'ocr_contradictions': {'drug': '  '}}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                checked_signals(**changes)
        with self.assertRaises(ValidationError):
            ReleaseDecision(status='exception', document_reasons=[], field_reasons={}, accepted_order=None)


if __name__ == '__main__':
    unittest.main()
