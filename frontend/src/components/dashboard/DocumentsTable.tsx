"use client";

import { ArrowUpRight, Bot, Inbox, Search, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState, type ReactNode } from "react";

import type { DocumentListItem } from "@/lib/api/types";
import { formatDateTime, formatMoney } from "@/lib/format";
import type { Locale } from "@/lib/i18n";
import { interpolate, type Messages } from "@/lib/messages";

import { categoryOf, isExportable, isOpenable, type Category } from "./docState";
import { StatusBadge } from "./StatusBadge";

/**
 * The real list of documents: the prototype's "Extracted Data" table, fed by the
 * backend instead of an in-memory job store.
 *
 * A row opens the validation workspace. Rows still processing have no annotation
 * to open, so they are inert and say so by looking it. A failed row does open —
 * the workspace shows the reason as its blocking finding.
 */

const FILTERS: ("all" | Category)[] = [
  "all",
  "processing",
  "review",
  "blocked",
  "confirmed",
  "failed",
];

const EXPORT_FORMATS = ["json", "xlsx", "csv"] as const;

interface Props {
  documents: DocumentListItem[];
  t: Messages;
  locale: Locale;
  /** Search and status filter. Off for the compact "recent" lists. */
  toolbar?: boolean;
  /** Rendered in the empty state, e.g. a link to the upload page. */
  emptyAction?: ReactNode;
  emptyText?: string;
}

