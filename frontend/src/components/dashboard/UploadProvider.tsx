"use client";

/**
 * Uploads that survive navigation.
 *
 * The engine lives in a provider mounted by the shell layout, not in the upload
 * page, so starting a batch and then opening History to watch it does not abort
 * the batch. Page components come and go; the engine does not.
 *
 * HOW A FILE MOVES:
 *   1. ask the BFF to authorize an upload (it holds the tenant identity);
 *   2. POST the PDF straight to the FastAPI backend with the signed URL it got
 *      back. Document bytes never pass through Next.js (CLAUDE.md), and an
 *      XMLHttpRequest is what gives real per-byte progress — fetch cannot;
 *   3. from there it is 'processing' until the backend's document list says
 *      otherwise. The pipeline reports no percentages, so none are invented.
 *
 * The engine records error CODES, never sentences: the components render them in
 * the reviewer's language.
 */

import {
  createContext,
  useContext,
  useEffect,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";

import type { UploadAuthorization, UploadResult } from "@/lib/api/types";

export const MAX_FILES_PER_BATCH = 20;
const CONCURRENCY = 2;
/** Until the backend says otherwise (it does, on the first authorization). */
const DEFAULT_MAX_BYTES = 25 * 1024 * 1024;

export type UploadErrorCode = "notPdf" | "tooLarge" | "network" | "expired" | "server";

export interface UploadError {
  code: UploadErrorCode;
  status?: number;
}

/** 'processing' is settled by the caller against the live document list. */
export type UploadPhase = "queued" | "uploading" | "processing" | "done" | "failed";

export interface UploadItem {
  id: string;
  name: string;
  size: number;
  phase: UploadPhase;
  /** Bytes sent, 0–100. Real: from the XHR's upload events. */
  progress: number;
  documentId: string | null;
  annotationId: string | null;
  duplicate: boolean;
  retried: boolean;
  /** When the file finished uploading; drives the elapsed timer while it processes. */
  processingSince: number | null;
  error: UploadError | null;
}

function postFile(
  url: string,
  file: File,
  onProgress: (pct: number) => void,
): Promise<{ status: number; body: UploadResult | null }> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100));
    };
    xhr.onload = () => {
      let body: UploadResult | null = null;
      try {
        body = JSON.parse(xhr.responseText) as UploadResult;
      } catch {
        // A non-JSON error body (a proxy's HTML page, say) is still an error status.
      }
      resolve({ status: xhr.status, body });
    };
    xhr.onerror = () => reject(new Error("network"));
    xhr.onabort = () => reject(new Error("aborted"));
    const form = new FormData();
    form.append("file", file, file.name);
    xhr.send(form);
  });
}

function isPdf(file: File): boolean {
  return file.type === "application/pdf" || /\.pdf$/i.test(file.name);
}

interface Snapshot {
  items: UploadItem[];
  /** Increments each time the backend accepts a file, so views can refresh at once. */
  accepted: number;
}

/** A small external store: React subscribes to it rather than owning its state. */
class UploadEngine {
  private items: UploadItem[] = [];
  private accepted = 0;
  private snapshot: Snapshot = { items: [], accepted: 0 };
  private listeners = new Set<() => void>();

  private files = new Map<string, File>();
  private queue: string[] = [];
  private active = 0;
  private maxBytes = DEFAULT_MAX_BYTES;
  private counter = 0;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  /** Stable between changes, as useSyncExternalStore requires. */
  getSnapshot = (): Snapshot => this.snapshot;

  private notify() {
    this.snapshot = { items: this.items, accepted: this.accepted };
    this.listeners.forEach((listener) => listener());
  }

  private patch(id: string, changes: Partial<UploadItem>) {
    this.items = this.items.map((item) => (item.id === id ? { ...item, ...changes } : item));
    this.notify();
  }

