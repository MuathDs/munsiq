import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { DEFAULT_LOCALE, isLocale } from "@/lib/i18n";

/**
 * `/` is not a page: it sends you to the dashboard, in the language you last
 * used (the proxy remembers it in a cookie) or Arabic, the default, if you have
 * none. The prototype's batch-processing screen used to live here; it is now the
 * dashboard's upload page, wired to the backend.
 */
export default async function Home() {
  const saved = (await cookies()).get("munsiq_locale")?.value;
  redirect(`/${saved && isLocale(saved) ? saved : DEFAULT_LOCALE}/dashboard`);
}
