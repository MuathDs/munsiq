import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { SettingsView } from "@/components/dashboard/SettingsView";
import { attempt } from "@/lib/api/load";
import { getOrg, getSystem } from "@/lib/api/server";
import { DEFAULT_LOCALE, isLocale } from "@/lib/i18n";
import { messagesFor } from "@/lib/messages";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = messagesFor(isLocale(locale) ? locale : DEFAULT_LOCALE);
  return { title: `${t.nav.settings} · ${t.appName}` };
}

export default async function SettingsPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();

  // Each block renders only if its data loaded. A settings page that fails
  // because the backend is down should still let you change the language.
  const [org, system] = await Promise.all([attempt(() => getOrg()), attempt(() => getSystem())]);

  return (
    <SettingsView
      org={org.ok ? org.data : null}
      system={system.ok ? system.data : null}
      locale={locale}
      t={messagesFor(locale)}
    />
  );
}
