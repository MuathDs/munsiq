/**
 * Download a generated file through the BFF and say honestly whether it worked.
 *
 * A plain `<a download>` cannot: on a refusal the browser saves the error page as
 * the file, and nothing tells the UI the export happened. Fetching first means a
 * 409 ("not confirmed yet") surfaces as a message in the reviewer's language and
 * a success is known, so the invoice can move to "exported" only when it did.
 */

import type { Locale } from "./i18n";

export type DownloadResult =
  { ok: true; filename: string } | { ok: false; message: string | null };

/** The backend's bilingual refusal, if the response carries one. */
function refusalMessage(body: unknown, locale: Locale): string | null {
  if (typeof body !== "object" || body === null) return null;
  const detail = (body as { detail?: unknown }).detail;
  if (typeof detail !== "object" || detail === null) return null;
  const key = locale === "ar" ? "message_ar" : "message_en";
  const message = (detail as Record<string, unknown>)[key];
  return typeof message === "string" ? message : null;
}

function filenameFrom(header: string | null, fallback: string): string {
  const match = header?.match(/filename="?([^";]+)"?/i);
  return match?.[1] ?? fallback;
}

export async function downloadFile(
  url: string,
  locale: Locale,
  init?: RequestInit,
  fallbackName = "munsiq-export",
): Promise<DownloadResult> {
  let response: Response;
  try {
    response = await fetch(url, { cache: "no-store", ...init });
  } catch {
    return { ok: false, message: null };
  }

  if (!response.ok) {
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      // Not JSON: the caller falls back to its generic message.
    }
    return { ok: false, message: refusalMessage(body, locale) };
  }

  const filename = filenameFrom(
    response.headers.get("content-disposition"),
    fallbackName,
  );
  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  // Revoked on the next turn: revoking synchronously can cancel the save in some browsers.
  setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
  return { ok: true, filename };
}
