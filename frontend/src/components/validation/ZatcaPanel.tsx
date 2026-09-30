"use client";

/**
 * Compliance and provenance, collapsed into header chips.
 *
 * The previous full-width strip put four checks and a model note on one line of
 * 11px text, competing with everything beneath it. Now the header carries one
 * verdict ("ZATCA 4/4") that opens a panel with the detail, plus one chip per
 * reader — signed XML, QR, model, derived — with the number of fields it filled.
 *
 * The rules remain the single source of truth for compliance; this only renders
 * their verdicts.
 */

import {
  Bot,
  Calculator,
  ChevronDown,
  CircleCheck,
  CircleHelp,
  CircleX,
  QrCode,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

import type { ExtractedField, ValidationFinding } from "@/lib/api/types";
import { interpolate, type Messages } from "@/lib/messages";

import { countSources, SOURCE_ORDER, type SourceKind } from "./sourceCounts";

type Verdict = "ok" | "bad" | "unknown";

function verdictFor(findings: ValidationFinding[], code: string): Verdict {
  const hit = findings.find((f) => f.rule_code === code);
  // A rule that never ran is 'unknown', not 'ok'. A green tick for a check that
  // was never performed is exactly the false assurance this panel must avoid.
  if (!hit) return "unknown";
  return hit.passed ? "ok" : "bad";
}

interface Check {
  id: string;
  label: string;
  verdict: Verdict;
  value: string;
}

function checksFor(hasEmbeddedUbl: boolean, findings: ValidationFinding[], t: Messages): Check[] {
  const qr = verdictFor(findings, "QR_TOTAL_MATCH");
  const trn = verdictFor(findings, "TRN_FORMAT");
  const vat = verdictFor(findings, "VAT_CATEGORY_VALID");
  return [
    {
      id: "ubl",
      label: t.zatca.embeddedUbl,
      // Absence is not a failure — most AP intake is still scanned paper.
      verdict: hasEmbeddedUbl ? "ok" : "unknown",
      value: hasEmbeddedUbl ? t.zatca.embeddedUblYes : t.zatca.embeddedUblNo,
    },
    {
      id: "qr",
      label: t.zatca.qr,
      verdict: qr,
      value: qr === "ok" ? t.zatca.qrMatch : qr === "bad" ? t.zatca.qrMismatch : t.zatca.qrAbsent,
    },
    {
      id: "trn",
      label: t.zatca.trn,
      verdict: trn,
      value: trn === "ok" ? t.zatca.trnValid : trn === "bad" ? t.zatca.trnInvalid : t.zatca.notChecked,
    },
    {
      id: "vat",
      label: t.zatca.vatCategory,
      verdict: vat,
      value: vat === "ok" ? t.zatca.vatValid : vat === "bad" ? t.zatca.vatInvalid : t.zatca.notChecked,
    },
  ];
}

const CHIP = {
  success: "border-success/35 bg-success-soft text-success hover:border-success/60",
  danger: "border-danger/45 bg-danger-soft text-danger hover:border-danger/70",
  neutral: "border-line-strong bg-surface text-ink-soft hover:text-ink",
} as const;

const ICON_WELL: Record<Verdict, string> = {
  ok: "bg-success-soft text-success",
  bad: "bg-danger-soft text-danger",
  unknown: "bg-line text-ink-faint",
};

const VALUE_TONE: Record<Verdict, string> = {
  ok: "text-success",
  bad: "text-danger",
  unknown: "text-ink-faint",
};

export function ZatcaSummary({
  hasEmbeddedUbl,
  findings,
  t,
}: {
  hasEmbeddedUbl: boolean;
  findings: ValidationFinding[];
  t: Messages;
}) {
  const [open, setOpen] = useState(false);
  const wrapper = useRef<HTMLDivElement>(null);
  const panelId = useId();

  const checks = checksFor(hasEmbeddedUbl, findings, t);
  const passed = checks.filter((c) => c.verdict === "ok").length;
  const failed = checks.filter((c) => c.verdict === "bad").length;
  const run = passed + failed;
  const tone = failed > 0 ? "danger" : passed > 0 ? "success" : "neutral";

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: MouseEvent) => {
      if (wrapper.current && !wrapper.current.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      // Stop here: the workspace's Esc means "revert the focused field", and
      // closing a panel must not also discard a reviewer's edit.
      event.stopPropagation();
      setOpen(false);
    };
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div ref={wrapper} className="relative">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((value) => !value)}
        title={t.zatca.title}
        className={`inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-[12px] font-semibold transition-colors ${CHIP[tone]}`}
      >
        {tone === "danger" ? <ShieldAlert size={14} aria-hidden /> : <ShieldCheck size={14} aria-hidden />}
        <span>{t.zatca.short}</span>
        <span className="tabular font-mono">
          {run === 0 ? "—" : interpolate(t.zatca.checks, { passed, total: run })}
        </span>
        <ChevronDown
          size={13}
          aria-hidden
          className={`opacity-70 transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>

      {open ? (
        <div
          id={panelId}
          role="dialog"
          aria-label={t.zatca.title}
          className="absolute start-0 top-full z-40 mt-2 w-80 rounded-[14px] border border-line-strong bg-surface p-4 shadow-2xl"
        >
          <p className="text-sm font-semibold text-ink">{t.zatca.title}</p>
          <p className="mt-0.5 text-[12px] text-ink-faint">{t.zatca.subtitle}</p>
          <ul className="mt-4 space-y-3">
            {checks.map((check) => {
              const Icon =
                check.verdict === "ok" ? CircleCheck : check.verdict === "bad" ? CircleX : CircleHelp;
              return (
                <li key={check.id} className="flex items-center gap-3">
                  <span
                    className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${ICON_WELL[check.verdict]}`}
                  >
                    <Icon size={16} aria-hidden />
                  </span>
                  <div className="min-w-0">
                    <p className="text-[13px] text-ink">{check.label}</p>
                    <p className={`text-[12px] ${VALUE_TONE[check.verdict]}`}>{check.value}</p>
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

/**
 * Who read the invoice, as one chip per reader with the fields it filled:
 * "ZATCA XML · 11", "QR code · 5", "AI · 3", "Derived · 1".
 *
 * Every reader is always shown, and one that filled nothing is dimmed rather
 * than hidden — "no model was used" is the product's whole economic argument
 * for a compliant invoice, and an absent chip would not say it. Labels collapse
 * to icon + count below xl, where the header runs out of room; the full
 * sentence stays in the tooltip and the accessible name.
 */
const SOURCE_ICON: Record<SourceKind, typeof ShieldCheck> = {
  xml: ShieldCheck,
  qr: QrCode,
  model: Bot,
  computed: Calculator,
};

const SOURCE_TONE: Record<SourceKind, string> = {
  xml: "border-success/35 bg-success-soft text-success",
  qr: "border-success/35 bg-success-soft text-success",
  model: "border-warning/35 bg-warning-soft text-warning",
  computed: "border-line-strong bg-surface-hover text-ink",
};

const SOURCE_OFF = "border-line bg-surface text-ink-faint opacity-60";

function sourceTitle(kind: SourceKind, count: number, modelVersion: string | null, t: Messages) {
  switch (kind) {
    case "xml":
      return count ? interpolate(t.source.xmlTitle, { count }) : t.source.xmlNone;
    case "qr":
      return count ? interpolate(t.source.qrTitle, { count }) : t.source.qrNone;
    case "model":
      return modelVersion
        ? interpolate(t.source.modelTitle, { model: modelVersion, count })
        : t.source.modelNone;
    case "computed":
      return count ? interpolate(t.source.computedTitle, { count }) : t.source.computedNone;
  }
}

export function SourceChips({
  fields,
  modelVersion,
  t,
}: {
  fields: ExtractedField[];
  modelVersion: string | null;
  t: Messages;
}) {
  const counts = countSources(fields);
  return (
    <ul className="flex items-center gap-1.5" aria-label={t.source.title}>
      {SOURCE_ORDER.map((kind) => {
        const count = counts[kind];
        const Icon = SOURCE_ICON[kind];
        const title = sourceTitle(kind, count, modelVersion, t);
        return (
          <li
            key={kind}
            title={title}
            aria-label={`${t.source[kind]} · ${count} — ${title}`}
            data-source={kind}
            data-count={count}
            className={`inline-flex h-8 items-center gap-1.5 rounded-full border px-2.5 text-[12px] font-semibold ${
              count > 0 ? SOURCE_TONE[kind] : SOURCE_OFF
            }`}
          >
            <Icon size={14} className="shrink-0" aria-hidden />
            <span className="hidden whitespace-nowrap xl:inline" aria-hidden>
              {t.source[kind]}
            </span>
            <span className="hidden opacity-60 xl:inline" aria-hidden>
              ·
            </span>
            <span className="tabular font-mono" aria-hidden>
              {count}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
