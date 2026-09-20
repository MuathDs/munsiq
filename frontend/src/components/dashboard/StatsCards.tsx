import { FileCheck2, Inbox, Percent, ShieldCheck, type LucideIcon } from "lucide-react";

import type { Stats } from "@/lib/api/types";
import { interpolate, type Messages } from "@/lib/messages";

/**
 * The dashboard's headline numbers, every one computed from the data.
 *
 * A card whose number cannot be computed is NOT rendered — no "—", no zero, no
 * estimate. The accuracy card needs at least one confirmed invoice; "fields read
 * from signed XML" needs at least one processed one. Until then they are simply
 * absent, because a placeholder in a number slot reads as a measurement.
 */

interface Card {
  id: string;
  icon: LucideIcon;
  label: string;
  value: string;
  caption?: string;
  tone?: "warning" | "danger";
}

function buildCards(stats: Stats, t: Messages): Card[] {
  const cards: Card[] = [
    {
      id: "processed",
      icon: Inbox,
      label: t.stats.processed,
      value: String(stats.processed),
      caption:
        stats.in_progress > 0
          ? interpolate(t.stats.processedProgress, { count: stats.in_progress })
          : stats.failed > 0
            ? interpolate(t.stats.processedFailed, { count: stats.failed })
            : undefined,
      tone: stats.in_progress === 0 && stats.failed > 0 ? "danger" : undefined,
    },
    {
      id: "awaiting",
      icon: FileCheck2,
      label: t.stats.awaiting,
      value: String(stats.awaiting_review),
      caption:
        stats.blocked > 0
          ? interpolate(t.stats.awaitingBlocked, { count: stats.blocked })
          : undefined,
      tone: stats.blocked > 0 ? "danger" : undefined,
    },
  ];

  if (stats.processed > 0) {
    cards.push({
      id: "signedXml",
      icon: ShieldCheck,
      label: t.stats.signedXml,
      value: interpolate(t.stats.signedXmlOf, {
        count: stats.from_signed_xml,
        total: stats.processed,
      }),
      caption: t.stats.signedXmlHint,
    });
  }

  const accuracy = stats.accuracy;
  if (accuracy && accuracy.fields_total > 0) {
    const kept = accuracy.fields_total - accuracy.fields_corrected;
    cards.push({
      id: "accuracy",
      icon: Percent,
      label: t.stats.accuracy,
      value: `${((kept / accuracy.fields_total) * 100).toFixed(1)}%`,
      caption: interpolate(t.stats.accuracyHint, {
        kept,
        total: accuracy.fields_total,
        invoices: accuracy.annotations,
      }),
    });
  }
  return cards;
}

export function StatsCards({ stats, t }: { stats: Stats; t: Messages }) {
  const cards = buildCards(stats, t);
  return (
    <div className="grid gap-4 [grid-template-columns:repeat(auto-fit,minmax(220px,1fr))]">
      {cards.map((card) => (
        <StatCard key={card.id} {...card} />
      ))}
    </div>
  );
}

function StatCard({ icon: Icon, label, value, caption, tone }: Omit<Card, "id">) {
  return (
    <div className="rounded-[14px] border border-line bg-surface px-[22px] py-5">
      <div className="flex items-center gap-2 text-sm text-ink-soft">
        <Icon size={15} aria-hidden />
        {label}
      </div>
      {/* Only a bare number is pinned to LTR. A composed sentence ("2 من 4")
          keeps the page direction; pinning it scrambles its Arabic words. */}
      <p
        className="tabular mt-2 font-mono text-[28px] font-bold text-ink"
        dir={/^[\d.,%]+$/.test(value) ? "ltr" : undefined}
      >
        {value}
      </p>
      {caption ? (
        <p
          className={`mt-1 text-xs ${
            tone === "danger" ? "text-danger" : tone === "warning" ? "text-warning" : "text-ink-soft"
          }`}
        >
          {caption}
        </p>
      ) : null}
    </div>
  );
}
