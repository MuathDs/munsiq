/**
 * BFF: authorize one upload.
 *
 * Returns an absolute, signed URL. The browser posts the PDF straight to the
 * FastAPI backend with it, so document bytes never stream through Next.js and
 * the browser gets real upload progress. It never learns a tenant id — only a
 * token that expires in minutes and is bound to uploading.
 */

import { NextResponse } from "next/server";

import { bffError } from "@/lib/api/bff";
import { authorizeUpload } from "@/lib/api/server";

export async function POST() {
  try {
    return NextResponse.json(await authorizeUpload());
  } catch (error) {
    return bffError(error);
  }
}
