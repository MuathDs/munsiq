import { Loader2 } from "lucide-react";

import { interpolate, type Messages } from "@/lib/messages";

/**
 * Batch progress: files finished out of files chosen.
 *
 * The prototype averaged per-job progress numbers that were themselves a guess
 * (tokens received over a hard-coded ceiling). This counts something real — how
 * many files have a result — so the bar can only move when something happened.
 */
export function ProcessingBanner({
  total,
  complete,
  t,
}: {
  total: number;
  complete: number;
  t: Messages;
}) {
  if (total === 0 || complete >= total) return null;

  return (
    <div
      role="status"
      className="flex items-center gap-4 rounded-[14px] border border-line bg-surface px-5 py-4"
    >
      <Loader2 size={18} className="shrink-0 animate-spin text-accent" aria-hidden />
      <p className="tabular whitespace-nowrap text-[13px] font-semibold text-ink">
        {interpolate(t.upload.batch, { done: complete, total })}
      </p>
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-line">
        <div
          className="h-full bg-accent transition-[width] duration-300"
          style={{ inlineSize: `${(complete / total) * 100}%` }}
        />
      </div>
    </div>
  );
}
