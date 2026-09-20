import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { LoadError } from "@/components/dashboard/LoadError";
import { TemplatesView } from "@/components/dashboard/TemplatesView";
import { TopBar } from "@/components/dashboard/TopBar";
import { attempt } from "@/lib/api/load";
import { getTemplates } from "@/lib/api/server";
import { DEFAULT_LOCALE, isLocale } from "@/lib/i18n";
import { messagesFor } from "@/lib/messages";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = messagesFor(isLocale(locale) ? locale : DEFAULT_LOCALE);
  return { title: `${t.nav.templates} · ${t.appName}` };
}

export default async function TemplatesPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  const t = messagesFor(locale);

  const templates = await attempt(() => getTemplates());
  if (!templates.ok) {
    return (
      <>
        <TopBar title={t.templates.title} />
        <LoadError t={t} detail={templates.detail} />
      </>
    );
  }

  return <TemplatesView templates={templates.data} locale={locale} t={t} />;
}
