"use client";

/**
 * Three-tier triage.
 *
 * A reviewer's attention is the scarce resource, so the list is ordered by what
 * actually needs a decision:
 *
 *   BLOCKING          pinned to the top, always expanded, must be resolved
 *   REVIEW_SUGGESTED  expanded, worth a glance
 *   AUTO_VALIDATED    collapsed behind a disclosure — thirty green ticks are
 *                     noise, and scrolling past them to reach the one red field
 *                     is the failure mode this ordering prevents
 */

import { ChevronDown, ChevronRight, CircleCheck, Eye, TriangleAlert } from "lucide-react";
import { useState } from "react";

import { fieldKeyOf, type ExtractedField, type ValidationFinding } from "@/lib/api/types";
import { interpolate, type Messages } from "@/lib/messages";

import { FieldRow } from "./FieldRow";

interface Props {
  fields: ExtractedField[];
  findings: ValidationFinding[];
  focusedKey: string | null;
  t: Messages;
  isArabic: boolean;
  onFocus: (key: string) => void;
  onHover: (key: string | null) => void;
  onChange: (field: ExtractedField, value: string | null) => void;
}

function tierOf(field: ExtractedField): "blocking" | "review" | "validated" {
  if (field.validation_state === "blocking") return "blocking";
  if (field.validation_state === "auto_validated") return "validated";
  return "review";
}

export function FieldPane({
  fields,
  findings,
  focusedKey,
  t,
  isArabic,
  onFocus,
  onHover,
  onChange,
}: Props) {
  const [showValidated, setShowValidated] = useState(false);

  const blocking = fields.filter((f) => tierOf(f) === "blocking");
  const review = fields.filter((f) => tierOf(f) === "review");
  const validated = fields.filter((f) => tierOf(f) === "validated");

  const findingsFor = (field: ExtractedField) =>
    findings.filter((f) => f.field_key === field.field_key);

  const renderRows = (rows: ExtractedField[]) =>
    rows.map((field) => {
      const key = fieldKeyOf(field);
      return (
        <FieldRow
          key={key}
          field={field}
          findings={findingsFor(field)}
          focused={focusedKey === key}
          t={t}
          isArabic={isArabic}
          onFocus={() => onFocus(key)}
          onHover={(hovering) => onHover(hovering ? key : null)}
          onChange={(value) => onChange(field, value)}
        />
      );
    });

  return (
    <div className="flex h-full flex-col overflow-y-auto">
      {blocking.length > 0 ? (
        <Tier
          tone="danger"
          icon={<TriangleAlert size={13} />}
          title={t.tiers.blocking}
          hint={t.tiers.blockingHint}
          count={blocking.length}
        >
          <ul className="divide-y divide-line">{renderRows(blocking)}</ul>
        </Tier>
      ) : null}

      {review.length > 0 ? (
        <Tier
          tone="warning"
          icon={<Eye size={13} />}
          title={t.tiers.review}
          hint={t.tiers.reviewHint}
          count={review.length}
        >
          <ul className="divide-y divide-line">{renderRows(review)}</ul>
        </Tier>
      ) : null}

      {validated.length > 0 ? (
        <div className="border-t border-line">
          <button
            type="button"
            onClick={() => setShowValidated((open) => !open)}
            aria-expanded={showValidated}
            className="flex w-full items-center gap-2 px-3 py-2.5 text-start text-xs font-medium text-success hover:bg-surface-hover"
          >
            {showValidated ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            <CircleCheck size={13} />
            <span className="tabular">
              {interpolate(t.tiers.validatedCount, { count: validated.length })}
            </span>
          </button>
          {showValidated ? (
            <ul className="divide-y divide-line">{renderRows(validated)}</ul>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function Tier({
  tone,
  icon,
  title,
  hint,
  count,
  children,
}: {
  tone: "danger" | "warning";
  icon: React.ReactNode;
  title: string;
  hint: string;
  count: number;
  children: React.ReactNode;
}) {
  const toneClass =
    tone === "danger" ? "text-danger bg-danger-soft" : "text-warning bg-warning-soft";
  return (
    <section className="border-b border-line">
      <header className={`flex items-center gap-2 px-3 py-2 ${toneClass}`}>
        {icon}
        <h3 className="text-xs font-semibold">{title}</h3>
        <span className="tabular rounded-full bg-current/15 px-1.5 text-[10px] font-bold">
          {count}
        </span>
        <span className="ms-auto hidden text-[10px] opacity-80 sm:block">{hint}</span>
      </header>
      {children}
    </section>
  );
}
