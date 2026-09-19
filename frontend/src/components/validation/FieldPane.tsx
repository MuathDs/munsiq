"use client";

/**
 * The field pane.
 *
 * One entry point per region. Here it is the provenance summary at the top: a
 * single bar that says, before any row is read, how much of this document came
 * from the signed XML and how much from a model. Everything below it is triage:
 *
 *   BLOCKERS          the red card, when there is one — nothing else matters
 *                     until it is resolved
 *   BLOCKING fields   pinned first
 *   NEEDS REVIEW      next
 *   AUTO-VALIDATED    last, and EXPANDED by default. Collapsing it made a
 *                     compliant invoice look like an empty screen; ordering,
 *                     not hiding, is what keeps the one red field on top.
 */

import { ChevronDown, ShieldCheck } from "lucide-react";
import { useState } from "react";

import {
  fieldKeyOf,
  type ExtractedField,
  type SchemaField,
  type ValidationFinding,
} from "@/lib/api/types";
import { interpolate, type Messages } from "@/lib/messages";

import { FieldRow } from "./FieldRow";
import { isNumericLike, isRequired, kindOf, labelFor, tierOf } from "./fieldModel";
import { ProvenanceBadge, type ProvenanceKind } from "./ProvenanceBadge";

interface Props {
  /** Already ordered by `orderFields` — the same order the keyboard walks. */
  fields: ExtractedField[];
  schemaFields: SchemaField[];
  findings: ValidationFinding[];
  focusedKey: string | null;
  t: Messages;
  isArabic: boolean;
  onFocus: (key: string) => void;
  onHover: (key: string | null) => void;
  onChange: (field: ExtractedField, value: string | null) => void;
  /** Rendered above the tiers: the blocker card. */
  children?: React.ReactNode;
}

export function FieldPane({
  fields,
  schemaFields,
  findings,
  focusedKey,
  t,
  isArabic,
  onFocus,
  onHover,
  onChange,
  children,
}: Props) {
  const [showValidated, setShowValidated] = useState(true);

  const blocking = fields.filter((f) => tierOf(f) === "blocking");
  const review = fields.filter((f) => tierOf(f) === "review");
  const validated = fields.filter((f) => tierOf(f) === "validated");

  const renderRows = (rows: ExtractedField[]) => (
    <ul className="space-y-2.5">
      {rows.map((field) => {
        const key = fieldKeyOf(field);
        return (
          <FieldRow
            key={key}
            field={field}
            label={labelFor(field.field_key, schemaFields, isArabic)}
            required={isRequired(field.field_key, schemaFields)}
            numeric={isNumericLike(field, schemaFields)}
            findings={findings.filter((f) => f.field_key === field.field_key)}
            focused={focusedKey === key}
            t={t}
            isArabic={isArabic}
            onFocus={() => onFocus(key)}
            onHover={(hovering) => onHover(hovering ? key : null)}
            onChange={(value) => onChange(field, value)}
          />
        );
      })}
    </ul>
  );

  return (
    <div className="flex h-full flex-col bg-bg">
      <PaneHeader fields={fields} findings={findings} t={t} />

      <div className="pane-scroll min-h-0 flex-1 overflow-y-auto">
        <div className="space-y-6 px-6 pb-10 pt-5">
          {children}

          {blocking.length > 0 ? (
            <TierSection
              tone="danger"
              title={t.tiers.blocking}
              hint={t.tiers.blockingHint}
              count={blocking.length}
            >
              {renderRows(blocking)}
            </TierSection>
          ) : null}

          {review.length > 0 ? (
            <TierSection
              tone="warning"
              title={t.tiers.review}
              hint={t.tiers.reviewHint}
              count={review.length}
            >
              {renderRows(review)}
            </TierSection>
          ) : null}

          {validated.length > 0 ? (
            <TierSection
              tone="success"
              title={t.tiers.validated}
              count={validated.length}
              action={
                <button
                  type="button"
                  onClick={() => setShowValidated((open) => !open)}
                  aria-expanded={showValidated}
                  className="flex h-7 items-center gap-1 rounded-[9px] px-2 text-[12px] font-medium text-ink-soft transition-colors hover:bg-surface-hover hover:text-ink"
                >
                  {showValidated ? t.tiers.hide : t.tiers.show}
                  <ChevronDown
                    size={14}
                    className={`transition-transform ${showValidated ? "" : "-rotate-90 rtl:rotate-90"}`}
                  />
                </button>
              }
            >
              {showValidated ? (
                renderRows(validated)
              ) : (
                <button
                  type="button"
                  onClick={() => setShowValidated(true)}
                  className="flex w-full items-center gap-3 rounded-[10px] border border-dashed border-success/35 bg-success-soft px-4 py-3.5 text-start transition-colors hover:border-success/60"
                >
                  <ShieldCheck size={16} className="shrink-0 text-success" aria-hidden />
                  <span className="text-[13px] text-ink-soft">
                    {interpolate(t.tiers.collapsedSummary, { count: validated.length })}
                  </span>
                  <span className="ms-auto text-[12px] font-semibold text-success">
                    {t.tiers.show}
                  </span>
                </button>
              )}
            </TierSection>
          ) : null}
        </div>
      </div>
    </div>
  );
}

