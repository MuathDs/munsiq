"use client";

import { FileText, History, Languages, LayoutDashboard, Settings, UploadCloud } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import type { Org } from "@/lib/api/types";
import { initialsOf } from "@/lib/format";
import { LOCALE_LABEL, otherLocale, type Locale } from "@/lib/i18n";
import type { Messages } from "@/lib/messages";

/**
 * The app shell's navigation.
 *
 * Every item is a real route. The prototype listed five entries and wired one, so
 * four were decoration; here each opens a page that reads real data. The card at
 * the bottom is the real organization the BFF is acting for — the prototype's
 * hard-coded "Jordan Diaz · Finance Ops" is gone.
 *
 * RTL: the sidebar is first in the flex row, so `dir="rtl"` puts it on the right
 * without a single locale branch. Borders and spacing are logical properties.
 */

const NAV = [
  { key: "dashboard", segment: "dashboard", icon: LayoutDashboard },
  { key: "upload", segment: "upload", icon: UploadCloud },
  { key: "history", segment: "history", icon: History },
  { key: "templates", segment: "templates", icon: FileText },
  { key: "settings", segment: "settings", icon: Settings },
] as const;

export function Sidebar({ locale, t, org }: { locale: Locale; t: Messages; org: Org | null }) {
  const pathname = usePathname();
  const next = otherLocale(locale);
  // The same page in the other language: swap the leading locale segment.
  const otherHref = pathname.replace(/^\/(ar|en)(?=\/|$)/, `/${next}`);

  return (
    <aside className="sticky top-0 flex h-dvh w-[264px] shrink-0 flex-col gap-6 border-e border-line bg-sidebar px-[14px] py-[22px]">
      <div className="flex items-center gap-3 border-b border-line pb-6">
        <div className="flex h-[34px] w-[34px] shrink-0 items-center justify-center rounded-[9px] bg-accent text-base font-bold text-white">
          {locale === "ar" ? "م" : "M"}
        </div>
        <div className="min-w-0">
          <p className="text-base font-bold leading-none tracking-tight text-ink">{t.appName}</p>
          <p className="mt-1 text-[11px] text-ink-faint">{t.nav.tagline}</p>
        </div>
      </div>

      <nav className="flex flex-col gap-1.5 text-sm" aria-label="Main">
        {NAV.map(({ key, segment, icon: Icon }) => {
          const href = `/${locale}/${segment}`;
          const active = pathname === href || pathname.startsWith(`${href}/`);
          return (
            <Link
              key={key}
              href={href}
              aria-current={active ? "page" : undefined}
              className={`flex items-center gap-3 rounded-[10px] px-3 py-[10px] transition-colors ${
                active
                  ? "bg-accent/14 font-semibold text-ink"
                  : "font-medium text-ink-soft hover:bg-surface-hover hover:text-ink"
              }`}
            >
              <Icon size={16} className={active ? "text-accent-strong" : ""} aria-hidden />
              {t.nav[key]}
            </Link>
          );
        })}
      </nav>

      <div className="mt-auto flex flex-col gap-3">
        <Link
          href={otherHref}
          className="flex items-center gap-2 rounded-[10px] px-3 py-2 text-[13px] font-medium text-ink-soft transition-colors hover:bg-surface-hover hover:text-ink"
        >
          <Languages size={15} aria-hidden />
          {LOCALE_LABEL[next]}
        </Link>

        <div className="flex items-center gap-3 rounded-[10px] border border-line bg-surface p-3">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-avatar text-xs font-semibold text-ink">
            {org ? initialsOf(org.name) : "?"}
          </div>
          <div className="min-w-0 flex-1">
            {org ? (
              <>
                <p
                  className="line-clamp-2 break-words text-[13px] font-semibold leading-tight text-ink"
                  title={org.name}
                >
                  <bdi>{org.name}</bdi>
                </p>
                {org.vat_number ? (
                  <p className="tabular mt-1 truncate font-mono text-[11px] text-ink-soft" dir="ltr">
                    {org.vat_number}
                  </p>
                ) : null}
              </>
            ) : (
              <p className="text-[12px] text-ink-faint">{t.nav.orgUnavailable}</p>
            )}
          </div>
        </div>
      </div>
    </aside>
  );
}
