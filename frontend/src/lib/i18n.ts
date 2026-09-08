/**
 * Bilingual ar/en with full RTL.
 *
 * Hand-rolled rather than pulled from a library: two locales, one namespace and
 * a typed dictionary is about forty lines, and it keeps the message catalogue
 * type-checked — a missing Arabic string is a compile error, not a key echoed
 * at a reviewer in production.
 *
 * Arabic is not an afterthought here. It is the primary language of the
 * documents this product reads, so `ar` is the default locale.
 */

export const LOCALES = ["ar", "en"] as const;
export type Locale = (typeof LOCALES)[number];

export const DEFAULT_LOCALE: Locale = "ar";

export function isLocale(value: string): value is Locale {
  return (LOCALES as readonly string[]).includes(value);
}

/** `dir` drives every logical property in the layout. Nothing is mirrored by hand. */
export function dirFor(locale: Locale): "rtl" | "ltr" {
  return locale === "ar" ? "rtl" : "ltr";
}

export function otherLocale(locale: Locale): Locale {
  return locale === "ar" ? "en" : "ar";
}

export const LOCALE_LABEL: Record<Locale, string> = {
  ar: "العربية",
  en: "English",
};
