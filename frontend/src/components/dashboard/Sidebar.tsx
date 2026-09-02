import {
  LayoutDashboard,
  UploadCloud,
  History,
  FileText,
  Settings,
  ChevronRight,
} from "lucide-react";

const NAV_ITEMS = [
  { label: "Dashboard", icon: LayoutDashboard, active: false },
  { label: "Batch Upload", icon: UploadCloud, active: true },
  { label: "History", icon: History, active: false },
  { label: "Templates", icon: FileText, active: false },
  { label: "Settings", icon: Settings, active: false },
];

export function Sidebar() {
  return (
    <aside className="w-[264px] shrink-0 sticky top-0 h-screen flex flex-col gap-6 border-r border-line bg-sidebar py-[22px] px-[14px]">
      <div className="flex items-center gap-3 pb-6 border-b border-line">
        <div className="w-[34px] h-[34px] rounded-[9px] bg-accent flex items-center justify-center text-white font-bold text-base shrink-0">
          M
        </div>
        <div>
          <p className="text-base font-bold tracking-tight text-ink leading-none">Munsiq</p>
          <p className="text-[11px] text-ink-faint mt-1">AI Invoice Extraction</p>
        </div>
      </div>

      <nav className="flex flex-col gap-3 text-sm">
        {NAV_ITEMS.map(({ label, icon: Icon, active }) => (
          <div
            key={label}
            className={`flex items-center gap-3 rounded-[10px] px-3 py-[10px] ${
              active ? "bg-accent/14 text-ink font-semibold" : "text-ink-soft font-medium"
            }`}
          >
            <Icon size={16} className={active ? "text-accent-strong" : ""} />
            {label}
          </div>
        ))}
      </nav>

      <div className="mt-auto flex items-center gap-3 rounded-[10px] border border-line bg-surface p-3">
        <div className="w-8 h-8 rounded-full bg-avatar flex items-center justify-center text-xs font-semibold text-ink shrink-0">
          JD
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-[13px] font-semibold text-ink leading-none">Jordan Diaz</p>
          <p className="text-[11px] text-ink-soft mt-1">Finance Ops</p>
        </div>
        <ChevronRight size={16} className="text-ink-faint shrink-0" />
      </div>
    </aside>
  );
}
