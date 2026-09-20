/**
 * The app shell: sidebar, page area, and the upload engine.
 *
 * A route group, so `(shell)` adds nothing to the URL. It wraps the dashboard,
 * upload, history, templates and settings pages — and deliberately NOT
 * `/annotations/[id]`, which is the validation workspace and owns the whole
 * viewport. The two share the locale layout above and nothing else.
 *
 * The layout persists across navigations between its pages, which is why the
 * organization is fetched once here rather than in every page, and why the
 * upload engine can live here and keep a batch running while you look at History.
 */

import { notFound } from "next/navigation";

import { Sidebar } from "@/components/dashboard/Sidebar";
import { UploadProvider } from "@/components/dashboard/UploadProvider";
import { attempt } from "@/lib/api/load";
import { getOrg } from "@/lib/api/server";
import { isLocale } from "@/lib/i18n";
import { messagesFor } from "@/lib/messages";

export default async function ShellLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  const t = messagesFor(locale);

  // A failing backend must not take the navigation down with it: the pages
  // below say what went wrong, and the sidebar still lets you leave.
  const org = await attempt(() => getOrg());

  return (
    <UploadProvider>
      <div className="flex min-h-dvh bg-bg text-ink">
        <Sidebar locale={locale} t={t} org={org.ok ? org.data : null} />
        <main className="flex min-w-0 flex-1 flex-col gap-[26px] px-10 pb-15 pt-8">{children}</main>
      </div>
    </UploadProvider>
  );
}
