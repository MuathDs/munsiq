"use client";

import { CircleAlert, CircleCheck, FileText, Loader2, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { formatBytes, formatElapsed } from "@/lib/format";
import type { Locale } from "@/lib/i18n";
import { interpolate, type Messages } from "@/lib/messages";

import type { UploadRow } from "./uploadRows";

/**
 * One row per file, with what is actually known about it.
 *
 * Uploading shows a real percentage: bytes sent, from the browser's own upload
 * events. Once the file is accepted the backend takes over and reports no
 * progress at all, so the bar becomes an indeterminate one with an elapsed timer
 * — honest about "working, no idea how far" — rather than a number that was
 * never measured.
 */

function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [active]);
  return now;
}

function errorText(row: UploadRow, t: Messages, locale: Locale, maxMb: number): string {
  const error = row.error;
  if (!error) return "";
  switch (error.code) {
    case "stalled":
      return t.upload.stalled;
    case "pipeline":
      return (locale === "ar" ? error.ar : error.en) ?? t.upload.failed;
    case "notPdf":
      return t.upload.errors.notPdf;
    case "tooLarge":
      return interpolate(t.upload.errors.tooLarge, { size: maxMb });
    case "network":
      return t.upload.errors.network;
    case "expired":
      return t.upload.errors.expired;
    case "server":
      return interpolate(t.upload.errors.server, { status: error.status ?? "?" });
  }
}

export function UploadQueue({
  rows,
  t,
  locale,
  maxMb,
  onClear,
}: {
  rows: UploadRow[];
  t: Messages;
  locale: Locale;
  maxMb: number;
  onClear: () => void;
}) {
  const processing = rows.some((row) => row.phase === "processing");
  const now = useNow(processing);
  if (rows.length === 0) return null;
  const anyFinished = rows.some((row) => row.finished);

  return (
    <div className="rounded-[14px] border border-line bg-surface">
      <ul>
        {rows.map((row) => (
          <li
            key={row.item.id}
            className="flex items-center gap-4 border-t border-line px-5 py-3.5 first:border-t-0"
          >
            <FileText size={16} className="shrink-0 text-ink-faint" aria-hidden />
            <div className="min-w-0 flex-1">
              <p className="truncate text-[13px] font-medium text-ink" title={row.item.name}>
                <bdi>{row.item.name}</bdi>
              </p>
              <p className="tabular mt-0.5 font-mono text-[11px] text-ink-faint" dir="ltr">
                {formatBytes(row.item.size)}
              </p>
            </div>

            <div className="w-[260px] shrink-0">
              {row.phase === "queued" ? (
                <p className="text-[12px] text-ink-faint">{t.upload.queued}</p>
              ) : null}

              {row.phase === "uploading" ? (
                <div>
                  <div className="h-1.5 overflow-hidden rounded-full bg-line">
                    <div
                      className="h-full bg-accent transition-[width] duration-200"
                      style={{ inlineSize: `${row.item.progress}%` }}
                    />
                  </div>
                  <p className="tabular mt-1 text-[12px] text-ink-soft">
                    {interpolate(t.upload.uploading, { pct: row.item.progress })}
                  </p>
                </div>
              ) : null}

              {row.phase === "processing" ? (
                <div>
                  <div className="indeterminate h-1.5 rounded-full bg-line" />
                  <p className="tabular mt-1 flex items-center gap-1.5 text-[12px] text-ink-soft">
                    <Loader2 size={12} className="animate-spin" aria-hidden />
                    {row.item.processingSince
                      ? interpolate(t.upload.processingFor, {
                          time: formatElapsed(now - row.item.processingSince),
                        })
                      : t.upload.processing}
                  </p>
                </div>
              ) : null}

              {row.phase === "done" ? (
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="flex items-center gap-1.5 text-[12px] font-medium text-success">
                      <CircleCheck size={13} aria-hidden />
                      {t.upload.done}
                    </p>
                    {row.item.duplicate ? (
                      <p className="mt-0.5 text-[11px] text-ink-faint">{t.upload.duplicate}</p>
                    ) : null}
                    {row.item.retried ? (
                      <p className="mt-0.5 text-[11px] text-ink-faint">{t.upload.retried}</p>
                    ) : null}
                  </div>
                  {row.annotationId ? (
                    <Link
                      href={`/${locale}/annotations/${row.annotationId}`}
                      className="shrink-0 rounded-[9px] border border-line-strong px-3 py-1 text-[12px] font-semibold text-ink transition-colors hover:bg-surface-hover"
                    >
                      {t.upload.open}
                    </Link>
                  ) : null}
                </div>
              ) : null}

              {row.phase === "failed" ? (
                <div className="flex items-start justify-between gap-3">
                  <p className="flex items-start gap-1.5 text-[12px] text-danger">
                    <CircleAlert size={13} className="mt-0.5 shrink-0" aria-hidden />
                    <span className="line-clamp-3">{errorText(row, t, locale, maxMb)}</span>
                  </p>
                  {row.annotationId ? (
                    <Link
                      href={`/${locale}/annotations/${row.annotationId}`}
                      className="shrink-0 rounded-[9px] border border-line-strong px-3 py-1 text-[12px] font-semibold text-ink transition-colors hover:bg-surface-hover"
                    >
                      {t.upload.open}
                    </Link>
                  ) : null}
                </div>
              ) : null}
            </div>
          </li>
        ))}
      </ul>

      {anyFinished ? (
        <div className="flex justify-end border-t border-line px-5 py-2.5">
          <button
            type="button"
            onClick={onClear}
            className="inline-flex items-center gap-1.5 rounded-[9px] px-2.5 py-1 text-[12px] font-medium text-ink-soft transition-colors hover:bg-surface-hover hover:text-ink"
          >
            <X size={13} aria-hidden />
            {t.upload.clear}
          </button>
        </div>
      ) : null}
    </div>
  );
}
