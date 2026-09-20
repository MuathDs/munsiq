/**
 * What a document's row means, in one place.
 *
 * The API reports a raw state and a count of blocking findings; the UI groups
 * those into the five things a reviewer thinks in. Keeping the mapping here means
 * the status badge, the filter chips and the stat counts cannot disagree.
 */

import type { DocumentListItem } from "@/lib/api/types";

export type Category = "processing" | "review" | "blocked" | "confirmed" | "failed";

const CONFIRMED = new Set(["confirmed", "approved", "exporting", "exported"]);
const FAILED = new Set(["failed", "stalled", "rejected"]);

export function categoryOf(doc: DocumentListItem): Category {
  if (doc.state === "processing") return "processing";
  if (FAILED.has(doc.state)) return "failed";
  if (CONFIRMED.has(doc.state)) return "confirmed";
  // Awaiting review. Unresolved errors mean Confirm will refuse, which is the
  // thing worth seeing before opening the document.
  return doc.blocking_count > 0 ? "blocked" : "review";
}

/** Only exports of a confirmed annotation exist; the API refuses anything else. */
export function isExportable(doc: DocumentListItem): boolean {
  return doc.annotation_id !== null && CONFIRMED.has(doc.state);
}

/** A row with an annotation opens the workspace — including a failed one, which shows why. */
export function isOpenable(doc: DocumentListItem): boolean {
  return doc.annotation_id !== null;
}
