import { Inbox, Percent, Clock, type LucideIcon } from "lucide-react";

interface StatsCardsProps {
  processedCount: number;
  accuracyPct: number | null;
  hoursSaved: number;
}

export function StatsCards({ processedCount, accuracyPct, hoursSaved }: StatsCardsProps) {
  return (
    <div className="grid grid-cols-3 gap-4">
      <StatCard
        icon={Inbox}
        label="Invoices Processed"
        value={String(processedCount)}
        delta={processedCount > 0 ? `+${processedCount} this session` : undefined}
      />
      <StatCard
        icon={Percent}
        label="Extraction Accuracy"
        value={accuracyPct === null ? "—" : `${accuracyPct.toFixed(1)}%`}
        caption="This session — % of rows needing no review"
      />
      <StatCard
        icon={Clock}
        label="Time Saved"
        value={`${hoursSaved.toFixed(1)} hrs`}
        caption="Est. vs. manual entry (~3 min/doc)"
      />
    </div>
  );
}

function StatCard({
  icon: Icon,
  label,
  value,
  delta,
  caption,
}: {
  icon: LucideIcon;
  label: string;
  value: string;
  delta?: string;
  caption?: string;
}) {
  return (
    <div className="rounded-[14px] border border-line bg-surface px-[22px] py-5">
      <div className="flex items-center gap-2 text-ink-soft text-sm">
        <Icon size={15} />
        {label}
      </div>
      <p className="font-mono text-[28px] font-bold text-ink mt-2">{value}</p>
      {delta && <p className="text-xs text-success mt-1">{delta}</p>}
      {caption && <p className="text-xs text-ink-soft mt-1">{caption}</p>}
    </div>
  );
}
