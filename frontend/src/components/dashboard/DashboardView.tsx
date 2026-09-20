"use client";

import { ArrowRight, UploadCloud } from "lucide-react";
import Link from "next/link";
import { useEffect } from "react";

import type { DocumentListItem, Stats } from "@/lib/api/types";
import type { Locale } from "@/lib/i18n";
import type { Messages } from "@/lib/messages";
import { useToasts } from "@/lib/useToasts";

import { ToastStack } from "../ToastStack";
import { DocumentsTable } from "./DocumentsTable";
import { StatsCards } from "./StatsCards";
import { TopBar } from "./TopBar";
import { useUploads } from "./UploadProvider";
import { useLiveDocuments } from "./useLiveDocuments";

const RECENT = 8;

/**
 * The landing page: what is done, what is waiting, what is broken.
 *
 * Rendered on the server first, then kept current by polling — but only while a
 * document is processing. Stat cards the data cannot support are not rendered at
 * all (see StatsCards).
 */
export function DashboardView({
  initialDocuments,
  initialStats,
  locale,
  t,
}: {
  initialDocuments: DocumentListItem[];
  initialStats: Stats;
  locale: Locale;
  t: Messages;
}) {
  const { accepted } = useUploads();
  const { documents, stats, failing } = useLiveDocuments(initialDocuments, initialStats, {
    withStats: true,
    refreshKey: accepted,
  });
  const { toasts, pushToast, dismissToast } = useToasts();

  useEffect(() => {
    if (failing) pushToast(t.dashboard.connectionLost);
  }, [failing, pushToast, t]);

  const uploadHref = `/${locale}/upload`;

  return (
    <>
      <TopBar
        title={t.dashboard.title}
        subtitle={t.dashboard.subtitle}
        actions={
          <Link
            href={uploadHref}
            className="inline-flex items-center gap-2 rounded-[9px] bg-accent px-4 py-2 text-[13px] font-semibold text-white transition-colors hover:bg-accent-strong"
          >
            <UploadCloud size={15} aria-hidden />
            {t.dashboard.uploadCta}
          </Link>
        }
      />

      {stats ? <StatsCards stats={stats} t={t} /> : null}

      <section className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold text-ink">{t.dashboard.recent}</h2>
          {documents.length > RECENT ? (
            <Link
              href={`/${locale}/history`}
              className="inline-flex items-center gap-1.5 text-[13px] font-medium text-ink-soft transition-colors hover:text-ink"
            >
              {t.dashboard.viewAll}
              <ArrowRight size={14} aria-hidden className="rtl:-scale-x-100" />
            </Link>
          ) : null}
        </div>
        <DocumentsTable
          documents={documents.slice(0, RECENT)}
          t={t}
          locale={locale}
          emptyText={t.dashboard.empty}
          emptyAction={
            <Link
              href={uploadHref}
              className="rounded-[9px] bg-accent px-4 py-2 text-[13px] font-semibold text-white transition-colors hover:bg-accent-strong"
            >
              {t.dashboard.uploadCta}
            </Link>
          }
        />
      </section>

      <ToastStack toasts={toasts} onDismiss={dismissToast} />
    </>
  );
}
