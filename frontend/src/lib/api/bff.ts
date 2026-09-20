import "server-only";

/**
 * Shared plumbing for the BFF route handlers.
 *
 * Every handler under `app/api/bff/` does the same two things: call the backend
 * through `server.ts`, and translate a failure into a response the browser can
 * act on. The translation lives here so no handler improvises its own.
 */

import { NextResponse } from "next/server";

import { ApiError } from "./server";

/**
 * A backend failure as a response.
 *
 * An ApiError keeps its status and body: a 409 from confirm carries the
 * bilingual blocker list, which the workspace renders verbatim. Anything else is
 * a 502 — the backend was unreachable or broke — and says so without leaking
 * internals to the browser.
 */
export function bffError(error: unknown): NextResponse {
  if (error instanceof ApiError) {
    return NextResponse.json(
      typeof error.body === "object" && error.body !== null
        ? error.body
        : { error: error.message },
      { status: error.status },
    );
  }
  return NextResponse.json({ error: "upstream failure" }, { status: 502 });
}
