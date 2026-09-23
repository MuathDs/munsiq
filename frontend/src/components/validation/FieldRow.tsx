"use client";

/**
 * One field. Reading order, and therefore visual weight, top to bottom:
 *
 *   label + provenance badge   13px label, badge pinned to the inline end so
 *                              every badge in the list lines up in one column
 *   VALUE                      16px semibold — the thing a reviewer is actually
 *                              checking, so the heaviest element in the row
 *   findings                   only when a rule has something to say
 *
 * A `ubl_xml` value renders read-only. It came from a cryptographically signed
 * attachment, so overwriting it takes a deliberate act — the unlock control —
 * rather than a stray keystroke.
 */

import { Lock, LockOpen, TriangleAlert } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import {
  currentValue,
  fieldKeyOf,
  type ExtractedField,
  type ValidationFinding,
} from "@/lib/api/types";
import type { Messages } from "@/lib/messages";

import {
  MismatchComparison,
  ProvenanceBadge,
  provenanceOf,
  type ProvenanceKind,
} from "./ProvenanceBadge";

interface Props {
  field: ExtractedField;
  label: string;
  required: boolean;
  numeric: boolean;
  findings: ValidationFinding[];
  focused: boolean;
  t: Messages;
  isArabic: boolean;
  onFocus: () => void;
  onHover: (hovering: boolean) => void;
  onChange: (value: string | null) => void;
}

/** The inline-start bar carries provenance, so the colour reads down the list. */
const BAR: Record<ProvenanceKind, string> = {
  verified: "bg-success",
  extracted: "bg-warning",
  mismatch: "bg-danger",
  human: "bg-accent-strong",
  absent: "bg-line-strong",
};

export function FieldRow({
  field,
  label,
  required,
  numeric,
  findings,
  focused,
  t,
  isArabic,
  onFocus,
  onHover,
  onChange,
}: Props) {
  const value = currentValue(field);
  const [draft, setDraft] = useState(value ?? "");
  const [unlocked, setUnlocked] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  // Server-authoritative: after a flush the field may come back revalidated,
  // so the draft follows it unless the reviewer is actively editing.
  useEffect(() => {
    if (document.activeElement !== inputRef.current) setDraft(value ?? "");
  }, [value]);

  useEffect(() => {
    if (focused) inputRef.current?.focus();
  }, [focused]);

  const mismatch = findings.find((f) => f.rule_code === "XML_PDF_MISMATCH" && !f.passed);
  const kind = provenanceOf(field.source, Boolean(mismatch));
  const readOnly = kind === "verified" && !unlocked;
  const blocking = field.validation_state === "blocking";
  const failures = findings.filter((f) => !f.passed);
  const inputId = `field-${fieldKeyOf(field)}`;

  const surface = blocking
    ? "border-danger/40 bg-danger-soft"
    : focused
      ? "border-line-strong bg-surface-hover"
      : "border-line bg-surface hover:border-line-strong";

  const valueFace = numeric ? "font-mono tabular tracking-tight" : "";
  const inputChrome = readOnly
    ? "cursor-default border-0 bg-transparent px-0 focus-visible:outline-none"
    : "rounded-[9px] border border-line-strong bg-bg px-3 focus:border-accent focus-visible:outline-none";

  return (
    <li
      className={`relative rounded-[10px] border py-3.5 pe-4 ps-5 transition-colors ${surface} ${
        focused ? "ring-2 ring-accent/50" : ""
      }`}
      onMouseEnter={() => onHover(true)}
      onMouseLeave={() => onHover(false)}
    >
      <span
        aria-hidden
        className={`absolute inset-y-3 start-1.5 w-[3px] rounded-full ${blocking ? "bg-danger" : BAR[kind]}`}
      />

      <div className="flex items-start justify-between gap-3">
        {/* The schema's label only — never the raw field key. The key is an API
            identifier; a reviewer should not have to read snake_case. */}
        <label
          htmlFor={inputId}
          className="min-w-0 pt-1 text-[13px] font-medium leading-5 text-ink-soft"
        >
          {label}
          {field.row_index !== null ? (
            <span className="tabular ms-1.5 font-mono text-ink-faint">#{field.row_index + 1}</span>
          ) : null}
          {required ? (
            <span className="text-danger/80" aria-hidden>
              {" *"}
            </span>
          ) : null}
        </label>
        <ProvenanceBadge kind={kind} t={t} confidence={field.confidence} />
      </div>

      <div className="mt-2.5 flex items-center gap-2">
        <input
          id={inputId}
          ref={inputRef}
          value={draft}
          readOnly={readOnly}
          onFocus={onFocus}
          onChange={(event) => {
            setDraft(event.target.value);
            onChange(event.target.value === "" ? null : event.target.value);
          }}
          placeholder="—"
          aria-invalid={blocking}
          className={`h-10 w-full min-w-0 text-base font-semibold text-ink placeholder:font-normal placeholder:text-ink-faint ${valueFace} ${inputChrome}`}
        />
        {kind === "verified" ? (
          <button
            type="button"
            onClick={() => setUnlocked((open) => !open)}
            title={unlocked ? t.provenance.verified : t.provenance.readOnlyHint}
            aria-label={t.provenance.unlock}
            aria-pressed={unlocked}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[9px] text-ink-faint transition-colors hover:bg-surface-hover hover:text-ink"
          >
            {unlocked ? <LockOpen size={15} /> : <Lock size={15} />}
          </button>
        ) : null}
      </div>

      {mismatch ? (
        <MismatchComparison
          xmlValue={field.value_extracted}
          modelValue={extractModelValue(mismatch)}
          t={t}
        />
      ) : null}

      {failures.length > 0 ? (
        <ul className="mt-3 space-y-1.5 border-t border-line pt-3">
          {failures.map((finding) => (
            <li
              key={finding.id}
              className={`flex gap-2 text-[12px] leading-5 ${
                finding.severity === "error" ? "text-danger" : "text-warning"
              }`}
            >
              <TriangleAlert size={14} className="mt-0.5 shrink-0" aria-hidden />
              <span>
                <span dir="ltr" className="me-1.5 font-mono text-[11px] opacity-70">
                  {finding.rule_code}
                </span>
                {(isArabic ? finding.message_ar : finding.message_en) ??
                  finding.message_en ??
                  finding.message_ar}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </li>
  );
}

/**
 * The model's reading, pulled out of the mismatch message.
 *
 * The backend composes that sentence; parsing it here is a seam, not a
 * long-term answer. When the API returns the shadow value as its own field this
 * becomes a property read.
 */
function extractModelValue(finding: ValidationFinding): string | null {
  const source = finding.message_en ?? "";
  const match = source.match(/model read '([^']*)'/);
  return match ? match[1] : null;
}
