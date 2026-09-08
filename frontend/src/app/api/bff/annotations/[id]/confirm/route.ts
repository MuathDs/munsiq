/**
 * BFF: confirm.
 *
 * A 409 from the backend means blocking findings remain. That response is
 * forwarded verbatim, bilingual messages and all — the workspace renders what
 * the rules said rather than paraphrasing it.
 */

import { NextResponse } from "next/server";

import { ApiError, confirmAnnotation } from "@/lib/api/server";

export async function POST(
  _request: Request,
  context: { params: Promise<{ id: string }> },
) {
  const { id } = await context.params;
  try {
    return NextResponse.json(await confirmAnnotation(id));
  } catch (error) {
    if (error instanceof ApiError) {
      // 409 carries {detail: {detail, blockers[]}} — pass it through intact.
      return NextResponse.json(
        typeof error.body === "object" && error.body !== null
          ? error.body
          : { error: error.message },
        { status: error.status },
      );
    }
    return NextResponse.json({ error: "upstream failure" }, { status: 502 });
  }
}
