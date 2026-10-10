import {
  FIELD_KEYS,
  type ExtractedField,
  type FieldKey,
  type WorkflowEnvelope,
} from '../domain/types';

export type DemoCase = {
  id: 'clear' | 'ambiguous' | 'non-prescription';
  label: string;
  summary: string;
  envelope: WorkflowEnvelope;
};

export type ExceptionResolution = {
  dateOfBirth: string;
  strength: string;
  refills: string;
  technician: string;
};

export type FieldCorrection = {
  key: FieldKey;
  value: string;
  technician: string;
};

const field = (
  key: FieldKey,
  value: string | null,
  sourceText: string | null,
  reason: string,
  confidence: number | null,
  candidates?: ExtractedField['candidates'],
): ExtractedField => ({
  key,
  value,
  confidence,
  sourceText,
  status: candidates?.length ? 'needs-review' : value ? 'extracted' : 'missing',
  reason,
  candidates,
});

const clearFields: Record<FieldKey, ExtractedField> = {
  patientName: field('patientName', 'Maria L. Hernandez', 'Maria L. Hernandez', 'Primary and verifier readings agree.', 0.99),
  dateOfBirth: field('dateOfBirth', '04/12/1978', '04/12/1978', 'Primary and verifier readings agree.', 0.98),
  drug: field('drug', 'Lisinopril', 'Lisinopril 10 mg tablet', 'Primary and verifier readings agree.', 0.99),
  strength: field('strength', '10 mg', 'Lisinopril 10 mg tablet', 'Primary and verifier readings agree.', 0.98),
  dosageForm: field('dosageForm', 'Tablet', 'Lisinopril 10 mg tablet', 'Primary and verifier readings agree.', 0.96),
  directions: field('directions', 'Take 1 tablet by mouth once daily', 'Take 1 tablet by mouth once daily', 'Primary and verifier readings agree.', 0.96),
  quantity: field('quantity', '30 tablets', '30 tablets', 'Primary and verifier readings agree.', 0.93),
  refills: field('refills', '3', '3', 'Primary and verifier readings agree.', 0.91),
  prescriber: field('prescriber', 'Alan R. Whitfield, MD', 'Alan R. Whitfield, MD', 'The prescriber line is faint and should be reviewed.', 0.78),
  writtenDate: field('writtenDate', '03/14/2024', '03/14/2024', 'Primary and verifier readings agree.', 0.95),
};

const clearOrder = Object.fromEntries(
  FIELD_KEYS.map((key) => [key, clearFields[key].value as string]),
) as Record<FieldKey, string>;

const ambiguousFields: Partial<Record<FieldKey, ExtractedField>> = {
  patientName: field('patientName', 'James O. Carter', 'James O. Carter', 'The name is readable.', 0.97),
  dateOfBirth: field('dateOfBirth', null, '11/0?/1961', 'One digit is unreadable.', null),
  drug: field('drug', 'Venlafaxine ER', 'Venlafaxine ER', 'The drug name is readable.', 0.95),
  strength: field('strength', null, 'smudged strength', 'The source supports two readings.', null, [
    { id: 'strength-25', value: '25 mg', confidence: 0.53, rationale: 'The leading mark may be a 2.' },
    { id: 'strength-75', value: '75 mg', confidence: 0.44, rationale: 'The leading mark may be a 7.' },
  ]),
  dosageForm: field('dosageForm', 'Capsule', 'capsule', 'The dosage form is readable.', 0.93),
  directions: field('directions', 'Take 1 capsule by mouth every morning', 'Take 1 capsule by mouth every morning', 'The directions are readable.', 0.91),
  quantity: field('quantity', '30', '30', 'The quantity is readable.', 0.89),
  refills: field('refills', null, null, 'The refill line is blank.', null),
  prescriber: field('prescriber', 'Priya Nakamura, DO', 'Priya Nakamura, DO', 'The printed prescriber name is readable.', 0.95),
  writtenDate: field('writtenDate', '02/28/2024', '02/28/2024', 'The written date is readable.', 0.94),
};

const now = '2026-10-10T18:00:00Z';

