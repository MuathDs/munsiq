/**
 * Display formatting. Presentation only — nothing here changes a value.
 *
 * Money is a string end to end (CLAUDE.md: never a float), so it is grouped by
 * string manipulation rather than through `Number`, which would round a
 * 20-digit amount and could turn "0.10" into "0.1".
 */

import type { Locale } from "./i18n";

const PLAIN_DECIMAL = /^(-?)(\d+)(\.\d+)?$/;

/** "52118.00" -> "52,118.00". Anything that is not a plain decimal is returned as is. */
export function formatMoney(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const match = PLAIN_DECIMAL.exec(value.trim());
  if (!match) return value;
  const [, sign, whole, fraction = ""] = match;
  return `${sign}${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",")}${fraction}`;
}

/**
 * Gregorian, Latin digits, in both locales.
 *
 * Arabic-Indic digits would sit next to the monospace Latin figures everywhere
 * else on the page (amounts, invoice numbers), and `ar-SA` defaults to the
 * Hijri calendar, which is not what an invoice date means.
 */
export function formatDateTime(iso: string, locale: Locale): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat(locale === "ar" ? "ar-SA-u-ca-gregory-nu-latn" : "en-GB", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

/** 65_000 -> "1:05". */
export function formatElapsed(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

/** 1_536_000 -> "1.5 MB". */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** Up to two initials for an avatar: "Al Jazeera Industrial" -> "AJ"; Arabic -> its first letter. */
export function initialsOf(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return "?";
  if (/[؀-ۿ]/.test(words[0])) return Array.from(words[0])[0];
  return words
    .slice(0, 2)
    .map((word) => Array.from(word)[0]?.toUpperCase() ?? "")
    .join("");
}
