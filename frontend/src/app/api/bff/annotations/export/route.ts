/**
 * BFF: export several confirmed annotations as one Excel workbook.
 *
 * All or nothing. If any selected invoice is not confirmed the backend refuses the
 * whole batch with a bilingual message naming them, and that refusal is forwarded
 * so the UI can show why instead of saving an error page as a spreadsheet.
 */

import { NextResponse } from "next/server";

import { bffError } from "@/lib/api/bff";
import { exportBatch } from "@/lib/api/server";

const MAX_IDS = 200;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export async function POST(request: Request) {
  let ids: unknown;
  try {
    ({ ids } = (await request.json()) as { ids?: unknown });
  } catch {
    return NextResponse.json(
      { error: "expected a JSON body" },
      { status: 400 },
    );
  }
  if (
    !Array.isArray(ids) ||
    ids.length === 0 ||
    ids.length > MAX_IDS ||
    !ids.every((id) => typeof id === "string" && UUID.test(id))
  ) {
    return NextResponse.json(
      { error: `ids must be 1 to ${MAX_IDS} annotation ids` },
      { status: 400 },
    );
  }

  try {
    const upstream = await exportBatch(ids as string[]);
    return new Response(upstream.body, {
      status: 200,
      headers: {
        "Content-Type":
          upstream.headers.get("content-type") ?? "application/octet-stream",
        "Content-Disposition":
          upstream.headers.get("content-disposition") ?? "attachment",
        "Cache-Control": "no-store",
      },
    });
  } catch (error) {
    return bffError(error);
  }
}
