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
 *   GREEN  من رمز QR     — decoded from the ZATCA QR a simplified invoice must
 *                          print: seller, VAT number, date, total, VAT. Read
 *                          deterministically, no model; the model never
 *                          overrides it, and a disagreement is a warning.
 *   AMBER  مستخرج (AI)   — a model read it off the page. Advisory, shown with
 *                          its confidence.
 *   RED    تعارض          — the signed XML and the model disagree. The XML
 *                          wins; the reviewer must resolve it before confirming.
 *   NEUTRAL محسوب         — calculated from other fields (a receipt's subtotal
 *                          as total − VAT), so printed nowhere: nothing to point
 *                          at on the page, and only as right as its inputs.
 *
 * The distinction is the whole argument for this architecture: a compliant
 * Saudi invoice already contains its own answer, and a system that knows the
 * difference between reading and guessing is not the same product as one that
 * guesses everything. So the badge is sized to be read at a glance, not
 * discovered on inspection.
 */

import {
  Bot,
  Calculator,
  CircleDashed,
  QrCode,
  ShieldCheck,
  TriangleAlert,
  UserPen,
} from "lucide-react";

import type { FieldSource } from "@/lib/api/types";
import type { Messages } from "@/lib/messages";

export type ProvenanceKind =
  | "verified"
  | "qr"
  | "extracted"
  | "mismatch"
  | "human"
  | "derived"
  | "absent";

export function provenanceOf(source: FieldSource | null, hasMismatch: boolean): ProvenanceKind {
  // A mismatch outranks everything: the field has a signed value AND a
  // conflicting reading, which is more urgent than either alone.
  if (hasMismatch) return "mismatch";
  if (source === "ubl_xml") return "verified";
  if (source === "qr") return "qr";
  if (source === "human") return "human";
  if (source === "vlm") return "extracted";
  if (source === "computed") return "derived";
  return "absent";
}

const STYLES: Record<ProvenanceKind, string> = {
  verified: "border-success/40 bg-success-soft text-success",
  qr: "border-success/40 bg-success-soft text-success",
  extracted: "border-warning/40 bg-warning-soft text-warning",
  mismatch: "border-danger/50 bg-danger-soft text-danger",
  human: "border-accent/40 bg-accent/15 text-accent-strong",
  derived: "border-line-strong bg-surface-hover text-ink",
  absent: "border-line-strong bg-line text-ink-soft",
};

const SIZES = {
  sm: "h-6 gap-1 px-2 text-[11px]",
  md: "h-7 gap-1.5 px-2.5 text-[12px]",
} as const;

const ICONS: Record<ProvenanceKind, typeof ShieldCheck> = {
  verified: ShieldCheck,
  qr: QrCode,
  extracted: Bot,
  mismatch: TriangleAlert,
  human: UserPen,
  derived: Calculator,
  absent: CircleDashed,
};

export function provenanceLabel(kind: ProvenanceKind, t: Messages): string {
  switch (kind) {
    case "verified":
      return t.provenance.verified;
    case "qr":
      return t.provenance.qr;
    case "extracted":
      return t.provenance.extracted;
    case "mismatch":
      return t.provenance.mismatch;
    case "human":
      return t.provenance.human;
    case "derived":
      return t.provenance.derived;
    case "absent":
      return t.provenance.ocrRule;
  }
}

function tooltipFor(kind: ProvenanceKind, t: Messages): string {
  switch (kind) {
    case "verified":
      return t.provenance.verifiedTooltip;
    case "qr":
      return t.provenance.qrTooltip;
    case "extracted":
      return t.provenance.extractedTooltip;
    case "mismatch":
      return t.provenance.mismatchTooltip;
    case "human":
      return t.provenance.humanTooltip;
    case "derived":
      return t.provenance.derivedTooltip;
    case "absent":
      return t.provenance.ocrRuleTooltip;
  }
}

/** Decimal arrives as a string over JSON; a bar needs a number. */
function toConfidence(value: number | string | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function ProvenanceBadge({
  kind,
  t,
  confidence,
  size = "md",
}: {
  kind: ProvenanceKind;
  t: Messages;
  confidence?: number | string | null;
  size?: keyof typeof SIZES;
}) {
  const Icon = ICONS[kind];
  const value = toConfidence(confidence);

  return (
    <span
      className={`inline-flex shrink-0 items-center whitespace-nowrap rounded-full border font-semibold ${SIZES[size]} ${STYLES[kind]}`}
      title={tooltipFor(kind, t)}
    >
      <Icon size={size === "sm" ? 12 : 14} strokeWidth={2.25} aria-hidden />
      <span>{provenanceLabel(kind, t)}</span>
      {kind === "extracted" && value !== null && size === "md" ? (
        <ConfidenceBar value={value} t={t} />
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
      className="ms-0.5 inline-flex items-center"
      title={`${t.provenance.confidence}: ${pct}%`}
      aria-label={`${t.provenance.confidence}: ${pct}%`}
    >
      <span className="block h-1.5 w-10 overflow-hidden rounded-full bg-current/25">
        <span className="block h-full rounded-full bg-current" style={{ inlineSize: `${pct}%` }} />
      </span>
    </span>
  );
}

/**
 * Both readings, side by side, when the signed XML — or the ZATCA QR — and the
 * model disagree.
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
  authority = "xml",
}: {
  xmlValue: string | null;
  modelValue: string | null;
  t: Messages;
  authority?: "xml" | "qr";
}) {
  const AuthorityIcon = authority === "qr" ? QrCode : ShieldCheck;
  return (
    <div className="mt-3 grid grid-cols-2 gap-2">
      <div className="rounded-[9px] border border-success/35 bg-success-soft px-3 py-2.5">
        <div className="flex items-center gap-1.5 text-[11px] font-semibold text-success">
          <AuthorityIcon size={12} aria-hidden />
          {authority === "qr" ? t.provenance.qrCode : t.provenance.signedXml}
        </div>
        <div className="tabular mt-1 break-words font-mono text-[15px] font-semibold text-ink">
          {xmlValue ?? "—"}
        </div>
      </div>
      <div className="rounded-[9px] border border-danger/30 bg-bg/40 px-3 py-2.5">
        <div className="flex items-center gap-1.5 text-[11px] font-semibold text-warning">
          <Bot size={12} aria-hidden />
          {t.provenance.modelRead}
        </div>
        <div className="tabular mt-1 break-words font-mono text-[15px] text-ink-soft line-through decoration-danger/70">
          {modelValue ?? "—"}
        </div>
      </div>
    </div>
  );
}
