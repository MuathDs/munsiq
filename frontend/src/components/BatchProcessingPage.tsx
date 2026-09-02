"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Sidebar } from "./dashboard/Sidebar";
import { TopBar } from "./dashboard/TopBar";
import { StatsCards } from "./dashboard/StatsCards";
import { UploadDropzone } from "./dashboard/UploadDropzone";
import { ProcessingBanner } from "./dashboard/ProcessingBanner";
import { ResultsTable } from "./dashboard/ResultsTable";
import { ToastStack } from "./ToastStack";
import { useToasts } from "@/lib/useToasts";
import type { InvoiceJob } from "@/lib/types";

const POLL_INTERVAL_MS = 1500;
const MINUTES_SAVED_PER_DOC = 3;

export function BatchProcessingPage() {
  const [jobs, setJobs] = useState<InvoiceJob[]>([]);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const connectionFailingRef = useRef(false);
  const seenErrorIdsRef = useRef<Set<string>>(new Set());
  const { toasts, pushToast, dismissToast } = useToasts();

  const hasInFlight = jobs.some((j) => j.status === "processing");

  const pollStatus = useCallback(async () => {
    try {
      const res = await fetch("/api/invoices/status");
      if (!res.ok) {
        throw new Error(`Status check failed (${res.status})`);
      }
      const data = await res.json();
      const newJobs = data.jobs as InvoiceJob[];

      // Surface a toast the moment a job flips to "error" -- e.g. the model
      // returned malformed or truncated JSON -- instead of only showing it
      // as a quiet badge in the table.
      for (const job of newJobs) {
        if (job.status === "error" && !seenErrorIdsRef.current.has(job.id)) {
          seenErrorIdsRef.current.add(job.id);
          pushToast(`Couldn't extract "${job.fileName}": ${job.errorMessage ?? "unknown error"}`);
        }
      }

      setJobs(newJobs);
      connectionFailingRef.current = false;
    } catch (err) {
      // Avoid toast-spam: only notify once per failure streak, not every poll tick.
      if (!connectionFailingRef.current) {
        connectionFailingRef.current = true;
        pushToast(
          err instanceof Error
            ? `Lost connection to the extraction service: ${err.message}`
            : "Lost connection to the extraction service.",
        );
      }
    }
  }, [pushToast]);

  useEffect(() => {
    if (hasInFlight && !pollRef.current) {
      pollRef.current = setInterval(pollStatus, POLL_INTERVAL_MS);
    }
    if (!hasInFlight && pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [hasInFlight, pollStatus]);

  async function handleFilesSelected(files: File[]) {
    const formData = new FormData();
    files.forEach((file) => formData.append("files", file));

    try {
      const res = await fetch("/api/invoices/upload", { method: "POST", body: formData });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.error ?? `Upload failed (${res.status})`);
      }
      const data = await res.json();
      setJobs((prev) => [...prev, ...(data.jobs as InvoiceJob[])]);
      pollStatus();
    } catch (err) {
      pushToast(err instanceof Error ? err.message : "Failed to upload files.");
    }
  }

  function handleDownload() {
    window.location.href = "/api/invoices/export";
  }

  const doneJobs = jobs.filter((j) => j.status === "done");
  const reviewedClean = doneJobs.filter((j) => !j.needsReview).length;
  const accuracyPct = doneJobs.length > 0 ? (reviewedClean / doneJobs.length) * 100 : null;
  const hoursSaved = (doneJobs.length * MINUTES_SAVED_PER_DOC) / 60;

  return (
    <div className="flex min-h-screen bg-bg text-ink">
      <Sidebar />
      <main className="flex-1 flex flex-col gap-[26px] pt-8 px-10 pb-15">
        <TopBar />
        <StatsCards
          processedCount={doneJobs.length}
          accuracyPct={accuracyPct}
          hoursSaved={hoursSaved}
        />
        <UploadDropzone onFilesSelected={handleFilesSelected} />
        <ProcessingBanner jobs={jobs} />
        <ResultsTable jobs={jobs} onDownload={handleDownload} />
      </main>
      <ToastStack toasts={toasts} onDismiss={dismissToast} />
    </div>
  );
}
