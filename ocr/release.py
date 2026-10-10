"""Deterministic order-entry release policy; no clinical or dispensing authorization.

This first policy consumes explicit checks, not calibrated probabilities. The caller
must obtain blind readings of the same input and attest to the supplied signals.
"""

from typing import Literal

from pydantic import Field, create_model, model_validator

from .schema import APPROVAL_REQUIRED_FIELDS, FIELD_KEYS, Extraction, StrictModel

RELEASE_POLICY_VERSION = 'ftf-release-v1'
FieldKey = Literal[*FIELD_KEYS]
ReasonCode = Literal[
    'NOT_A_PRESCRIPTION', 'UNSUPPORTED_MULTI_ORDER', 'MISSING_REQUIRED_FIELD',
    'AMBIGUOUS_FIELD', 'PRIMARY_VERIFIER_CONFLICT', 'MISSING_EVIDENCE',
    'OCR_CONTRADICTION', 'LOW_IMAGE_QUALITY', 'OUT_OF_DISTRIBUTION',
    'INCOMPLETE_RESPONSE', 'VERIFICATION_NOT_INDEPENDENT', 'UNSUPPORTED_DOCUMENT',
]


class ReleaseSignals(StrictModel):
    # None means unassessed, never a passing check. Counts belong to each reading.
    primary_complete: bool | None = None
    verifier_complete: bool | None = None
    primary_order_count: int | None = Field(default=None, ge=0)
    verifier_order_count: int | None = Field(default=None, ge=0)
    independent_verification: bool | None = None
    ocr_checked: bool | None = None
    ocr_contradictions: dict[FieldKey, str] = Field(default_factory=dict)
    image_quality_passed: bool | None = None
    document_supported: bool | None = None
    in_distribution: bool | None = None

    @model_validator(mode='after')
    def actionable_contradictions(self):
        if any(not detail.strip() for detail in self.ocr_contradictions.values()):
            raise ValueError('OCR contradictions require a nonblank explanation')
        return self


class ReleaseReason(StrictModel):
    code: ReasonCode
    source: Literal['primary', 'verifier', 'comparison', 'ocr', 'input']
    detail: str = Field(min_length=1)


AcceptedOrder = create_model(
    'AcceptedOrder', __base__=StrictModel,
    **{key: (str, Field(min_length=1)) for key in APPROVAL_REQUIRED_FIELDS},
)


class ReleaseDecision(StrictModel):
    status: Literal['auto-released', 'exception', 'rejected']
    policy_version: Literal['ftf-release-v1'] = RELEASE_POLICY_VERSION
    document_reasons: list[ReleaseReason]
    field_reasons: dict[FieldKey, list[ReleaseReason]]
    accepted_order: AcceptedOrder | None

    @model_validator(mode='after')
    def coherent_decision(self):
        has_reasons = bool(self.document_reasons or self.field_reasons)
        if self.status == 'auto-released':
            if self.accepted_order is None or has_reasons:
                raise ValueError('Release requires an order and no failing checks')
        elif self.accepted_order is not None or not has_reasons:
            raise ValueError('Non-release requires actionable reasons and no order')
        if any(not reasons for reasons in self.field_reasons.values()):
            raise ValueError('Field reasons cannot be empty')
        return self


def normalize_field(key: FieldKey, value: str) -> str:
    """Compare typography only; never convert units, expand Sig, or reinterpret dates."""
    text = ' '.join(value.split())
    if key in ('patientName', 'drug', 'dosageForm', 'prescriber'):
        return text.lower()
    return text


