import type { FieldValue, LineItem } from "./munsiqModel";

export type JobStatus = "processing" | "done" | "error";

export interface InvoiceJob {
  id: string;
  fileName: string;
  status: JobStatus;
  progress: number; // 0-100
  // Dynamic, per-document header fields (vendor, dates, IBAN, tax breakdown, ...) --
  // the key set varies by what was actually found in each document, no fixed schema.
  fields?: Record<string, FieldValue>;
  // Dynamic line-item table rows, present only when the document had one.
  lineItems?: LineItem[];
  needsReview?: boolean;
  errorMessage?: string;
}
