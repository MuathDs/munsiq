import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { LoadError } from "@/components/dashboard/LoadError";
import { TopBar } from "@/components/dashboard/TopBar";
import { UploadView } from "@/components/dashboard/UploadView";
import { attempt } from "@/lib/api/load";
import { getDocuments, getSystem } from "@/lib/api/server";
import { DEFAULT_LOCALE, isLocale } from "@/lib/i18n";
import { messagesFor } from "@/lib/messages";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = messagesFor(isLocale(locale) ? locale : DEFAULT_LOCALE);
  return { title: `${t.nav.upload} · ${t.appName}` };
}

export default async function UploadPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  const t = messagesFor(locale);

  const [documents, system] = await Promise.all([
    attempt(() => getDocuments(10)),
    attempt(() => getSystem()),
  ]);
  if (!documents.ok || !system.ok) {
    return (
      <>
        <TopBar title={t.upload.title} />
        <LoadError t={t} detail={!documents.ok ? documents.detail : !system.ok ? system.detail : ""} />
      </>
    );
  }

  return (
    <UploadView
      initialDocuments={documents.data}
      // The limit shown in the hint is the backend's own, never a copy of it.
      maxMb={Math.round(system.data.max_upload_bytes / (1024 * 1024))}
      locale={locale}
      t={t}
    />
  );
}