const SUMMARY_ORDER: ProvenanceKind[] = ["verified", "extracted", "human", "mismatch", "absent"];

const SEGMENT: Record<ProvenanceKind, string> = {
  verified: "bg-success",
  extracted: "bg-warning",
  human: "bg-accent-strong",
  mismatch: "bg-danger",
  absent: "bg-ink-faint/60",
};

/**
 * Provenance at a glance: one proportional bar and a legend of the same badges
 * the rows use. The badge vocabulary is introduced here, once, so every row
 * below reads as "one of these".
 */
function PaneHeader({
  fields,
  findings,
  t,
}: {
  fields: ExtractedField[];
  findings: ValidationFinding[];
  t: Messages;
}) {
  const counts: Record<ProvenanceKind, number> = {
    verified: 0,
    extracted: 0,
    human: 0,
    mismatch: 0,
    absent: 0,
  };
  for (const field of fields) counts[kindOf(field, findings)] += 1;
  const present = SUMMARY_ORDER.filter((kind) => counts[kind] > 0);

  return (
    <div className="shrink-0 border-b border-line px-6 pb-4 pt-5">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-base font-semibold text-ink">{t.workspace.fields}</h2>
        <span className="tabular font-mono text-[12px] text-ink-faint">{fields.length}</span>
      </div>

      <div className="mt-3 flex h-2 gap-0.5 overflow-hidden rounded-full bg-line" aria-hidden>
        {present.map((kind) => (
          <span
            key={kind}
            className={`${SEGMENT[kind]} first:rounded-s-full last:rounded-e-full`}
            style={{ flexGrow: counts[kind], flexBasis: 0 }}
          />
        ))}
      </div>

      <ul className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2">
        {present.map((kind) => (
          <li key={kind} className="flex items-center gap-2">
            <ProvenanceBadge kind={kind} t={t} size="sm" />
            <span className="tabular font-mono text-[12px] text-ink-soft">{counts[kind]}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

const DOT = {
  danger: "bg-danger",
  warning: "bg-warning",
  success: "bg-success",
} as const;

function TierSection({
  tone,
  title,
  hint,
  count,
  action,
  children,
}: {
  tone: keyof typeof DOT;
  title: string;
  hint?: string;
  count: number;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section>
      <header className="mb-3 flex min-w-0 items-center gap-2.5">
        <span className={`h-2 w-2 shrink-0 rounded-full ${DOT[tone]}`} aria-hidden />
        <h3 className="shrink-0 text-[13px] font-semibold text-ink">{title}</h3>
        <span className="tabular shrink-0 rounded-full bg-line px-2 py-0.5 font-mono text-[11px] text-ink-soft">
          {count}
        </span>
        {hint ? <span className="min-w-0 truncate text-[12px] text-ink-faint">{hint}</span> : null}
        {action ? <div className="ms-auto shrink-0">{action}</div> : null}
      </header>
      {children}
    </section>
  );
}
