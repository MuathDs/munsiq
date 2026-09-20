import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { HistoryView } from "@/components/dashboard/HistoryView";
import { LoadError } from "@/components/dashboard/LoadError";
import { TopBar } from "@/components/dashboard/TopBar";
import { attempt } from "@/lib/api/load";
import { getDocuments } from "@/lib/api/server";
import { DEFAULT_LOCALE, isLocale } from "@/lib/i18n";
import { messagesFor } from "@/lib/messages";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = messagesFor(isLocale(locale) ? locale : DEFAULT_LOCALE);
  return { title: `${t.nav.history} · ${t.appName}` };
}

export default async function HistoryPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  const t = messagesFor(locale);

  const documents = await attempt(() => getDocuments(200));
  if (!documents.ok) {
    return (
      <>
        <TopBar title={t.history.title} />
        <LoadError t={t} detail={documents.detail} />
      </>
    );
  }

  return <HistoryView initialDocuments={documents.data} locale={locale} t={t} />;
}
