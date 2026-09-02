import { Check, AlertTriangle, Loader2 } from "lucide-react";
import type { InvoiceJob } from "@/lib/types";

export function StatusBadge({ job }: { job: InvoiceJob }) {
  if (job.status === "processing") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-line text-ink-soft text-xs font-medium px-3 py-1">
        <Loader2 size={12} className="animate-spin" />
        Processing
      </span>
    );
  }

  if (job.status === "error" || job.needsReview) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-warning/15 text-warning text-xs font-medium px-3 py-1">
        <AlertTriangle size={12} />
        Needs review
      </span>
    );
  }

  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-success/15 text-success text-xs font-medium px-3 py-1">
      <Check size={12} />
      Extracted
    </span>
  );
}
