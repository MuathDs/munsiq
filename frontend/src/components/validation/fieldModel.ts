/**
 * How fields are grouped, ordered and labelled.
 *
 * One module, used by both the field pane and the keyboard navigation, so the
 * order a reviewer Tabs through is exactly the order they see. Two copies of
 * this logic would drift, and Tab would start jumping around the screen.
 */

import {
  currentValue,
  type ExtractedField,
  type SchemaField,
  type ValidationFinding,
} from "@/lib/api/types";

import { provenanceOf, type ProvenanceKind } from "./ProvenanceBadge";

export type Tier = "blocking" | "review" | "validated";

const TIER_RANK: Record<Tier, number> = { blocking: 0, review: 1, validated: 2 };

export function tierOf(field: ExtractedField): Tier {
  if (field.validation_state === "blocking") return "blocking";
  if (field.validation_state === "auto_validated") return "validated";
  return "review";
}

export function hasMismatch(field: ExtractedField, findings: ValidationFinding[]): boolean {
  return findings.some(
    (f) => f.rule_code === "XML_PDF_MISMATCH" && !f.passed && f.field_key === field.field_key,
  );
}

export function kindOf(field: ExtractedField, findings: ValidationFinding[]): ProvenanceKind {
  return provenanceOf(field.source, hasMismatch(field, findings));
}

/**
 * Tier first (what needs a decision), then the schema's own order (how the
 * invoice reads: number, date, seller, totals), never alphabetical.
 */
export function orderFields(fields: ExtractedField[], schema: SchemaField[]): ExtractedField[] {
  const position = new Map(schema.map((spec, index) => [spec.key, index]));
  const width = schema.length + 1;
  const rank = (field: ExtractedField) => {
    const base = position.get(field.field_key) ?? schema.length;
    // Line items read row by row — every cell of line 1, then line 2 — after
    // the header, rather than all descriptions followed by all quantities.
    return field.row_index === null ? base : width * (field.row_index + 1) + base;
  };
  return [...fields].sort(
    (a, b) =>
      TIER_RANK[tierOf(a)] - TIER_RANK[tierOf(b)] ||
      rank(a) - rank(b) ||
      a.field_key.localeCompare(b.field_key) ||
      (a.row_index ?? -1) - (b.row_index ?? -1),
  );
}

const warnedKeys = new Set<string>();

/**
 * The schema's label in the reviewer's language.
 *
 * Never the raw key. A missing label for the reviewer's language falls back to
 * the other language's label, then to a humanised key ("Seller vat number") —
 * and each fallback is logged once, because it is a schema-authoring gap to fix
 * at the source, not something the UI should quietly paper over.
 */
export function labelFor(key: string, schema: SchemaField[], isArabic: boolean): string {
  const spec = schema.find((s) => s.key === key);
  const own = isArabic ? spec?.label_ar : spec?.label_en;
  if (own) return own;

  const warning = `${key}:${isArabic ? "ar" : "en"}`;
  if (!warnedKeys.has(warning)) {
    warnedKeys.add(warning);
    console.warn(
      `[munsiq] extraction schema has no ${isArabic ? "label_ar" : "label_en"} for "${key}"` +
        (spec ? "" : " (the key is not in the schema at all)"),
    );
  }

  const other = isArabic ? spec?.label_en : spec?.label_ar;
  if (other) return other;
  const words = key.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function isRequired(key: string, schema: SchemaField[]): boolean {
  return schema.find((s) => s.key === key)?.required ?? false;
}

const NUMERIC_TYPES = new Set(["decimal", "number", "integer", "money", "date"]);

/**
 * Numbers, dates, VAT numbers and invoice references render in JetBrains Mono,
 * per the design handoff: digits line up and 0/O and 1/l stay distinct. Prose —
 * and any Arabic, which the mono face has no glyphs for — stays in the UI face.
 */
export function isNumericLike(field: ExtractedField, schema: SchemaField[]): boolean {
  const spec = schema.find((s) => s.key === field.field_key);
  if (spec && NUMERIC_TYPES.has(spec.type.toLowerCase())) return true;
  const value = currentValue(field);
  return value !== null && /\d/.test(value) && /^[0-9A-Za-z\s.,:/+-]+$/.test(value);
}
