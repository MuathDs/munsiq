"use client";

/**
 * Compliance and provenance, collapsed into two header chips.
 *
 * The previous full-width strip put four checks and a model note on one line of
 * 11px text, competing with everything beneath it. Now the header carries one
 * verdict ("ZATCA 4/4") that opens a panel with the detail, plus a chip saying
 * whether the values came from signed XML or a model.
 *
 * The rules remain the single source of truth for compliance; this only renders
 * their verdicts.
 */

import {
  Bot,
  ChevronDown,
  CircleCheck,
  CircleHelp,
  CircleX,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

import type { ValidationFinding } from "@/lib/api/types";
import { interpolate, type Messages } from "@/lib/messages";

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
  const trn = verdictFor(findings, "TRN_CHECKSUM");
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
 * Where the values came from, as one fact rather than a sentence.
 *
 * "Signed XML · no AI" is the product's whole economic argument — a compliant
 * invoice cost zero model calls — so it earns a header chip of its own.
 */
export function SourceChip({ modelVersion, t }: { modelVersion: string | null; t: Messages }) {
  if (!modelVersion) {
    return (
      <span
        title={t.zatca.noModel}
        className="inline-flex h-8 items-center gap-1.5 rounded-full border border-success/35 bg-success-soft px-3 text-[12px] font-semibold text-success"
      >
        <ShieldCheck size={14} aria-hidden />
        {t.source.signed}
      </span>
    );
  }
  return (
    <span
      title={`${t.zatca.modelVersion}: ${modelVersion}`}
      className="inline-flex h-8 max-w-64 items-center gap-1.5 rounded-full border border-warning/35 bg-warning-soft px-3 text-[12px] font-semibold text-warning"
    >
      <Bot size={14} className="shrink-0" aria-hidden />
      <span className="truncate">{interpolate(t.source.model, { model: modelVersion })}</span>
    </span>
  );
}
