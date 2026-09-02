import { NextRequest } from "next/server";
import { createJob, updateJob } from "@/lib/jobStore";
import { extractFromText } from "@/lib/munsiqModel";
import type { InvoiceJob } from "@/lib/types";

async function processJob(job: InvoiceJob, text: string) {
  try {
    const { parsed, truncated } = await extractFromText(text, (pct) =>
      updateJob(job.id, { progress: pct }),
    );

    if (!parsed) {
      updateJob(job.id, {
        status: "error",
        progress: 100,
        errorMessage: truncated
          ? "Model output was cut off before the JSON finished (hit the token limit)"
          : "Model did not return valid JSON",
      });
      return;
    }

    // No confidence score is exposed by the model, so "needs review" is based on
    // whether extraction actually returned anything usable, not a fabricated score.
    const needsReview = truncated || Object.keys(parsed.fields).length === 0;

    updateJob(job.id, {
      status: "done",
      progress: 100,
      fields: parsed.fields,
      lineItems: parsed.lineItems,
      needsReview,
    });
  } catch (err) {
    updateJob(job.id, {
      status: "error",
      progress: 100,
      errorMessage: err instanceof Error ? err.message : "Extraction failed",
    });
  }
}

export async function POST(req: NextRequest) {
  let formData: FormData;
  try {
    formData = await req.formData();
  } catch {
    return Response.json({ error: "Request body was not valid multipart form data" }, { status: 400 });
  }

  const files = formData.getAll("files").filter((f): f is File => f instanceof File);

  if (files.length === 0) {
    return Response.json({ error: "No files provided" }, { status: 400 });
  }

  const created: InvoiceJob[] = [];

  for (const file of files) {
    const text = await file.text();
    const job = createJob(file.name);
    created.push(job);
    // Fire-and-forget: the row starts "processing" and the client polls
    // /api/invoices/status for progress rather than blocking this request.
    void processJob(job, text);
  }

  return Response.json({ jobs: created });
}
