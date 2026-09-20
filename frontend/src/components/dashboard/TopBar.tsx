import type { ReactNode } from "react";

/**
 * The page heading. The prototype's version carried a notification bell with a
 * permanent green dot and a "JD" avatar — neither was connected to anything, and
 * an indicator that always says "something happened" is worse than none.
 */
export function TopBar({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-6">
      <div className="min-w-0">
        <h1 className="text-[28px] font-bold tracking-tight text-ink">{title}</h1>
        {subtitle ? <p className="mt-1 max-w-xl text-sm text-ink-soft">{subtitle}</p> : null}
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-3">{actions}</div> : null}
    </div>
  );
}
