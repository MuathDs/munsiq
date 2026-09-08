import "server-only";

/**
 * Server-side backend client — the BFF layer.
 *
 * WHY THIS EXISTS. The backend derives tenant identity from a verified JWT and
 * nothing else; `get_current_org_id` raises 501 rather than accepting a header
 * or query parameter, because that value feeds the Postgres RLS GUC directly
 * and a caller-supplied one would let anyone choose a tenant.
 *
 * Real auth is deferred (see CLAUDE.md). Until it lands, the org identity lives
 * HERE — on the server, in an environment variable — and the browser never
 * sends a tenant id. Server components and the route handlers under
 * `app/api/bff/` are the only things that call the backend.
 *
 * `server-only` makes that structural: importing this file from a client
 * component is a build error, not a code review note.
 *
 * Replacing this with real auth is local: drop the header below, forward the
 * user's token instead, and let the backend read its own claim.
 */

import type { AnnotationDetail, CorrectionEvent, CorrectionResult } from "./types";

const API_BASE = process.env.MUNSIQ_API_URL ?? "http://127.0.0.1:8000";

/**
 * Dev-only tenant identity. In production this is replaced by the signed-in
 * user's org claim; nothing else about the call path changes.
 */
const DEV_ORG_ID = process.env.MUNSIQ_ORG_ID ?? "";

/** Proves to the backend that this caller is the BFF, not a browser. */
const BFF_SECRET = process.env.MUNSIQ_BFF_SECRET ?? "";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly body?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function assertConfigured(): void {
  if (!DEV_ORG_ID || !BFF_SECRET) {
    throw new ApiError(
      500,
      "MUNSIQ_ORG_ID and MUNSIQ_BFF_SECRET must both be set. The BFF holds " +
        "tenant identity server-side and authenticates itself to the backend; " +
        "see frontend/.env.local.example.",
    );
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  assertConfigured();
  const response = await fetch(`${API_BASE}/api/v1${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      // The backend accepts this pair ONLY when TRUSTED_BFF_ENABLED is on and
      // the secret matches. A browser has neither, so it cannot assert a
      // tenant. Both headers disappear when real auth lands.
      "X-Munsiq-Org": DEV_ORG_ID,
      "X-Munsiq-BFF-Secret": BFF_SECRET,
      ...init?.headers,
    },
    // Signed image URLs expire in five minutes and findings change on every
    // edit, so nothing here is safe to cache.
    cache: "no-store",
  });

  if (!response.ok) {
    let body: unknown;
    try {
      body = await response.json();
    } catch {
      body = await response.text();
    }
    throw new ApiError(response.status, `${init?.method ?? "GET"} ${path}`, body);
  }
  return (await response.json()) as T;
}

export function getAnnotation(id: string): Promise<AnnotationDetail> {
  return call<AnnotationDetail>(`/annotations/${id}`);
}

export function patchFields(
  id: string,
  events: CorrectionEvent[],
): Promise<CorrectionResult> {
  return call<CorrectionResult>(`/annotations/${id}/fields`, {
    method: "PATCH",
    body: JSON.stringify({ events }),
  });
}

export function confirmAnnotation(id: string): Promise<{ status: string }> {
  return call<{ status: string }>(`/annotations/${id}/confirm`, { method: "POST" });
}

/**
 * Page images are served by the backend against a short-lived signed token, so
 * their bytes never pass through Next.js — see CLAUDE.md, "Do not stream
 * document bytes through Next.js".
 */
export function absoluteImageUrl(relative: string): string {
  return `${API_BASE}${relative}`;
}
