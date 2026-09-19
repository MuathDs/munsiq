"use client";

/**
 * Why this document cannot be confirmed — the primary element of the field
 * pane whenever it exists, so it is the one card with a coloured surface.
 *
 * The messages come from the rules with both languages already written, so this
 * component never composes prose — it picks a side and renders it.
 */

import { TriangleAlert } from "lucide-react";

import type { ValidationFinding } from "@/lib/api/types";
import { interpolate, type Messages } from "@/lib/messages";

export function BlockerList({
  findings,
  isArabic,
  t,
  labelFor,
  onJump,
}: {
  findings: ValidationFinding[];
  isArabic: boolean;
  t: Messages;
  labelFor: (fieldKey: string) => string;
  onJump: (fieldKey: string) => void;
}) {
  const blocking = findings.filter((f) => f.severity === "error" && !f.passed);
  if (blocking.length === 0) return null;

  return (
    <section aria-live="polite" className="rounded-[14px] border border-danger/40 bg-danger-soft p-4">
      <header className="flex items-start gap-3">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[9px] bg-danger/20 text-danger">
          <TriangleAlert size={16} aria-hidden />
        </span>
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-danger">
            {blocking.length === 1
              ? t.blockers.countOne
              : interpolate(t.blockers.countMany, { count: blocking.length })}
          </h2>
          <p className="mt-0.5 text-[12px] text-danger/75">{t.tiers.blockingHint}</p>
        </div>
      </header>

      <ul className="mt-3.5 space-y-2">
        {blocking.map((finding) => (
          <li key={`${finding.rule_code}-${finding.field_key ?? ""}`}>
            <button
              type="button"
              disabled={!finding.field_key}
              onClick={() => finding.field_key && onJump(finding.field_key)}
              className="group w-full rounded-[10px] bg-bg/55 px-3.5 py-3 text-start transition-colors hover:bg-bg/85 disabled:cursor-default"
            >
              <div className="flex min-w-0 items-center gap-2">
                <code
                  dir="ltr"
                  className="shrink-0 rounded-[6px] bg-danger/15 px-1.5 py-0.5 font-mono text-[11px] font-semibold text-danger"
                >
                  {finding.rule_code}
                </code>
                {finding.field_key ? (
                  <span className="min-w-0 truncate text-[12px] text-ink-soft">
                    {labelFor(finding.field_key)}
                  </span>
                ) : null}
                {finding.field_key ? (
                  <span className="ms-auto shrink-0 text-[11px] font-medium text-ink-faint group-hover:text-ink-soft">
                    {t.blockers.openField}
                  </span>
                ) : null}
              </div>
              <p className="mt-1.5 text-[13px] leading-relaxed text-ink">
                {(isArabic ? finding.message_ar : finding.message_en) ??
                  finding.message_en ??
                  finding.message_ar}
              </p>
            </button>
          </li>
        ))}
      </ul>

      <p className="mt-3 text-[11px] text-danger/70">{t.blockers.jumpHint}</p>
    </section>
  );
}
