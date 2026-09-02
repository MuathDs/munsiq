import { Bell } from "lucide-react";

export function TopBar() {
  return (
    <div className="flex items-center justify-between gap-6">
      <div>
        <h1 className="text-[28px] font-bold tracking-tight text-ink">Batch Processing</h1>
        <p className="text-sm text-ink-soft mt-1 max-w-xl">
          Upload invoices and let Munsiq&apos;s extraction model turn them into structured,
          exportable data in seconds.
        </p>
      </div>
      <div className="flex items-center gap-3 shrink-0">
        <button className="relative w-[38px] h-[38px] rounded-[9px] border border-line bg-surface flex items-center justify-center">
          <Bell size={17} className="text-ink-soft" />
          <span className="absolute top-1.5 right-1.5 w-1.5 h-1.5 rounded-full bg-success" />
        </button>
        <div className="w-[38px] h-[38px] rounded-full bg-avatar flex items-center justify-center text-xs font-semibold text-ink">
          JD
        </div>
      </div>
    </div>
  );
}
