import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { dirFor, isLocale, LOCALES } from "@/lib/i18n";

export const metadata: Metadata = {
  title: "Munsiq — Validation workspace",
  description: "Review and confirm extracted invoice data.",
};

export function generateStaticParams() {
  return LOCALES.map((locale) => ({ locale }));
}

/**
 * Locale shell.
 *
 * Renders a wrapper element rather than its own `<html>`: the root layout
 * already provides one for the legacy dashboard at `/`, and two `<html>` tags
 * in one tree is invalid markup that React reports as a hydration mismatch.
 *
 * `dir` and `lang` on a wrapper are valid HTML and apply to the whole subtree,
 * so every CSS logical property below still mirrors correctly — which is the
 * only thing the layout actually needs from them.
 */
export default async function LocaleLayout({
  children,
  params,
}: Readonly<{
  children: React.ReactNode;
  params: Promise<{ locale: string }>;
}>) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();

  return (
    <div lang={locale} dir={dirFor(locale)} className="min-h-dvh">
      {children}
    </div>
  );
}

export const dynamicParams = false;
