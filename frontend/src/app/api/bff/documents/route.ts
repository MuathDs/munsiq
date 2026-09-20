/**
 * BFF: the document list, for the dashboard's live polling.
 *
 * The pages render their first frame on the server through `server.ts`; this is
 * only what the browser calls afterwards to keep it current.
 */

import { NextResponse } from "next/server";

import { bffError } from "@/lib/api/bff";
import { getDocuments } from "@/lib/api/server";

export async function GET() {
  try {
    return NextResponse.json(await getDocuments());
  } catch (error) {
    return bffError(error);
  }
}
