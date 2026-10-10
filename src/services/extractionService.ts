import type { ExtractionResult } from '../domain/types';

/**
 * Request handed to an extraction engine.
 *
 * `file` is absent for built-in demo cases (we already know the document), and
 * present for real uploads.
 */
export interface ExtractionRequest {
  /** The uploaded document. Omitted when replaying a built-in demo case. */
  file?: File;
  /** Identifier of a built-in demo case, when not uploading. */
  demoCaseId?: string;
  /** Optional hint for the engine, e.g. 'fax' | 'escript-scan'. */
  documentHint?: string;
}

/**
 * The seam between the UI and whatever performs extraction.
 *
 * Today this is backed by `MockExtractionService`. To go live, implement this
 * interface against the Nicrron API (see `nicrronExtractionService.ts`) and
 * swap the instance exported from `src/services/index.ts` — no UI changes needed.
 */
export interface ExtractionService {
  /** Human-readable name, surfaced in the UI footer for traceability. */
  readonly name: string;

  /**
   * Extract structured prescription fields from a document.
   *
   * Implementations must never fabricate values: when a field cannot be read
   * with confidence, return `value: null` with status `missing`, or supply
   * `candidates` with status `needs-review`.
   */
  extract(request: ExtractionRequest): Promise<ExtractionResult>;
}

/** Thrown when an engine cannot process the document at all. */
export class ExtractionError extends Error {
  readonly cause?: unknown;

  constructor(
    message: string,
    cause?: unknown,
  ) {
    super(message);
    this.name = 'ExtractionError';
    this.cause = cause;
  }
}
