/**
 * Locale routing.
 *
 * `proxy.ts`, not `middleware.ts`: Next.js 16 renamed the convention and warns
 * on the old name. Same functionality, current spelling.
 *
 * Everything under `/[locale]` needs a locale segment; a bare path gets the
 * default. Arabic is the default because it is the primary language of the
 * documents this product reads.
 *
 * The legacy dashboard at `/` and the BFF routes under `/api` are left alone —
 * see CLAUDE.md, "Deprecated paths".
 */

import { NextResponse, type NextRequest } from "next/server";

import { DEFAULT_LOCALE, LOCALES } from "@/lib/i18n";

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;

  const hasLocale = LOCALES.some(
    (locale) => pathname === `/${locale}` || pathname.startsWith(`/${locale}/`),
  );
  if (hasLocale) return NextResponse.next();

  // Only paths this phase owns are redirected. The legacy prototype keeps its
  // route exactly as it was.
  if (pathname.startsWith("/annotations")) {
    const url = request.nextUrl.clone();
    url.pathname = `/${DEFAULT_LOCALE}${pathname}`;
    return NextResponse.redirect(url);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/annotations/:path*"],
};
