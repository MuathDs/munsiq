import { randomUUID } from "crypto";
import type { InvoiceJob } from "./types";

// In-memory, single-process job store. This is fine for local/portfolio use,
// where the Next.js server is one long-lived Node process -- it resets on
// server restart and would not work across multiple serverless instances.
const jobs = new Map<string, InvoiceJob>();

export function createJob(fileName: string): InvoiceJob {
  const job: InvoiceJob = {
    id: randomUUID(),
    fileName,
    status: "processing",
    progress: 0,
  };
  jobs.set(job.id, job);
  return job;
}

export function updateJob(id: string, patch: Partial<InvoiceJob>): void {
  const existing = jobs.get(id);
  if (!existing) return;
  jobs.set(id, { ...existing, ...patch });
}

export function getAllJobs(): InvoiceJob[] {
  return Array.from(jobs.values());
}
