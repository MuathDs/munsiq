"use client";

/**
 * Why this document cannot be confirmed, pinned where it cannot be missed.
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
  onJump,
}: {
  findings: ValidationFinding[];
  isArabic: boolean;
  t: Messages;
  onJump: (fieldKey: string) => void;
}) {
  const blocking = findings.filter((f) => f.severity === "error" && !f.passed);
  if (blocking.length === 0) return null;

  return (
    <section
      aria-live="polite"
      className="border-b border-danger/30 bg-danger-soft px-3 py-2.5"
    >
      <header className="flex items-center gap-2">
        <TriangleAlert size={14} className="text-danger" aria-hidden />
        <h2 className="text-xs font-semibold text-danger">
          {blocking.length === 1
            ? t.blockers.countOne
            : interpolate(t.blockers.countMany, { count: blocking.length })}
        </h2>
        <span className="ms-auto hidden text-[10px] text-danger/70 sm:block">
          {t.blockers.jumpHint}
        </span>
      </header>

      <ul className="mt-2 space-y-1.5">
        {blocking.map((finding) => (
          <li key={`${finding.rule_code}-${finding.field_key ?? ""}`}>
            <button
              type="button"
              disabled={!finding.field_key}
              onClick={() => finding.field_key && onJump(finding.field_key)}
              className="w-full rounded-md border border-danger/25 bg-bg/40 px-2 py-1.5 text-start hover:bg-bg/70 disabled:cursor-default"
            >
              <div className="flex items-center gap-2">
                <code className="rounded bg-danger/15 px-1 text-[10px] font-semibold text-danger">
                  {finding.rule_code}
                </code>
                {finding.field_key ? (
                  <span className="text-[10px] text-ink-faint">{finding.field_key}</span>
                ) : null}
              </div>
              <p className="mt-1 text-[11px] leading-snug text-ink">
                {(isArabic ? finding.message_ar : finding.message_en) ??
                  finding.message_en ??
                  finding.message_ar}
              </p>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
