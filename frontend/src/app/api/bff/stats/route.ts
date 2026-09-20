/** BFF: dashboard stats, for the browser to refresh after documents change state. */

import { NextResponse } from "next/server";

import { bffError } from "@/lib/api/bff";
import { getStats } from "@/lib/api/server";

export async function GET() {
  try {
    return NextResponse.json(await getStats());
  } catch (error) {
    return bffError(error);
  }
}
