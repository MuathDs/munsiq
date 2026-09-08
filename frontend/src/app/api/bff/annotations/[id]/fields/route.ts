/**
 * BFF: field corrections.
 *
 * The browser PATCHes here, not the backend. Tenant identity is attached
 * server-side by `lib/api/server`, so the request the browser sends carries no
 * org id at all — there is nothing for a caller to tamper with.
 *
 * This is NOT the deprecated `app/api/extract` path: no model is called here,
 * and every byte goes to the FastAPI backend.
 */

import { NextResponse } from "next/server";

import { ApiError, patchFields } from "@/lib/api/server";
import type { CorrectionEvent } from "@/lib/api/types";

export async function PATCH(
  request: Request,
  context: { params: Promise<{ id: string }> },
) {
  const { id } = await context.params;

  let events: CorrectionEvent[];
  try {
    const body = (await request.json()) as { events?: CorrectionEvent[] };
    events = body.events ?? [];
  } catch {
    return NextResponse.json({ error: "invalid JSON body" }, { status: 400 });
  }

  if (events.length === 0) {
    return NextResponse.json({ error: "no events" }, { status: 400 });
  }

  try {
    return NextResponse.json(await patchFields(id, events));
  } catch (error) {
    if (error instanceof ApiError) {
      return NextResponse.json({ error: error.body ?? error.message }, {
        status: error.status,
      });
    }
    return NextResponse.json({ error: "upstream failure" }, { status: 502 });
  }
}
