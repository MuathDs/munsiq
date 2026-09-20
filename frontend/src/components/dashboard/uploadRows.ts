/**
 * What an upload's row shows, settled against the backend's live document list.
 *
 * The upload engine knows about bytes: queued, uploading, accepted. Everything
 * after acceptance is the BACKEND's to say — the pipeline runs in a background
 * task — so an accepted file stays 'processing' here until the document list
 * reports a result. This module is that join, kept pure so the banner and the
 * rows cannot disagree about who is finished.
 */

import type { DocumentListItem } from "@/lib/api/types";

import type { UploadError, UploadItem, UploadPhase } from "./UploadProvider";

export interface UploadRow {
  item: UploadItem;
  phase: UploadPhase;
  /** Set once there is something to open. */
  annotationId: string | null;
  /** Why it failed, when it did: a client-side code, or the backend's own words. */
  error: UploadError | { code: "stalled" } | { code: "pipeline"; en: string | null; ar: string | null } | null;
  finished: boolean;
}

export function deriveRow(
  item: UploadItem,
  docs: Map<string, DocumentListItem>,
  /** When the request behind `docs` was made. See useLiveDocuments. */
  snapshotAt: number,
): UploadRow {
  if (item.phase !== "processing" || item.documentId === null) {
    return {
      item,
      phase: item.phase,
      annotationId: item.annotationId,
      error: item.error,
      finished: item.phase === "done" || item.phase === "failed",
    };
  }

  const doc = docs.get(item.documentId);
  // A list requested BEFORE this upload was accepted cannot know its outcome. The
  // case that matters is a retry: the old failed annotation is still in a stale
  // snapshot, and reading it would flash the previous failure over a document
  // that is, right now, processing again.
  const stale = item.processingSince !== null && snapshotAt < item.processingSince;
  // Not in the list yet (the first poll has not landed): still processing.
  if (!doc || stale || doc.state === "processing") {
    return { item, phase: "processing", annotationId: null, error: null, finished: false };
  }
  if (doc.state === "stalled") {
    return { item, phase: "failed", annotationId: null, error: { code: "stalled" }, finished: true };
  }
  if (doc.state === "failed") {
    return {
      item,
      phase: "failed",
      annotationId: doc.annotation_id,
      error: { code: "pipeline", en: doc.error_en, ar: doc.error_ar },
      finished: true,
    };
  }
  return { item, phase: "done", annotationId: doc.annotation_id, error: null, finished: true };
}
