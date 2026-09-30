/**
 * Who read the invoice, as numbers: how many fields each reader filled.
 *
 * Kept free of React and of runtime imports so Node's own test runner can load
 * it directly (`npm test`). A reviewer's correction is not a reading, and a
 * field with no value was filled by nobody, so neither is counted.
 */

import type { ExtractedField } from "@/lib/api/types";

export type SourceKind = "xml" | "qr" | "model" | "computed";

/** Order of authority: what was signed, what was encoded, what was guessed, what was derived. */
export const SOURCE_ORDER: readonly SourceKind[] = ["xml", "qr", "model", "computed"];

const KIND_OF: Partial<Record<NonNullable<ExtractedField["source"]>, SourceKind>> = {
  ubl_xml: "xml",
  qr: "qr",
  vlm: "model",
  computed: "computed",
};

export function countSources(
  fields: readonly Pick<ExtractedField, "source" | "value_extracted">[],
): Record<SourceKind, number> {
  const counts: Record<SourceKind, number> = { xml: 0, qr: 0, model: 0, computed: 0 };
  for (const field of fields) {
    const kind = field.source ? KIND_OF[field.source] : undefined;
    if (kind && field.value_extracted?.trim()) counts[kind] += 1;
  }
  return counts;
}
