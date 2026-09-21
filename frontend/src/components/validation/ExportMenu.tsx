"use client";

import {
  ChevronDown,
  Download,
  FileJson,
  FileSpreadsheet,
  FileText,
  Loader2,
} from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

import { downloadFile } from "@/lib/downloadExport";
import type { Locale } from "@/lib/i18n";
import type { Messages } from "@/lib/messages";

const FORMATS = [
  { format: "xlsx", icon: FileSpreadsheet },
  { format: "csv", icon: FileText },
  { format: "json", icon: FileJson },
] as const;

type Format = (typeof FORMATS)[number]["format"];

/**
 * Download the confirmed invoice as Excel, CSV or JSON.
 *
 * Before confirmation the control is present but disabled, and says why: only a
 * confirmed invoice leaves the system, because confirmation is where the rules stop
 * being advisory. A missing button would leave the reviewer wondering where export
 * went; a disabled one with no reason would look broken.
 *
 * A successful download tells the backend, which moves the invoice to "exported"
 * (a lifecycle state, not just a file), and `onExported` lets the page show it.
 */
export function ExportMenu({
  annotationId,
  confirmed,
  locale,
  t,
  onExported,
}: {
  annotationId: string;
  confirmed: boolean;
  locale: Locale;
  t: Messages;
  onExported: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<Format | null>(null);
  const [error, setError] = useState<string | null>(null);
  const root = useRef<HTMLDivElement>(null);
  const menuId = useId();
  const reasonId = useId();

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent | KeyboardEvent) => {
      if (event instanceof KeyboardEvent) {
        if (event.key === "Escape") setOpen(false);
      } else if (root.current && !root.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    window.addEventListener("mousedown", close);
    window.addEventListener("keydown", close);
    return () => {
      window.removeEventListener("mousedown", close);
      window.removeEventListener("keydown", close);
    };
  }, [open]);

  async function run(format: Format) {
    setBusy(format);
    setError(null);
    const result = await downloadFile(
      `/api/bff/annotations/${annotationId}/export?format=${format}`,
      locale,
      undefined,
      `munsiq-invoice.${format}`,
    );
    setBusy(null);
    if (result.ok) {
      setOpen(false);
      onExported();
    } else {
      setError(result.message ?? t.actions.exportFailed);
    }
  }

  const button =
    "flex h-9 items-center gap-2 rounded-[9px] border px-3 text-[13px] font-semibold transition-colors";

  if (!confirmed) {
    return (
      <span className="group relative inline-flex">
        <button
          type="button"
          disabled
          aria-describedby={reasonId}
          className={`${button} cursor-not-allowed border-line text-ink-faint`}
        >
          <Download size={15} aria-hidden />
          {t.actions.export}
        </button>
        {/* A disabled button receives no hover or focus, so the reason hangs off
            the wrapper: hover shows it, and it is always in the accessible name. */}
        <span
          id={reasonId}
          role="tooltip"
          className="pointer-events-none absolute end-0 top-full z-30 mt-2 hidden w-64 rounded-[9px] border border-line-strong bg-surface p-3 text-start text-[12px] font-normal leading-5 text-ink-soft shadow-lg group-hover:block"
        >
          {t.actions.exportLocked}
        </span>
      </span>
    );
  }

  return (
    <div ref={root} className="relative">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={menuId}
        className={`${button} border-line-strong text-ink hover:bg-surface-hover`}
      >
        {busy ? (
          <Loader2 size={15} className="animate-spin" aria-hidden />
        ) : (
          <Download size={15} aria-hidden />
        )}
        {busy ? t.actions.exporting : t.actions.export}
        <ChevronDown size={14} aria-hidden className="text-ink-faint" />
      </button>

      {open ? (
        <div
          id={menuId}
          role="menu"
          className="absolute end-0 top-full z-30 mt-2 w-48 overflow-hidden rounded-[10px] border border-line-strong bg-surface py-1 shadow-lg"
        >
          {FORMATS.map(({ format, icon: Icon }) => (
            <button
              key={format}
              type="button"
              role="menuitem"
              disabled={busy !== null}
              onClick={() => void run(format)}
              className="flex w-full items-center gap-2.5 px-3 py-2 text-start text-[13px] text-ink transition-colors hover:bg-surface-hover disabled:opacity-50"
            >
              <Icon size={15} aria-hidden className="text-ink-faint" />
              {t.actions.exportFormat[format]}
            </button>
          ))}
        </div>
      ) : null}

      <span role="status" aria-live="polite" className="sr-only">
        {error}
      </span>
      {error ? (
        <p className="absolute end-0 top-full z-30 mt-2 w-64 rounded-[9px] border border-danger/40 bg-danger-soft p-3 text-start text-[12px] leading-5 text-danger">
          {error}
        </p>
      ) : null}
    </div>
  );
}
