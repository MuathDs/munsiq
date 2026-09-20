/**
 * Locale routing.
 *
 * `proxy.ts`, not `middleware.ts`: Next.js 16 renamed the convention and warns
 * on the old name. Same functionality, current spelling.
 *
 * Everything under `/[locale]` needs a locale segment; a bare `/annotations/...`
 * gets the default. Arabic is the default because it is the primary language of
 * the documents this product reads.
 *
 * It also remembers the language you are using in a cookie, so `/` (which
 * redirects to the dashboard) can send you back to the language you chose
 * instead of always resetting to Arabic. The cookie is a display preference, not
 * identity: nothing about tenancy or authorization ever reads it.
 */

import { NextResponse, type NextRequest } from "next/server";

import { DEFAULT_LOCALE, LOCALES, type Locale } from "@/lib/i18n";

const ONE_YEAR_S = 60 * 60 * 24 * 365;

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;

  const locale = LOCALES.find(
    (candidate) => pathname === `/${candidate}` || pathname.startsWith(`/${candidate}/`),
  );
  if (locale) return remember(NextResponse.next(), locale);

  // The workspace route predates locale prefixes: /annotations/x -> /ar/annotations/x.
  const url = request.nextUrl.clone();
  url.pathname = `/${DEFAULT_LOCALE}${pathname}`;
  return NextResponse.redirect(url);
}

function remember(response: NextResponse, locale: Locale): NextResponse {
  response.cookies.set("munsiq_locale", locale, {
    path: "/",
    maxAge: ONE_YEAR_S,
    sameSite: "lax",
  });
  return response;
}

export const config = {
  matcher: ["/annotations/:path*", "/:locale(ar|en)/:path*"],
};
