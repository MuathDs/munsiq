"use client";

import { useEffect, useMemo } from "react";

import type { DocumentListItem } from "@/lib/api/types";
import type { Locale } from "@/lib/i18n";
import { interpolate, type Messages } from "@/lib/messages";
import { useToasts } from "@/lib/useToasts";

import { ToastStack } from "../ToastStack";
import { DocumentsTable } from "./DocumentsTable";
import { ProcessingBanner } from "./ProcessingBanner";
import { TopBar } from "./TopBar";
import { UploadDropzone } from "./UploadDropzone";
import { MAX_FILES_PER_BATCH, useUploads } from "./UploadProvider";
import { UploadQueue } from "./UploadQueue";
import { deriveRow } from "./uploadRows";
import { useLiveDocuments } from "./useLiveDocuments";

/**
 * Batch upload, with real progress.
 *
 * Bytes are posted straight to the backend (see UploadProvider), so the
 * percentage while uploading is measured. After acceptance the row waits on the
 * backend's own document list: 'processing' until it reports a result.
 */
export function UploadView({
  initialDocuments,
  maxMb,
  locale,
  t,
}: {
  initialDocuments: DocumentListItem[];
  maxMb: number;
  locale: Locale;
  t: Messages;
}) {
  const { items, accepted, add, dismiss } = useUploads();
  const { documents, failing, snapshotAt } = useLiveDocuments(initialDocuments, null, {
    refreshKey: accepted,
  });
  const { toasts, pushToast, dismissToast } = useToasts();

  useEffect(() => {
    if (failing) pushToast(t.dashboard.connectionLost);
  }, [failing, pushToast, t]);

  const rows = useMemo(() => {
    const byId = new Map(documents.map((doc) => [doc.document_id, doc]));
    return items.map((item) => deriveRow(item, byId, snapshotAt));
  }, [items, documents, snapshotAt]);

  const complete = rows.filter((row) => row.finished).length;

  function onFilesSelected(files: File[]) {
    const truncated = add(files);
    if (truncated) {
      pushToast(interpolate(t.upload.errors.tooMany, { count: MAX_FILES_PER_BATCH }));
    }
  }

  return (
    <>
      <TopBar title={t.upload.title} subtitle={t.upload.subtitle} />
      <UploadDropzone onFilesSelected={onFilesSelected} t={t} maxMb={maxMb} />
      <ProcessingBanner total={rows.length} complete={complete} t={t} />
      <UploadQueue
        rows={rows}
        t={t}
        locale={locale}
        maxMb={maxMb}
        onClear={() => dismiss(rows.filter((row) => row.finished).map((row) => row.item.id))}
      />

      <section className="flex flex-col gap-3">
        <h2 className="text-base font-semibold text-ink">{t.upload.recent}</h2>
        <DocumentsTable documents={documents.slice(0, 10)} t={t} locale={locale} />
      </section>

      <ToastStack toasts={toasts} onDismiss={dismissToast} />
    </>
  );
}
