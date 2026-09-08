"use client";

/**
 * The compliance strip.
 *
 * Four indicators a Saudi AP clerk actually cares about, read from the rule
 * results rather than recomputed here. The rules are the single source of
 * truth for whether this invoice is compliant; the UI only renders their verdict.
 */

import { CircleCheck, CircleHelp, CircleX, FileCode2 } from "lucide-react";

import type { ValidationFinding } from "@/lib/api/types";
import type { Messages } from "@/lib/messages";

type Verdict = "ok" | "bad" | "unknown";

function verdictFor(findings: ValidationFinding[], code: string): Verdict {
  const hit = findings.find((f) => f.rule_code === code);
  // A rule that never ran is 'unknown', not 'ok'. Showing a green tick for a
  // check that was never performed is exactly the kind of false assurance this
  // panel exists to avoid.
  if (!hit) return "unknown";
  return hit.passed ? "ok" : "bad";
}

export function ZatcaPanel({
  hasEmbeddedUbl,
  findings,
  modelVersion,
  t,
}: {
  hasEmbeddedUbl: boolean;
  findings: ValidationFinding[];
  modelVersion: string | null;
  t: Messages;
}) {
  return (
    <section
      aria-label={t.zatca.title}
      className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line bg-sidebar px-3 py-2"
    >
      <h2 className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
        <FileCode2 size={13} />
        {t.zatca.title}
      </h2>

      <Indicator
        label={t.zatca.embeddedUbl}
        verdict={hasEmbeddedUbl ? "ok" : "unknown"}
        value={hasEmbeddedUbl ? t.zatca.embeddedUblYes : t.zatca.embeddedUblNo}
      />
      <Indicator
        label={t.zatca.qr}
        verdict={verdictFor(findings, "QR_TOTAL_MATCH")}
        value={qrLabel(verdictFor(findings, "QR_TOTAL_MATCH"), t)}
      />
      <Indicator
        label={t.zatca.trn}
        verdict={verdictFor(findings, "TRN_CHECKSUM")}
        value={trnLabel(verdictFor(findings, "TRN_CHECKSUM"), t)}
      />
      <Indicator
        label={t.zatca.vatCategory}
        verdict={verdictFor(findings, "VAT_CATEGORY_VALID")}
        value={
          verdictFor(findings, "VAT_CATEGORY_VALID") === "unknown"
            ? t.zatca.unknown
            : verdictFor(findings, "VAT_CATEGORY_VALID") === "ok"
              ? "S / Z / E / O"
              : t.zatca.unknown
        }
      />

      <div className="ms-auto text-[11px] text-ink-faint">
        {modelVersion ? (
          <span className="tabular">
            {t.zatca.modelVersion}: {modelVersion}
          </span>
        ) : (
          // No model version means Step Zero answered from the signed XML and
          // the model was never called — worth saying out loud, it is the
          // product's whole economic argument.
          <span className="text-success">{t.zatca.noModel}</span>
        )}
      </div>
    </section>
  );
}

function qrLabel(verdict: Verdict, t: Messages): string {
  if (verdict === "ok") return t.zatca.qrMatch;
  if (verdict === "bad") return t.zatca.qrMismatch;
  return t.zatca.qrAbsent;
}

function trnLabel(verdict: Verdict, t: Messages): string {
  if (verdict === "ok") return t.zatca.trnValid;
  if (verdict === "bad") return t.zatca.trnInvalid;
  return t.zatca.unknown;
}

const TONE: Record<Verdict, string> = {
  ok: "text-success",
  bad: "text-danger",
  unknown: "text-ink-faint",
};

function Indicator({
  label,
  verdict,
  value,
}: {
  label: string;
  verdict: Verdict;
  value: string;
}) {
  const Icon = verdict === "ok" ? CircleCheck : verdict === "bad" ? CircleX : CircleHelp;
  return (
    <div className="flex items-center gap-1.5">
      <Icon size={13} className={TONE[verdict]} aria-hidden />
      <span className="text-[11px] text-ink-soft">{label}</span>
      <span className={`text-[11px] font-medium ${TONE[verdict]}`}>{value}</span>
    </div>
  );
}
