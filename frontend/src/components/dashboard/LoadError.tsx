import { CircleAlert } from "lucide-react";

import type { Messages } from "@/lib/messages";

/** A page that could not load its data says so, and says what to check. */
export function LoadError({ t, detail }: { t: Messages; detail: string }) {
  return (
    <div
      role="alert"
      className="flex items-start gap-3 rounded-[14px] border border-danger/40 bg-danger-soft p-5"
    >
      <CircleAlert size={18} className="mt-0.5 shrink-0 text-danger" aria-hidden />
      <div className="min-w-0">
        <p className="text-sm font-semibold text-danger">{t.dashboard.loadFailed}</p>
        <p className="mt-1 text-[13px] text-ink-soft">{t.dashboard.loadFailedHint}</p>
        <p className="mt-2 break-words font-mono text-[11px] text-ink-faint" dir="ltr">
          {detail}
        </p>
      </div>
    </div>
  );
}