def _nonblank(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def evaluate_release(
    primary: Extraction | None,
    verifier: Extraction | None,
    *,
    signals: ReleaseSignals,
) -> ReleaseDecision:
    """Release only a complete, supported single order with no failed checks.

    Inputs are validated Extraction models (None for a failed/malformed response).
    Independence, counts, OCR assessment, and quality/support are explicit caller
    attestations; this function cannot prove how model calls were performed.
    """
    document_reasons = []
    field_reasons = {}

    def reason(code, source, detail, key=None):
        item = ReleaseReason(code=code, source=source, detail=detail)
        if key is None:
            document_reasons.append(item)
        else:
            field_reasons.setdefault(key, []).append(item)

    for source, reading, complete, count in (
        ('primary', primary, signals.primary_complete, signals.primary_order_count),
        ('verifier', verifier, signals.verifier_complete, signals.verifier_order_count),
    ):
        if reading is None or complete is not True:
            reason('INCOMPLETE_RESPONSE', source, 'Obtain a complete validated response before retrying release.')
        if count is None:
            reason('INCOMPLETE_RESPONSE', source, 'Establish the number of prescription orders in this reading.')
        elif count > 1:
            reason('UNSUPPORTED_MULTI_ORDER', source, 'Use a supported single-order document; do not select one order.')
        elif count == 0:
            reason('NOT_A_PRESCRIPTION', source, 'No prescription order was identified; obtain a prescription document.')
        if reading is None:
            continue
        if not _nonblank(reading.transcription):
            reason('INCOMPLETE_RESPONSE', source, 'Obtain a nonblank source transcription before retrying release.')
        if reading.documentType == 'clinical-other':
            reason('NOT_A_PRESCRIPTION', source, 'Clinical notes/history cannot be released as a prescription order.')
        elif reading.documentType != 'prescription':
            reason('OUT_OF_DISTRIBUTION', source, 'Establish a supported prescription document type before retrying.')

    if primary is not None and verifier is not None and primary.documentType != verifier.documentType:
        reason('PRIMARY_VERIFIER_CONFLICT', 'comparison', 'Resolve the document-type disagreement against the source.')
    if (signals.primary_order_count is not None and signals.verifier_order_count is not None
            and signals.primary_order_count != signals.verifier_order_count):
        reason('PRIMARY_VERIFIER_CONFLICT', 'comparison', 'Resolve the order-count disagreement; never silently select an order.')
    if signals.independent_verification is not True or (primary is not None and primary is verifier):
        reason('VERIFICATION_NOT_INDEPENDENT', 'comparison', 'Obtain a blind verifier reading of the same input, without the primary answer.')
    for key, passed, code, instruction, source in (
        ('ocr_checked', signals.ocr_checked, 'INCOMPLETE_RESPONSE', 'Complete the OCR contradiction assessment.', 'ocr'),
        ('image_quality_passed', signals.image_quality_passed, 'LOW_IMAGE_QUALITY', 'Obtain a readable image that passes the input-quality checks.', 'input'),
        ('document_supported', signals.document_supported, 'UNSUPPORTED_DOCUMENT', 'Route to a supported document workflow or obtain a supported input.', 'input'),
        ('in_distribution', signals.in_distribution, 'OUT_OF_DISTRIBUTION', 'Escalate an input outside the supported operating range.', 'input'),
    ):
        if passed is None:
            reason('INCOMPLETE_RESPONSE', source, f'Assess {key} before retrying release.')
        elif not passed:
            reason(code, source, instruction)

    for key in APPROVAL_REQUIRED_FIELDS:
        fields = []
        for source, reading in (('primary', primary), ('verifier', verifier)):
            field = getattr(reading.fields, key, None) if reading is not None else None
            fields.append(field)
            if field is None:
                reason('MISSING_REQUIRED_FIELD', source, 'Read the required field from the source; do not infer it.', key)
                continue
            if not _nonblank(field.value) or field.status == 'missing':
                reason('MISSING_REQUIRED_FIELD', source, 'Establish one nonblank value for this required field from the source.', key)
            if field.status == 'needs-review' or field.candidates:
                reason('AMBIGUOUS_FIELD', source, 'Resolve the uncertain reading against source evidence; do not select a candidate automatically.', key)
            if field.status not in ('extracted', 'needs-review', 'missing'):
                reason('INCOMPLETE_RESPONSE', source, 'Obtain a valid extraction status for this field.', key)
            if not _nonblank(field.sourceText):
                reason('MISSING_EVIDENCE', source, 'Obtain nonblank source evidence for this field.', key)
        left, right = fields
        if (left is not None and right is not None and _nonblank(left.value)
                and _nonblank(right.value) and normalize_field(key, left.value) != normalize_field(key, right.value)):
            reason('PRIMARY_VERIFIER_CONFLICT', 'comparison', 'Reconcile the two readings against the source or obtain clarification.', key)
        if key in signals.ocr_contradictions:
            reason('OCR_CONTRADICTION', 'ocr', signals.ocr_contradictions[key], key)

    rejected = any(item.code in ('NOT_A_PRESCRIPTION', 'UNSUPPORTED_MULTI_ORDER')
                   for item in document_reasons)
    status = 'rejected' if rejected else 'exception' if document_reasons or field_reasons else 'auto-released'
    order = None
    if status == 'auto-released':
        # Agreement never changes the primary values or fills them using other sources.
        order = AcceptedOrder(**{key: getattr(primary.fields, key).value for key in APPROVAL_REQUIRED_FIELDS})
    return ReleaseDecision(status=status, document_reasons=document_reasons,
                           field_reasons=field_reasons, accepted_order=order)
