/**
 * Response shapes from the FastAPI backend.
 *
 * Hand-written to mirror `backend/app/schemas/workspace.py`. Generating these
 * from the OpenAPI spec is the right long-term answer; until that script exists,
 * this file is the contract and any drift shows up as a type error at the first
 * property access rather than as `undefined` at runtime.
 */

/** Drives the provenance badge — the core visual distinction in this product. */
export type FieldSource = "ubl_xml" | "vlm" | "ocr_rule" | "human";

export type ValidationState = "blocking" | "review_suggested" | "auto_validated";

export type Severity = "info" | "warning" | "error";

export interface BBox {
  /** 1-based page number. */
  page: number;
  /** Normalized 0.0–1.0, never pixels — drops straight into an SVG viewBox="0 0 1 1". */
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

export interface ExtractedField {
  field_key: string;
  row_index: number | null;
  value_extracted: string | null;
  value_final: string | null;
  /**
   * Arrives as a JSON string: the backend serializes Decimal as text so no
   * precision is lost in transit. Parse before doing arithmetic with it.
   */
  confidence: number | string | null;
  source: FieldSource | null;
  validation_state: ValidationState | string | null;
  bbox: BBox | null;
}

/** One requested field, as the queue's extraction schema defines it. */
export interface SchemaField {
  key: string;
  label_en: string;
  label_ar: string;
  type: string;
  required: boolean;
  /** True for a cell of the repeating line-item group. */
  line_item?: boolean;
}

export interface ValidationFinding {
  /** The validation_results row's own id. Two findings can share a rule_code
   * (the same rule failing on two different fields) — key lists on this, not
   * on rule_code alone. */
  id: string;
  rule_code: string;
  severity: Severity;
  passed: boolean;
  message_ar: string | null;
  message_en: string | null;
  field_key: string | null;
}

export interface PageInfo {
  page_number: number;
  text_source: string | null;
  /** 'text' | 'vision' | null — null means Step Zero answered and no model
   * (so no per-page routing decision) ever ran for this page. */
  extraction_path: "text" | "vision" | null;
  width_px: number | null;
  height_px: number | null;
  /** Short-lived signed URL. Expires in five minutes — do not cache it. */
  image_url: string | null;
}

export interface AnnotationDetail {
  annotation_id: string;
  document_id: string;
  status: string;
  model_version: string | null;
  automated: boolean;
  created_at: string;
  confirmed_at: string | null;
  has_embedded_ubl: boolean;
  page_count: number | null;
  blockers: string[];
  /** Labels (ar/en), types and order, read from the extraction schema. */
  schema_fields?: SchemaField[];
  fields: ExtractedField[];
  findings: ValidationFinding[];
  pages: PageInfo[];
}

/** One reviewer edit. The workspace PATCHes a batch of these, never a snapshot. */
export interface CorrectionEvent {
  field_key: string;
  row_index?: number | null;
  new_value: string | null;
  action?: "edit" | "delete" | "add" | "rebox";
}

export interface CorrectionResult {
  annotation_id: string;
  applied: number;
  blockers: string[];
  fields: ExtractedField[];
  findings: ValidationFinding[];
}

// --------------------------------------------------------------------------- //
// Dashboard — mirrors backend/app/schemas/dashboard.py
// --------------------------------------------------------------------------- //

/**
 * A document's state: 'processing' and 'stalled' exist only here (there is no
 * annotation yet); the rest is the latest annotation's status.
 */
export type DocState =
  | "processing"
  | "stalled"
  | "to_review"
  | "reviewing"
  | "confirmed"
  | "approved"
  | "exporting"
  | "exported"
  | "rejected"
  | "failed"
  | (string & {});

export interface DocumentListItem {
  document_id: string;
  /** Null until the pipeline finishes or fails — there is nothing to open yet. */
  annotation_id: string | null;
  filename: string | null;
  created_at: string;
  state: DocState;
  has_embedded_ubl: boolean;
  /** Null when Step Zero answered and no model was called. */
  model_version: string | null;
  page_count: number | null;
  invoice_number: string | null;
  seller_name: string | null;
  /** Exactly as extracted or corrected. A string: money is never a float. */
  total_amount: string | null;
  currency: string | null;
  blocking_count: number;
  error_en: string | null;
  error_ar: string | null;
}

export interface AccuracyStats {
  annotations: number;
  fields_total: number;
  fields_corrected: number;
}

export interface Stats {
  documents_total: number;
  processed: number;
  in_progress: number;
  awaiting_review: number;
  blocked: number;
  confirmed: number;
  failed: number;
  from_signed_xml: number;
  /** Null when not computable — the card is hidden, never filled with a placeholder. */
  accuracy: AccuracyStats | null;
}

export interface Template {
  id: string;
  version: number;
  name: string | null;
  queue_id: string | null;
  queue_name: string | null;
  in_use: boolean;
  created_at: string;
  fields: SchemaField[];
}

export interface Org {
  id: string;
  name: string;
  vat_number: string | null;
  data_region: string | null;
}

export interface SystemInfo {
  environment: string;
  inference_model: string;
  extraction_mode: "text" | "vision" | "auto";
  vision_model: string;
  ocr_engine: string;
  max_upload_bytes: number;
  grounding_threshold: number;
  stalled_after_s: number;
}

/** What the browser needs to POST one PDF straight to the API. */
export interface UploadAuthorization {
  /** Absolute URL, carrying a signed token. Expires in minutes. */
  upload_url: string;
  expires_in: number;
  max_bytes: number;
}

export interface UploadResult {
  document_id: string;
  filename: string | null;
  size_bytes: number;
  status: string;
  annotation_id: string | null;
  /** True when this exact file was already uploaded (HTTP 200, not 202). */
  duplicate: boolean;
  /** True when an earlier failed attempt is being processed again. */
  retried: boolean;
}

/** The current value: a human correction supersedes what was extracted. */
export function currentValue(field: ExtractedField): string | null {
  return field.value_final !== null ? field.value_final : field.value_extracted;
}

export function fieldKeyOf(field: ExtractedField): string {
  return field.row_index === null
    ? field.field_key
    : `${field.field_key}[${field.row_index}]`;
}
