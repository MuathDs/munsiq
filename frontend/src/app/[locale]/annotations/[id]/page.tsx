/**
 * The validation workspace route.
 *
 * A thin server component: it fetches the annotation through the BFF — where
 * the org identity lives — and hands a plain object to the client component.
 * The browser never learns which tenant it is looking at, and never talks to
 * the FastAPI backend directly.
 */

import { cookies } from "next/headers";
import { notFound } from "next/navigation";

import { absoluteImageUrl, ApiError, getAnnotation } from "@/lib/api/server";
import { isLocale } from "@/lib/i18n";
import { messagesFor } from "@/lib/messages";
import { ValidationWorkspace } from "@/components/validation/ValidationWorkspace";

const DEFAULT_SPLIT = 0.56;

export default async function AnnotationPage({
  params,
}: {
  params: Promise<{ locale: string; id: string }>;
}) {
  const { locale, id } = await params;
  if (!isLocale(locale)) notFound();

  let detail;
  try {
    detail = await getAnnotation(id);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    const t = messagesFor(locale);
    return (
      <main className="flex h-dvh items-center justify-center p-8">
        <div className="max-w-md text-center">
          <p className="text-sm text-danger">{t.errors.loadFailed}</p>
          <p className="mt-2 font-mono text-[11px] text-ink-faint">
            {error instanceof ApiError ? String(error.body ?? error.message) : String(error)}
          </p>
        </div>
      </main>
    );
  }

  // Page images are served by the backend against a signed token, so the
  // browser fetches them from there directly — their bytes never pass through
  // Next.js. See CLAUDE.md, "Do not stream document bytes through Next.js".
  const pages = detail.pages.map((page) => ({
    ...page,
    image_url: page.image_url ? absoluteImageUrl(page.image_url) : null,
  }));

  const store = await cookies();
  const saved = Number(store.get("munsiq_split")?.value);
  const split = Number.isFinite(saved) && saved > 0.2 && saved < 0.8 ? saved : DEFAULT_SPLIT;

  return (
    <ValidationWorkspace
      detail={{ ...detail, pages }}
      locale={locale}
      initialSplit={split}
    />
  );
}
