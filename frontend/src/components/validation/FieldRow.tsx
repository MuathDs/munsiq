"use client";

/**
 * One field: its provenance, its value, and what the rules said about it.
 *
 * A `ubl_xml` value renders read-only. It came from a cryptographically signed
 * attachment, so casually overwriting it should take a deliberate act — hence
 * the unlock affordance rather than an editable input.
 */

import { Lock, LockOpen } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import {
  currentValue,
  fieldKeyOf,
  type ExtractedField,
  type ValidationFinding,
} from "@/lib/api/types";
import type { Messages } from "@/lib/messages";

import { MismatchComparison, ProvenanceBadge, provenanceOf } from "./ProvenanceBadge";

interface Props {
  field: ExtractedField;
  findings: ValidationFinding[];
  focused: boolean;
  t: Messages;
  isArabic: boolean;
  onFocus: () => void;
  onHover: (hovering: boolean) => void;
  onChange: (value: string | null) => void;
}

const STATE_ACCENT: Record<string, string> = {
  blocking: "border-s-danger",
  review_suggested: "border-s-warning",
  auto_validated: "border-s-success/50",
};

export function FieldRow({
  field,
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

  const mismatch = findings.find(
    (f) => f.rule_code === "XML_PDF_MISMATCH" && !f.passed,
  );
  const kind = provenanceOf(field.source, Boolean(mismatch));
  const readOnly = kind === "verified" && !unlocked;
  const failures = findings.filter((f) => !f.passed);

  return (
    <li
      className={`border-s-2 bg-surface px-3 py-2.5 transition-colors ${
        STATE_ACCENT[field.validation_state ?? ""] ?? "border-s-line-strong"
      } ${focused ? "bg-surface-hover" : ""}`}
      onMouseEnter={() => onHover(true)}
      onMouseLeave={() => onHover(false)}
    >
      <div className="flex items-start justify-between gap-2">
        <label
          htmlFor={`field-${fieldKeyOf(field)}`}
          className="text-xs font-medium text-ink-soft"
        >
          {field.field_key}
          {field.row_index !== null ? (
            <span className="tabular text-ink-faint"> [{field.row_index}]</span>
          ) : null}
        </label>
        <ProvenanceBadge kind={kind} t={t} confidence={field.confidence} />
      </div>

      <div className="mt-1.5 flex items-center gap-2">
        <input
          id={`field-${fieldKeyOf(field)}`}
          ref={inputRef}
          value={draft}
          readOnly={readOnly}
          onFocus={onFocus}
          onChange={(event) => {
            setDraft(event.target.value);
            onChange(event.target.value === "" ? null : event.target.value);
          }}
          placeholder="—"
          aria-invalid={field.validation_state === "blocking"}
          className={`tabular w-full rounded-md border bg-bg px-2 py-1.5 text-sm text-ink placeholder:text-ink-faint ${
            readOnly
              ? "cursor-default border-success/25 text-success"
              : "border-line-strong focus:border-accent"
          }`}
        />
        {kind === "verified" ? (
          <button
            type="button"
            onClick={() => setUnlocked((open) => !open)}
            title={unlocked ? t.provenance.verified : t.provenance.readOnlyHint}
            aria-label={t.provenance.unlock}
            className="shrink-0 rounded-md p-1.5 text-ink-faint hover:bg-surface-hover hover:text-ink"
          >
            {unlocked ? <LockOpen size={14} /> : <Lock size={14} />}
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
        <ul className="mt-1.5 space-y-1">
          {failures.map((finding) => (
            <li
              key={finding.rule_code}
              className={`text-[11px] leading-snug ${
                finding.severity === "error" ? "text-danger" : "text-warning"
              }`}
            >
              <span className="font-mono text-[10px] opacity-70">
                {finding.rule_code}
              </span>{" "}
              {(isArabic ? finding.message_ar : finding.message_en) ??
                finding.message_en ??
                finding.message_ar}
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