export const DEMO_CASES: DemoCase[] = [
  {
    id: 'clear',
    label: 'Clear prescription',
    summary: 'Ready for straight-through release',
    envelope: {
      extractionId: 'fixture-clear-v1',
      inputHash: 'illustrative-clear-rx-v1',
      jobState: 'complete',
      revision: 1,
      source: { fileName: 'clear-rx.png', mimeType: 'image/png', url: '/demo/clear-rx.png', pageCount: 1 },
      categorization: {
        label: 'prescription',
        confidence: 'high',
        basis: 'illustrative',
        detail: 'Evaluation routing band; not calibrated model confidence.',
      },
      decision: {
        status: 'auto-released',
        policyVersion: 'ftf-release-v1',
        documentReasons: [],
        fieldReasons: {},
        acceptedOrder: clearOrder,
      },
      release: {
        actor: { type: 'policy', id: 'ftf-release-v1' },
        policyVersion: 'ftf-release-v1',
        provenance: 'automatic',
        revision: 1,
        releasedAt: now,
      },
      fields: clearFields,
      audit: [
        { id: 'clear-received', type: 'received', actor: 'system', occurredAt: now, detail: 'Evaluation case received.' },
        { id: 'clear-release', type: 'release', actor: 'policy:ftf-release-v1', occurredAt: now, detail: 'Release checks passed; accepted order created.' },
      ],
      fixtureEvidence: 'illustrative',
    },
  },
  {
    id: 'ambiguous',
    label: 'Ambiguous prescription',
    summary: 'Strength and demographics require review',
    envelope: {
      extractionId: 'fixture-ambiguous-v1',
      inputHash: 'illustrative-ambiguous-rx-v1',
      jobState: 'complete',
      revision: 1,
      source: { fileName: 'ambiguous-rx.png', mimeType: 'image/png', url: '/demo/ambiguous-rx.png', pageCount: 1 },
      categorization: {
        label: 'prescription',
        confidence: 'low',
        basis: 'illustrative',
        detail: 'Evaluation routing band; unresolved evidence requires technician review.',
      },
      decision: {
        status: 'exception',
        policyVersion: 'ftf-release-v1',
        documentReasons: [],
        fieldReasons: {
          dateOfBirth: [{ code: 'MISSING_REQUIRED_FIELD', source: 'primary', detail: 'One date-of-birth digit is unreadable.' }],
          strength: [{ code: 'AMBIGUOUS_FIELD', source: 'comparison', detail: 'The source supports both 25 mg and 75 mg.' }],
          refills: [{ code: 'MISSING_REQUIRED_FIELD', source: 'primary', detail: 'The refill line is blank.' }],
        },
        acceptedOrder: null,
      },
      release: null,
      fields: ambiguousFields,
      audit: [
        { id: 'ambiguous-received', type: 'received', actor: 'system', occurredAt: now, detail: 'Evaluation case received.' },
        { id: 'ambiguous-decision', type: 'decision', actor: 'policy:ftf-release-v1', occurredAt: now, detail: 'Routed to exception; no accepted order created.' },
      ],
      fixtureEvidence: 'illustrative',
    },
  },
  {
    id: 'non-prescription',
    label: 'Non-prescription',
    summary: 'Rejected clinical document',
    envelope: {
      extractionId: 'template_4_sample_3_handwriting',
      inputHash: '656c762e74e76533665361aa598f082bf7722688f414c0da20cad0af70cf0d54',
      jobState: 'complete',
      revision: 1,
      source: {
        fileName: 'template_4_sample_3_handwriting.jpg',
        mimeType: 'image/jpeg',
        url: '/run/template_4_sample_3_handwriting.jpg',
        pageCount: 1,
      },
      categorization: {
        label: 'non-prescription',
        confidence: 'high',
        basis: 'saved-result',
        detail: 'Saved rejection result; this band is not calibrated probability.',
      },
      decision: {
        status: 'rejected',
        policyVersion: 'ftf-release-v1',
        documentReasons: [{ code: 'NOT_A_PRESCRIPTION', source: 'primary', detail: 'This clinical document is not a prescription order.' }],
        fieldReasons: {},
        acceptedOrder: null,
      },
      release: null,
      fields: {},
      audit: [
        { id: 'non-rx-received', type: 'received', actor: 'system', occurredAt: now, detail: 'Saved public ClinOCR case loaded.' },
        { id: 'non-rx-rejected', type: 'rejection', actor: 'policy:ftf-release-v1', occurredAt: now, detail: 'Rejected as non-prescription; no accepted order created.' },
      ],
      fixtureEvidence: 'measured',
    },
  },
];

