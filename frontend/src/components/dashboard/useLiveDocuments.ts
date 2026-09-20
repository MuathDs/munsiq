"use client";

/**
 * A document list that stays true while things are processing.
 *
 * The page renders its first frame on the server. From then on the browser polls
 * the BFF — but ONLY while something is processing. An idle dashboard makes no
 * requests, and it refreshes when the tab regains focus, which is when a reviewer
 * who left to read a PDF comes back.
 *
 * Nothing here estimates progress. A document is 'processing' until the backend
 * says otherwise; the pipeline does not report percentages, so neither does this.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import type { DocumentListItem, Stats } from "@/lib/api/types";

const POLL_INTERVAL_MS = 2000;

interface Options {
  /** Also keep the stat cards current. */
  withStats?: boolean;
  /** Bump to force an immediate refresh — for example, when an upload is accepted. */
  refreshKey?: number;
}

export function useLiveDocuments(
  initialDocuments: DocumentListItem[],
  initialStats: Stats | null = null,
  { withStats = false, refreshKey = 0 }: Options = {},
) {
  const [documents, setDocuments] = useState(initialDocuments);
  const [stats, setStats] = useState(initialStats);
  const [failing, setFailing] = useState(false);
  // When the request behind the current list was MADE (not answered): a snapshot
  // requested before an event cannot be trusted to know about it. 0 for the
  // server-rendered first frame, which predates anything the browser did.
  const [snapshotAt, setSnapshotAt] = useState(0);
  const busy = useRef(false);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const refresh = useCallback(async () => {
    // One request at a time: a slow backend must not stack up polls behind it.
    if (busy.current) return;
    busy.current = true;
    const requestedAt = Date.now();
    try {
      const [docsResponse, statsResponse] = await Promise.all([
        fetch("/api/bff/documents", { cache: "no-store" }),
        withStats ? fetch("/api/bff/stats", { cache: "no-store" }) : Promise.resolve(null),
      ]);
      if (!docsResponse.ok || (statsResponse && !statsResponse.ok)) {
        throw new Error("refresh failed");
      }
      const nextDocuments = (await docsResponse.json()) as DocumentListItem[];
      const nextStats = statsResponse ? ((await statsResponse.json()) as Stats) : null;
      if (!mounted.current) return;
      setDocuments(nextDocuments);
      setSnapshotAt(requestedAt);
      if (nextStats) setStats(nextStats);
      setFailing(false);
    } catch {
      // Keep showing what we had. The caller decides how loudly to say so.
      if (mounted.current) setFailing(true);
    } finally {
      busy.current = false;
    }
  }, [withStats]);

  const processing = documents.some((doc) => doc.state === "processing");

  useEffect(() => {
    if (!processing) return;
    const timer = setInterval(() => void refresh(), POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [processing, refresh]);

  useEffect(() => {
    if (refreshKey === 0) return;
    // Deferred a tick: the refresh sets state, and doing that synchronously in an
    // effect body would render twice for one change.
    const timer = setTimeout(() => void refresh(), 0);
    return () => clearTimeout(timer);
  }, [refreshKey, refresh]);

  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === "visible") void refresh();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [refresh]);

  return { documents, stats, failing, processing, snapshotAt, refresh };
}
