/**
 * BFF: export a confirmed annotation.
 *
 * The body and headers pass through untouched, so an XLSX arrives as an XLSX with
 * its filename. A 409 (not confirmed yet) is forwarded with its bilingual message
 * so the UI can show why, instead of downloading an error page.
 */

import { NextResponse } from "next/server";

import { bffError } from "@/lib/api/bff";
import { exportAnnotation } from "@/lib/api/server";

const FORMATS = new Set(["json", "xlsx", "csv"]);

export async function GET(
  request: Request,
  context: { params: Promise<{ id: string }> },
) {
  const { id } = await context.params;
  const format = new URL(request.url).searchParams.get("format") ?? "json";
  if (!FORMATS.has(format)) {
    return NextResponse.json({ error: "format must be json, xlsx or csv" }, { status: 400 });
  }
  try {
    const upstream = await exportAnnotation(id, format);
    return new Response(upstream.body, {
      status: 200,
      headers: {
        "Content-Type": upstream.headers.get("content-type") ?? "application/octet-stream",
        "Content-Disposition": upstream.headers.get("content-disposition") ?? "attachment",
        "Cache-Control": "no-store",
      },
    });
  } catch (error) {
    return bffError(error);
  }
}
