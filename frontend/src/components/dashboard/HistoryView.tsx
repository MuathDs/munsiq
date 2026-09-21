"use client";

import { useEffect, useState } from "react";

import type { DocumentListItem } from "@/lib/api/types";
import type { Locale } from "@/lib/i18n";
import type { Messages } from "@/lib/messages";
import { useToasts } from "@/lib/useToasts";

import { ToastStack } from "../ToastStack";
import { DocumentsTable } from "./DocumentsTable";
import { TopBar } from "./TopBar";
import { useUploads } from "./UploadProvider";
import { useLiveDocuments } from "./useLiveDocuments";

/** Every document, filterable and searchable. A row opens the validation workspace. */
export function HistoryView({
  initialDocuments,
  locale,
  t,
}: {
  initialDocuments: DocumentListItem[];
  locale: Locale;
  t: Messages;
}) {
  const { accepted } = useUploads();
  // Bumped after an export: the backend has moved those invoices to "exported",
  // and the list should say so now rather than at the next poll.
  const [exportedCount, setExportedCount] = useState(0);
  const { documents, failing } = useLiveDocuments(initialDocuments, null, {
    refreshKey: accepted + exportedCount,
  });
  const { toasts, pushToast, dismissToast } = useToasts();

  useEffect(() => {
    if (failing) pushToast(t.dashboard.connectionLost);
  }, [failing, pushToast, t]);

  return (
    <>
      <TopBar title={t.history.title} subtitle={t.history.subtitle} />
      <DocumentsTable
        documents={documents}
        t={t}
        locale={locale}
        toolbar
        onExported={() => setExportedCount((count) => count + 1)}
        onNotify={pushToast}
      />
      <ToastStack toasts={toasts} onDismiss={dismissToast} />
    </>
  );
}