const assertFixture = ({ id, envelope }: DemoCase) => {
  if (envelope.jobState !== 'complete' || !envelope.decision)
    throw new Error(`Fixture ${id} must contain a completed decision`);
  const released = envelope.decision.status === 'auto-released';
  if (released !== Boolean(envelope.decision.acceptedOrder && envelope.release))
    throw new Error(`Fixture ${id} has an incoherent release result`);
  if (!released && (envelope.decision.acceptedOrder || envelope.release))
    throw new Error(`Fixture ${id} cannot expose a released order`);
  Object.values(envelope.fields).forEach((extractedField) => {
    if (!extractedField) return;
    if (extractedField.confidence !== null && (extractedField.confidence < 0 || extractedField.confidence > 1))
      throw new Error(`Fixture ${id} has invalid confidence for ${extractedField.key}`);
    extractedField.candidates?.forEach((candidate) => {
      if (candidate.confidence === null || candidate.confidence < 0 || candidate.confidence > 1)
        throw new Error(`Fixture ${id} has invalid confidence for candidate ${candidate.id}`);
    });
  });
};

DEMO_CASES.forEach(assertFixture);

export const resolveAmbiguousFixture = ({
  dateOfBirth,
  strength,
  refills,
  technician,
}: ExceptionResolution): WorkflowEnvelope => {
  if (![dateOfBirth, strength, refills, technician].every((value) => value.trim()))
    throw new Error('Every correction and the technician name are required');
  const original = DEMO_CASES.find((item) => item.id === 'ambiguous')!.envelope;
  const correctedAt = new Date().toISOString();
  const correctedFields = {
    ...original.fields,
    dateOfBirth: field('dateOfBirth', dateOfBirth.trim(), 'Technician clarification', 'Technician supplied a clarified value.', null),
    strength: field('strength', strength.trim(), 'Technician clarification', 'Technician selected or entered the clarified strength.', null),
    refills: field('refills', refills.trim(), 'Technician clarification', 'Technician supplied a clarified value.', null),
  };
  const acceptedOrder = Object.fromEntries(FIELD_KEYS.map((key) => {
    const value = correctedFields[key]?.value;
    if (!value) throw new Error(`Resolved fixture is missing ${key}`);
    return [key, value];
  })) as Record<FieldKey, string>;
  const resolved: WorkflowEnvelope = {
    ...original,
    revision: 2,
    fields: correctedFields,
    decision: {
      status: 'auto-released',
      policyVersion: 'ftf-release-v1',
      documentReasons: [],
      fieldReasons: {},
      acceptedOrder,
    },
    release: {
      actor: { type: 'policy', id: 'ftf-release-v1' },
      policyVersion: 'ftf-release-v1',
      provenance: 'exception-correction',
      revision: 2,
      releasedAt: correctedAt,
    },
    audit: [
      ...original.audit,
      { id: `correction-${correctedAt}`, type: 'correction', actor: technician.trim(), occurredAt: correctedAt, detail: `Clarified DOB, strength (${strength.trim()}), and refills.` },
      { id: `release-${correctedAt}`, type: 'release', actor: 'policy:ftf-release-v1', occurredAt: correctedAt, detail: 'Backend revalidation passed after technician correction.' },
    ],
  };
  assertFixture({ id: 'ambiguous', label: 'Ambiguous prescription', summary: 'Resolved exception', envelope: resolved });
  if (!resolved.audit.some((event) => event.type === 'correction'))
    throw new Error('Resolved fixture must preserve a technician correction event');
  return resolved;
};

export const correctReleasedFieldFixture = (
  original: WorkflowEnvelope,
  { key, value, technician }: FieldCorrection,
): WorkflowEnvelope => {
  if (!value.trim() || !technician.trim())
    throw new Error('The corrected value and technician name are required');
  if (original.decision?.status !== 'auto-released' || !original.decision.acceptedOrder || !original.release)
    throw new Error('Only a released order can use the field correction flow');
  const correctedAt = new Date().toISOString();
  const revision = original.revision + 1;
  const corrected: WorkflowEnvelope = {
    ...original,
    revision,
    fields: {
      ...original.fields,
      [key]: field(key, value.trim(), 'Technician clarification', 'Technician reviewed and corrected this value.', null),
    },
    decision: {
      ...original.decision,
      acceptedOrder: { ...original.decision.acceptedOrder, [key]: value.trim() },
    },
    release: {
      ...original.release,
      provenance: 'exception-correction',
      revision,
      releasedAt: correctedAt,
    },
    audit: [
      ...original.audit,
      { id: `correction-${key}-${correctedAt}`, type: 'correction', actor: technician.trim(), occurredAt: correctedAt, detail: `Corrected ${key} to ${value.trim()}.` },
      { id: `release-${correctedAt}`, type: 'release', actor: 'policy:ftf-release-v1', occurredAt: correctedAt, detail: 'Backend revalidation passed after technician correction.' },
    ],
  };
  assertFixture({ id: 'clear', label: 'Corrected released prescription', summary: 'Field corrected', envelope: corrected });
  return corrected;
};
