import { Loader2 } from "lucide-react";
import type { InvoiceJob } from "@/lib/types";

interface ProcessingBannerProps {
  jobs: InvoiceJob[];
}

export function ProcessingBanner({ jobs }: ProcessingBannerProps) {
  const inFlight = jobs.filter((j) => j.status === "processing");
  if (inFlight.length === 0) return null;

  const doneCount = jobs.filter((j) => j.status !== "processing").length;
  const avgProgress = inFlight.reduce((sum, j) => sum + j.progress, 0) / inFlight.length;

  return (
    <div className="rounded-[14px] border border-line bg-surface px-5 py-4 flex items-center gap-4">
      <Loader2 size={18} className="text-accent animate-spin shrink-0" />
      <p className="text-[13px] font-semibold text-ink whitespace-nowrap">
        AI Model Processing… {doneCount} of {jobs.length} complete
      </p>
      <div className="flex-1 h-1.5 rounded-full bg-line overflow-hidden">
        <div
          className="h-full bg-accent transition-[width] duration-300"
          style={{ width: `${avgProgress}%` }}
        />
      </div>
    </div>
  );
}
