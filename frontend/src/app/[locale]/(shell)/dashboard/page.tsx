import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { DashboardView } from "@/components/dashboard/DashboardView";
import { LoadError } from "@/components/dashboard/LoadError";
import { TopBar } from "@/components/dashboard/TopBar";
import { attempt } from "@/lib/api/load";
import { getDocuments, getStats } from "@/lib/api/server";
import { DEFAULT_LOCALE, isLocale } from "@/lib/i18n";
import { messagesFor } from "@/lib/messages";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = messagesFor(isLocale(locale) ? locale : DEFAULT_LOCALE);
  return { title: `${t.nav.dashboard} · ${t.appName}` };
}

export default async function DashboardPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  const t = messagesFor(locale);

  const [documents, stats] = await Promise.all([
    attempt(() => getDocuments()),
    attempt(() => getStats()),
  ]);
  if (!documents.ok || !stats.ok) {
    return (
      <>
        <TopBar title={t.dashboard.title} />
        <LoadError t={t} detail={!documents.ok ? documents.detail : !stats.ok ? stats.detail : ""} />
      </>
    );
  }

  return (
    <DashboardView
      initialDocuments={documents.data}
      initialStats={stats.data}
      locale={locale}
      t={t}
    />
  );
}