  /** Returns true when the selection was longer than a batch and had to be cut. */
  add = (selected: File[]): boolean => {
    const truncated = selected.length > MAX_FILES_PER_BATCH;
    const added: UploadItem[] = [];
    for (const file of selected.slice(0, MAX_FILES_PER_BATCH)) {
      const id = `upload-${++this.counter}`;
      const base: UploadItem = {
        id,
        name: file.name,
        size: file.size,
        phase: "queued",
        progress: 0,
        documentId: null,
        annotationId: null,
        duplicate: false,
        retried: false,
        processingSince: null,
        error: null,
      };
      // Refuse what the server would refuse, but say so per file rather than
      // silently dropping it: the reviewer picked twenty and should see why
      // nineteen are moving.
      if (!isPdf(file)) {
        added.push({ ...base, phase: "failed", error: { code: "notPdf" } });
      } else if (file.size > this.maxBytes) {
        added.push({ ...base, phase: "failed", error: { code: "tooLarge" } });
      } else {
        this.files.set(id, file);
        this.queue.push(id);
        added.push(base);
      }
    }
    this.items = [...this.items, ...added];
    this.notify();
    this.pump();
    return truncated;
  };

  dismiss = (ids: string[]) => {
    const drop = new Set(ids);
    this.items = this.items.filter((item) => !drop.has(item.id));
    this.notify();
  };

  private pump() {
    while (this.active < CONCURRENCY && this.queue.length > 0) {
      const id = this.queue.shift() as string;
      this.active += 1;
      void this.run(id).finally(() => {
        this.active -= 1;
        this.files.delete(id);
        this.pump();
      });
    }
  }

  private async run(id: string) {
    const file = this.files.get(id);
    if (!file) return;
    this.patch(id, { phase: "uploading", progress: 0 });

    // Two attempts: the second exists only for an expired authorization, which
    // is the one failure a fresh token actually fixes.
    for (let attempt = 0; attempt < 2; attempt += 1) {
      let granted: UploadAuthorization;
      try {
        const response = await fetch("/api/bff/uploads/authorize", { method: "POST" });
        if (!response.ok) {
          return this.fail(id, response.status === 502 ? "network" : "server", response.status);
        }
        granted = (await response.json()) as UploadAuthorization;
      } catch {
        return this.fail(id, "network");
      }

      this.maxBytes = granted.max_bytes;
      if (file.size > granted.max_bytes) return this.fail(id, "tooLarge");

      let result: { status: number; body: UploadResult | null };
      try {
        result = await postFile(granted.upload_url, file, (pct) => this.patch(id, { progress: pct }));
      } catch {
        return this.fail(id, "network");
      }

      if (result.status === 403 && attempt === 0) continue;
      if (result.status === 403) return this.fail(id, "expired");
      if (result.status === 413) return this.fail(id, "tooLarge");
      if (result.status === 415) return this.fail(id, "notPdf");
      if ((result.status !== 200 && result.status !== 202) || !result.body) {
        return this.fail(id, "server", result.status);
      }

      const body = result.body;
      this.accepted += 1;
      // An exact duplicate that already has a result needs no waiting.
      const settled = body.duplicate && body.annotation_id !== null;
      this.patch(id, {
        phase: settled ? "done" : "processing",
        progress: 100,
        documentId: body.document_id,
        annotationId: body.annotation_id,
        duplicate: body.duplicate,
        retried: body.retried,
        processingSince: settled ? null : Date.now(),
      });
      return;
    }
  }

  private fail(id: string, code: UploadErrorCode, status?: number) {
    this.patch(id, { phase: "failed", error: { code, status } });
  }
}

interface UploadContextValue {
  items: UploadItem[];
  accepted: number;
  add: (files: File[]) => boolean;
  dismiss: (ids: string[]) => void;
}

const UploadContext = createContext<UploadContextValue | null>(null);

export function UploadProvider({ children }: { children: ReactNode }) {
  const [engine] = useState(() => new UploadEngine());
  const { items, accepted } = useSyncExternalStore(
    engine.subscribe,
    engine.getSnapshot,
    engine.getSnapshot,
  );

  // Uploads in flight are lost on a hard reload or tab close. Say so, once,
  // rather than letting a reviewer close the tab on a half-sent batch.
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      const busy = engine
        .getSnapshot()
        .items.some((item) => item.phase === "queued" || item.phase === "uploading");
      if (busy) event.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [engine]);

  const value: UploadContextValue = { items, accepted, add: engine.add, dismiss: engine.dismiss };
  return <UploadContext.Provider value={value}>{children}</UploadContext.Provider>;
}

export function useUploads(): UploadContextValue {
  const context = useContext(UploadContext);
  if (!context) throw new Error("useUploads must be used inside <UploadProvider>");
  return context;
}
