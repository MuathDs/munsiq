import * as XLSX from "xlsx";
import { getAllJobs } from "@/lib/jobStore";
import type { FieldValue } from "@/lib/munsiqModel";

function humanLabel(key: string): string {
  return key
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

// Union of keys across every row, in first-seen order -- this is what makes the
// export "dynamic": columns are derived from what was actually extracted this run,
// not from a fixed list baked into the code.
function unionKeysInOrder(records: Record<string, FieldValue>[]): string[] {
  const seen = new Set<string>();
  const order: string[] = [];
  for (const record of records) {
    for (const key of Object.keys(record)) {
      if (!seen.has(key)) {
        seen.add(key);
        order.push(key);
      }
    }
  }
  return order;
}

export async function GET() {
  const doneJobs = getAllJobs().filter((j) => j.status === "done");

  const fieldKeys = unionKeysInOrder(doneJobs.map((j) => j.fields ?? {}));
  const summaryRows = doneJobs.map((job) => {
    const row: Record<string, FieldValue> = {
      "File": job.fileName,
      "Needs Review": job.needsReview ? "Yes" : "No",
    };
    for (const key of fieldKeys) {
      row[humanLabel(key)] = job.fields?.[key] ?? "";
    }
    return row;
  });

  const lineItemKeys = unionKeysInOrder(doneJobs.flatMap((j) => j.lineItems ?? []));
  const lineItemRows = doneJobs.flatMap((job) =>
    (job.lineItems ?? []).map((item) => {
      const row: Record<string, FieldValue> = { "File": job.fileName };
      for (const key of lineItemKeys) {
        row[humanLabel(key)] = item[key] ?? "";
      }
      return row;
    }),
  );

  const workbook = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(workbook, XLSX.utils.json_to_sheet(summaryRows), "Summary");
  if (lineItemRows.length > 0) {
    XLSX.utils.book_append_sheet(workbook, XLSX.utils.json_to_sheet(lineItemRows), "Line Items");
  }

  const buffer = XLSX.write(workbook, { type: "buffer", bookType: "xlsx" }) as Buffer;

  return new Response(new Blob([Uint8Array.from(buffer)]), {
    headers: {
      "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      "Content-Disposition": 'attachment; filename="munsiq-invoices.xlsx"',
    },
  });
}
