/**
 * Core domain model for Fax to Fill.
 *
 * These types are the contract between the extraction layer (today: mock data,
 * tomorrow: the Nicrron API) and the review UI. Keep them transport-agnostic.
 */

/** Canonical ordered list of the fields a draft order must account for. */
export const FIELD_KEYS = [
  'patientName',
  'dateOfBirth',
  'drug',
  'strength',
  'dosageForm',
  'directions',
  'quantity',
  'refills',
  'prescriber',
  'writtenDate',
] as const;

export type FieldKey = (typeof FIELD_KEYS)[number];

/** Human-readable labels, kept next to the keys so they never drift apart. */
export const FIELD_LABELS: Record<FieldKey, string> = {
  patientName: 'Patient name',
  dateOfBirth: 'Date of birth',
  drug: 'Drug',
  strength: 'Strength',
  dosageForm: 'Dosage form',
  directions: 'Directions (Sig)',
  quantity: 'Quantity',
  refills: 'Refills',
  prescriber: 'Prescriber',
  writtenDate: 'Written date',
};

/**
 * Clinically critical fields. A wrong value here can harm a patient, so the UI
 * highlights them and blocks approval until each one is resolved.
 *
 * "dose" is captured by `directions` (the Sig carries the dose per administration).
 */
export const CRITICAL_FIELDS: readonly FieldKey[] = [
  'drug',
  'strength',
  'directions',
] as const;

export function isCriticalField(key: FieldKey): boolean {
  return CRITICAL_FIELDS.includes(key);
}

/** Every field must be present before the backend may release an order. */
export const APPROVAL_REQUIRED_FIELDS: readonly FieldKey[] = FIELD_KEYS;

export type FieldStatus = 'extracted' | 'needs-review' | 'missing';

export const STATUS_LABELS: Record<FieldStatus, string> = {
  extracted: 'Ready',
  'needs-review': 'Needs Review',
  missing: 'Missing',
};

/**
 * Sentinel rendered whenever the extractor is not confident enough to assert a
 * value. We never guess: an empty/uncertain field shows this string instead.
 */
export const UNABLE_TO_DETERMINE = 'Unable to determine';

/** One possible reading of an ambiguous field (e.g. 25 mg vs 75 mg). */
export interface FieldCandidate {
  /** Stable id so selections survive re-renders. */
  id: string;
  value: string;
  /** Calibrated extraction confidence in 0..1; null means no score was provided. */
  confidence: number | null;
  /** Why the extractor considered this reading plausible. */
  rationale?: string;
}

/** A single extracted field as returned by the extraction service. */
export interface ExtractedField {
  key: FieldKey;
  /**
   * Best value the extractor can assert, or `null` when it cannot determine one.
   * `null` must never be replaced by a guess downstream.
   */
  value: string | null;
  /** Calibrated confidence when available; null for human input or uncalibrated live readings. */
  confidence: number | null;
  /** Exact supporting text; null when the source cannot be read. */
  sourceText: string | null;
  status: FieldStatus;
  /** Short explanation shown to the pharmacist (why this status/confidence). */
  reason: string;
  /** Present when multiple readings are plausible; forces an explicit choice. */
  candidates?: FieldCandidate[];
  /** Optional source location on the document, for future bounding-box overlays. */
  boundingBox?: BoundingBox;
}

/** Normalised (0..1) box relative to the page, so it scales with any viewer size. */
export interface BoundingBox {
  page: number;
  x: number;
  y: number;
  width: number;
  height: number;
}

/** The uploaded (or demo) document being reviewed. */
export interface SourceDocument {
  fileName: string;
  mimeType: string;
  /** Object URL or data URI for display. */
  url: string;
  pageCount: number;
}

/** Full result of an extraction run. */
export interface ExtractionResult {
  extractionId: string;
  /** Which engine produced this (mock today, Nicrron API later). */
  engine: string;
  engineVersion: string;
  receivedAt: string;
  document: SourceDocument;
  fields: Record<FieldKey, ExtractedField>;
  documentType?: 'prescription' | 'clinical-other' | 'unknown';
  /** Document-level notes, e.g. "fax is low resolution". */
  notes?: string[];
}

export type JobState = 'processing' | 'complete' | 'failed';
export type ReleaseStatus = 'auto-released' | 'exception' | 'rejected';
export type ReleaseProvenance = 'automatic' | 'exception-correction';
export type CategorizationConfidence = 'high' | 'medium' | 'low';
export type ReasonCode =
  | 'NOT_A_PRESCRIPTION'
  | 'UNSUPPORTED_MULTI_ORDER'
  | 'MISSING_REQUIRED_FIELD'
  | 'AMBIGUOUS_FIELD'
  | 'PRIMARY_VERIFIER_CONFLICT'
  | 'MISSING_EVIDENCE'
  | 'OCR_CONTRADICTION'
  | 'LOW_IMAGE_QUALITY'
  | 'OUT_OF_DISTRIBUTION'
  | 'INCOMPLETE_RESPONSE'
  | 'VERIFICATION_NOT_INDEPENDENT'
  | 'UNSUPPORTED_DOCUMENT';

export interface ReleaseReason {
  code: ReasonCode;
  source: 'primary' | 'verifier' | 'comparison' | 'ocr' | 'input';
  detail: string;
}

export interface AuditEvent {
  id: string;
  type: 'received' | 'decision' | 'correction' | 'release' | 'rejection';
  actor: string;
  occurredAt: string;
  detail: string;
}

export interface WorkflowEnvelope {
  extractionId: string;
  inputHash: string;
  jobState: JobState;
  revision: number;
  source: SourceDocument;
  categorization: {
    label: 'prescription' | 'non-prescription' | 'unknown';
    confidence: CategorizationConfidence | null;
    basis: 'illustrative' | 'saved-result' | 'live-pipeline';
    detail: string;
  };
  decision: null | {
    status: ReleaseStatus;
    policyVersion: string;
    documentReasons: ReleaseReason[];
    fieldReasons: Partial<Record<FieldKey, ReleaseReason[]>>;
    acceptedOrder: Record<FieldKey, string> | null;
  };
  release: null | {
    actor: { type: 'policy'; id: string };
    policyVersion: string;
    provenance: ReleaseProvenance;
    revision: number;
    releasedAt: string;
  };
  fields: Partial<Record<FieldKey, ExtractedField>>;
  audit: AuditEvent[];
  fixtureEvidence: 'illustrative' | 'measured' | 'live';
}
