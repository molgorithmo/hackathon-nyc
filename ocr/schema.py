"""Extraction suggestions are never pharmacist confirmations."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, create_model, model_validator

FIELD_KEYS = (
    'patientName', 'dateOfBirth', 'drug', 'strength', 'dosageForm',
    'directions', 'quantity', 'refills', 'prescriber', 'writtenDate',
)
APPROVAL_REQUIRED_FIELDS = FIELD_KEYS


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Candidate(StrictModel):
    value: str = Field(min_length=1)
    sourceText: str = Field(min_length=1)

    @model_validator(mode='after')
    def nonempty_evidence(self):
        if not self.value.strip() or not self.sourceText.strip():
            raise ValueError('Candidates require nonempty values and source evidence')
        return self


class ExtractedField(StrictModel):
    value: str | None
    status: Literal['extracted', 'needs-review', 'missing']
    sourceText: str | None
    confidence: float | None = Field(ge=0, le=1)
    candidates: list[Candidate]
    reason: str = Field(min_length=1)

    @model_validator(mode='after')
    def consistent_evidence(self):
        if self.value is not None and (not self.value.strip() or not self.sourceText or not self.sourceText.strip()):
            raise ValueError('A value requires nonempty source evidence')
        if self.status == 'missing' and (self.value is not None or self.candidates):
            raise ValueError('Missing fields cannot contain values or candidates')
        if self.status == 'extracted' and (self.value is None or len(self.candidates) > 1):
            raise ValueError('Extracted fields need one unambiguous value')
        if len(self.candidates) > 1 and (self.value is not None or self.status != 'needs-review'):
            raise ValueError('Competing candidates require abstention and review')
        if self.value is not None and self.candidates and self.value != self.candidates[0].value:
            raise ValueError('Selected value contradicts the candidate; abstain and request review')
        return self


PrescriptionFields = create_model(
    'PrescriptionFields', __base__=StrictModel,
    **{key: (ExtractedField, ...) for key in FIELD_KEYS},
)


class Extraction(StrictModel):
    documentType: Literal['prescription', 'clinical-other', 'unknown']
    transcription: str
    fields: PrescriptionFields
    notes: list[str]

    @model_validator(mode='after')
    def reject_non_orders(self):
        if self.documentType != 'prescription':
            for key in FIELD_KEYS[2:]:
                field = getattr(self.fields, key)
                if field.value is not None or field.candidates or field.status != 'missing':
                    raise ValueError('Non-prescriptions cannot produce order fields')
        return self
