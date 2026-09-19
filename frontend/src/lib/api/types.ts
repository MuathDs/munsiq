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

/** The current value: a human correction supersedes what was extracted. */
export function currentValue(field: ExtractedField): string | null {
  return field.value_final !== null ? field.value_final : field.value_extracted;
}

export function fieldKeyOf(field: ExtractedField): string {
  return field.row_index === null
    ? field.field_key
    : `${field.field_key}[${field.row_index}]`;
}
