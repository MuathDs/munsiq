"use client";

/**
 * THE core differentiator of this product.
 *
 * Every generic invoice OCR tool shows you a value. This shows you where the
 * value came from, and how much that origin is worth trusting:
 *
 *   GREEN  موثّق (XML)   — read from the UBL attachment the supplier
 *                          cryptographically signed and filed with ZATCA.
 *                          Not a prediction. Read-only by default.
 *   AMBER  مستخرج (AI)   — a model read it off the page. Advisory, shown with
 *                          its confidence.
 *   RED    تعارض          — the signed XML and the model disagree. The XML
 *                          wins; the reviewer must resolve it before confirming.
 *
 * The distinction is the whole argument for this architecture: a compliant
 * Saudi invoice already contains its own answer, and a system that knows the
 * difference between reading and guessing is not the same product as one that
 * guesses everything.
 */

import { Bot, ShieldCheck, TriangleAlert, UserPen } from "lucide-react";

import type { FieldSource } from "@/lib/api/types";
import type { Messages } from "@/lib/messages";

export type ProvenanceKind = "verified" | "extracted" | "mismatch" | "human" | "absent";

export function provenanceOf(
  source: FieldSource | null,
  hasMismatch: boolean,
): ProvenanceKind {
  // A mismatch outranks everything: the field has a signed value AND a
  // conflicting reading, which is more urgent than either alone.
  if (hasMismatch) return "mismatch";
  if (source === "ubl_xml") return "verified";
  if (source === "human") return "human";
  if (source === "vlm") return "extracted";
  return "absent";
}

const STYLES: Record<ProvenanceKind, string> = {
  verified: "bg-success-soft text-success border-success/30",
  extracted: "bg-warning-soft text-warning border-warning/30",
  mismatch: "bg-danger-soft text-danger border-danger/40",
  human: "bg-accent/15 text-accent-strong border-accent/30",
  absent: "bg-line text-ink-faint border-line-strong",
};

const ICONS: Record<ProvenanceKind, typeof ShieldCheck> = {
  verified: ShieldCheck,
  extracted: Bot,
  mismatch: TriangleAlert,
  human: UserPen,
  absent: Bot,
};

function labelFor(kind: ProvenanceKind, t: Messages): string {
  switch (kind) {
    case "verified":
      return t.provenance.verified;
    case "extracted":
      return t.provenance.extracted;
    case "mismatch":
      return t.provenance.mismatch;
    case "human":
      return t.provenance.human;
    case "absent":
      return t.provenance.ocrRule;
  }
}

function tooltipFor(kind: ProvenanceKind, t: Messages): string {
  switch (kind) {
    case "verified":
      return t.provenance.verifiedTooltip;
    case "extracted":
      return t.provenance.extractedTooltip;
    case "mismatch":
      return t.provenance.mismatchTooltip;
    case "human":
      return t.provenance.humanTooltip;
    case "absent":
      return t.provenance.ocrRuleTooltip;
  }
}

export function ProvenanceBadge({
  kind,
  t,
  confidence,
}: {
  kind: ProvenanceKind;
  t: Messages;
  confidence?: number | null;
}) {
  const Icon = ICONS[kind];
  const label = labelFor(kind, t);

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-semibold ${STYLES[kind]}`}
      title={tooltipFor(kind, t)}
    >
      <Icon size={12} aria-hidden />
      <span>{label}</span>
      {kind === "extracted" && typeof confidence === "number" ? (
        <ConfidenceBar value={confidence} t={t} />
      ) : null}
    </span>
  );
}

/**
 * A model's confidence, shown as a bar rather than a number.
 *
 * Precision would be false comfort — "0.9312" implies a calibration this value
 * does not have. A bar communicates "high / middling / low", which is all a
 * reviewer should act on.
 */
function ConfidenceBar({ value, t }: { value: number; t: Messages }) {
  const pct = Math.round(Math.max(0, Math.min(1, value)) * 100);
  return (
    <span
      className="inline-flex items-center gap-1"
      title={`${t.provenance.confidence}: ${pct}%`}
      aria-label={`${t.provenance.confidence}: ${pct}%`}
    >
      <span className="block h-1 w-8 rounded-full bg-current/25">
        <span
          className="block h-full rounded-full bg-current"
          style={{ inlineSize: `${pct}%` }}
        />
      </span>
    </span>
  );
}

/**
 * Both readings, side by side, when the signed XML and the model disagree.
 *
 * Shown rather than silently resolved: the reviewer is the one who decides
 * whether the PDF a human reads and the XML a machine files actually describe
 * the same invoice. The XML side is marked authoritative because it is what was
 * signed and filed — but the disagreement itself is the finding.
 */
export function MismatchComparison({
  xmlValue,
  modelValue,
  t,
}: {
  xmlValue: string | null;
  modelValue: string | null;
  t: Messages;
}) {
  return (
    <div className="mt-2 grid grid-cols-2 gap-2 rounded-lg border border-danger/30 bg-danger-soft p-2">
      <div>
        <div className="flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wide text-success">
          <ShieldCheck size={11} aria-hidden />
          {t.provenance.signedXml}
        </div>
        <div className="tabular mt-1 break-words text-sm font-semibold text-ink">
          {xmlValue ?? "—"}
        </div>
      </div>
      <div className="border-s border-danger/25 ps-2">
        <div className="flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wide text-warning">
          <Bot size={11} aria-hidden />
          {t.provenance.modelRead}
        </div>
        <div className="tabular mt-1 break-words text-sm text-ink-soft line-through decoration-danger/60">
          {modelValue ?? "—"}
        </div>
      </div>
    </div>
  );
}