export function DocumentsTable({
  documents,
  t,
  locale,
  toolbar = false,
  emptyAction,
  emptyText,
}: Props) {
  const router = useRouter();
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<"all" | Category>("all");

  const counts = useMemo(() => {
    const tally: Record<string, number> = { all: documents.length };
    for (const doc of documents) {
      const category = categoryOf(doc);
      tally[category] = (tally[category] ?? 0) + 1;
    }
    return tally;
  }, [documents]);

  const visible = useMemo(() => {
    const query = search.trim().toLowerCase();
    return documents.filter((doc) => {
      if (filter !== "all" && categoryOf(doc) !== filter) return false;
      if (!query) return true;
      return [doc.invoice_number, doc.seller_name, doc.filename].some((value) =>
        (value ?? "").toLowerCase().includes(query),
      );
    });
  }, [documents, filter, search]);

  return (
    <div className="rounded-[14px] border border-line bg-surface">
      {toolbar ? (
        <div className="flex flex-wrap items-center justify-between gap-4 border-b border-line px-5 py-4">
          <div className="flex flex-wrap items-center gap-1.5">
            {FILTERS.map((key) => {
              const active = filter === key;
              return (
                <button
                  key={key}
                  type="button"
                  onClick={() => setFilter(key)}
                  aria-pressed={active}
                  className={`inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-[13px] font-medium transition-colors ${
                    active
                      ? "bg-accent/14 text-ink"
                      : "text-ink-soft hover:bg-surface-hover hover:text-ink"
                  }`}
                >
                  {t.history.filter[key]}
                  <span className="tabular font-mono text-[11px] text-ink-faint">
                    {counts[key] ?? 0}
                  </span>
                </button>
              );
            })}
          </div>

          <div className="relative">
            <Search
              size={14}
              aria-hidden
              className="pointer-events-none absolute start-2.5 top-1/2 -translate-y-1/2 text-ink-faint"
            />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder={t.history.search}
              aria-label={t.history.search}
              className="w-[360px] max-w-full rounded-[9px] border border-line bg-bg py-1.5 pe-3 ps-8 text-[13px] text-ink placeholder:text-ink-faint"
            />
          </div>
        </div>
      ) : null}

      {documents.length === 0 || visible.length === 0 ? (
        <div className="flex flex-col items-center gap-3 px-6 py-16 text-center">
          <Inbox size={28} className="text-ink-faint" aria-hidden />
          <p className="max-w-sm text-sm text-ink-soft">
            {documents.length === 0 ? (emptyText ?? t.history.empty) : t.history.noMatch}
          </p>
          {documents.length === 0 ? emptyAction : null}
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[900px] text-start text-sm">
            <thead>
              <tr className="text-xs uppercase tracking-wide text-ink-faint">
                <Th>{t.history.columns.document}</Th>
                <Th>{t.history.columns.seller}</Th>
                <Th align="end">{t.history.columns.total}</Th>
                <Th>{t.history.columns.source}</Th>
                <Th>{t.history.columns.uploaded}</Th>
                <Th>{t.history.columns.status}</Th>
                <Th>
                  <span className="sr-only">{t.history.export}</span>
                </Th>
              </tr>
            </thead>
            <tbody>
              {visible.map((doc) => {
                const openable = isOpenable(doc);
                const href = `/${locale}/annotations/${doc.annotation_id}`;
                const reason = locale === "ar" ? doc.error_ar : doc.error_en;
                return (
                  <tr
                    key={doc.document_id}
                    onClick={openable ? () => router.push(href) : undefined}
                    className={`border-t border-line transition-colors ${
                      openable ? "cursor-pointer hover:bg-surface-hover" : ""
                    }`}
                  >
                    <td className="min-w-[230px] max-w-[300px] px-4 py-3.5">
                      <div className="flex min-w-0 items-center gap-2.5">
                        <div className="min-w-0">
                          {openable ? (
                            <Link
                              href={href}
                              onClick={(event) => event.stopPropagation()}
                              className="tabular block truncate font-mono text-[13px] font-semibold text-ink hover:underline"
                              dir="ltr"
                            >
                              {doc.invoice_number ?? doc.filename ?? t.history.unnamed}
                            </Link>
                          ) : (
                            <span
                              className="tabular block truncate font-mono text-[13px] font-semibold text-ink-soft"
                              dir="ltr"
                            >
                              {doc.invoice_number ?? doc.filename ?? t.history.unnamed}
                            </span>
                          )}
                          {doc.invoice_number && doc.filename ? (
                            <span
                              className="block truncate font-mono text-[11px] text-ink-faint"
                              dir="ltr"
                            >
                              {doc.filename}
                            </span>
                          ) : null}
                          {categoryOf(doc) === "failed" && reason ? (
                            <span
                              title={reason}
                              className="mt-0.5 line-clamp-2 block break-words text-[11px] text-danger"
                            >
                              {reason}
                            </span>
                          ) : null}
                        </div>
                      </div>
                    </td>
                    <td className="max-w-[150px] px-4 py-3.5 text-ink-soft">
                      {/* Truncated inside its own isolate, so an English name in an
                          Arabic row is clipped at ITS end, not the row's. */}
                      {doc.seller_name ? (
                        <bdi className="block truncate" title={doc.seller_name}>
                          {doc.seller_name}
                        </bdi>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td className="tabular whitespace-nowrap px-4 py-3.5 text-end font-mono text-ink" dir="ltr">
                      {doc.total_amount ? (
                        <>
                          {formatMoney(doc.total_amount)}
                          {doc.currency ? (
                            <span className="ms-1 text-[11px] text-ink-faint">{doc.currency}</span>
                          ) : null}
                        </>
                      ) : (
                        <span className="text-ink-faint">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3.5">
                      <SourceChip doc={doc} t={t} />
                    </td>
                    <td className="whitespace-nowrap px-4 py-3.5 text-[13px] text-ink-soft">
                      {formatDateTime(doc.created_at, locale)}
                    </td>
                    <td className="px-4 py-3.5">
                      <StatusBadge doc={doc} t={t} locale={locale} />
                    </td>
                    <td className="px-4 py-3.5">
                      {isExportable(doc) ? (
                        <ExportLinks id={doc.annotation_id as string} t={t} />
                      ) : openable ? (
                        <ArrowUpRight
                          size={15}
                          aria-hidden
                          className="text-ink-faint rtl:-scale-x-100"
                        />
                      ) : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {toolbar && documents.length > 0 ? (
        <p className="border-t border-line px-5 py-3 text-xs text-ink-faint">
          {interpolate(t.history.count, { shown: visible.length, total: documents.length })}
        </p>
      ) : null}
    </div>
  );
}

function Th({ children, align }: { children: ReactNode; align?: "end" }) {
  return (
    <th className={`px-4 py-3 font-medium ${align === "end" ? "text-end" : "text-start"}`}>
      {children}
    </th>
  );
}

/** Where the values came from: the product's whole economic argument, per row. */
function SourceChip({ doc, t }: { doc: DocumentListItem; t: Messages }) {
  if (doc.model_version) {
    return (
      <span
        title={doc.model_version}
        className="inline-flex max-w-[128px] items-center gap-1.5 rounded-full bg-warning/12 px-2.5 py-1 text-[11px] font-medium text-warning"
      >
        <Bot size={12} className="shrink-0" aria-hidden />
        <span className="truncate" dir="ltr">
          {interpolate(t.history.source.model, { model: doc.model_version })}
        </span>
      </span>
    );
  }
  if (doc.has_embedded_ubl && doc.annotation_id) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-success/12 px-2.5 py-1 text-[11px] font-medium text-success">
        <ShieldCheck size={12} aria-hidden />
        {t.history.source.xml}
      </span>
    );
  }
  return <span className="text-ink-faint">—</span>;
}

function ExportLinks({ id, t }: { id: string; t: Messages }) {
  return (
    <div
      role="group"
      aria-label={t.history.export}
      className="flex items-center gap-0.5"
      onClick={(event) => event.stopPropagation()}
    >
      {EXPORT_FORMATS.map((format) => (
        <a
          key={format}
          href={`/api/bff/annotations/${id}/export?format=${format}`}
          download
          title={interpolate(t.history.exportAs, { format: format.toUpperCase() })}
          className="rounded-[6px] px-1.5 py-0.5 font-mono text-[11px] font-semibold uppercase text-ink-soft transition-colors hover:bg-surface-hover hover:text-ink"
        >
          {format}
        </a>
      ))}
    </div>
  );
}
