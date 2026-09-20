"use client";

import { useMemo, useState } from "react";
import { Search, Download, Inbox, FileText, ChevronDown, ChevronRight } from "lucide-react";
import type { InvoiceJob } from "@/lib/types";
import type { FieldValue } from "@/lib/munsiqModel";
import { StatusBadge } from "./StatusBadge";

interface ResultsTableProps {
  jobs: InvoiceJob[];
  onDownload: () => void;
}

const PINNED_COLUMN_LIMIT = 5;

function humanLabel(key: string): string {
  return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatValue(value: FieldValue | undefined): string {
  if (value === undefined || value === null || value === "") return "—";
  if (typeof value === "number") return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
  return String(value);
}

// The table can't show every field a variable schema might produce, so the most
// frequently-extracted keys across this batch become fixed at-a-glance columns --
// everything else (plus line items) is one click away in the expanded row.
function pickPinnedColumns(jobs: InvoiceJob[], limit: number): string[] {
  const frequency = new Map<string, number>();
  const firstSeenOrder: string[] = [];

  for (const job of jobs) {
    if (job.status !== "done" || !job.fields) continue;
    for (const key of Object.keys(job.fields)) {
      if (!frequency.has(key)) firstSeenOrder.push(key);
      frequency.set(key, (frequency.get(key) ?? 0) + 1);
    }
  }

  return [...firstSeenOrder]
    .sort((a, b) => (frequency.get(b) ?? 0) - (frequency.get(a) ?? 0))
    .slice(0, limit);
}

export function ResultsTable({ jobs, onDownload }: ResultsTableProps) {
  const [search, setSearch] = useState("");
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const doneCount = jobs.filter((j) => j.status === "done").length;
  const canDownload = doneCount > 0;

  const pinnedColumns = useMemo(() => pickPinnedColumns(jobs, PINNED_COLUMN_LIMIT), [jobs]);

  const filtered = jobs.filter((job) => {
    if (!search.trim()) return true;
    const q = search.toLowerCase();
    if (job.fileName.toLowerCase().includes(q)) return true;
    return Object.values(job.fields ?? {}).some((v) => String(v ?? "").toLowerCase().includes(q));
  });

  return (
    <div className="rounded-[14px] border border-line bg-surface">
      <div className="flex items-center justify-between px-5 py-4 border-b border-line gap-4">
        <div className="flex items-center gap-2 shrink-0">
          <h2 className="text-base font-semibold text-ink">Extracted Data</h2>
          <span className="rounded-full bg-line text-ink-soft text-xs font-medium px-2.5 py-0.5">
            {doneCount} of {jobs.length}
          </span>
        </div>
        <div className="flex items-center gap-3 shrink-0">
          <div className="relative">
            <Search
              size={14}
              className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-faint"
            />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search any extracted field or file"
              className="w-[240px] rounded-[9px] border border-line bg-bg pl-8 pr-3 py-1.5 text-[13px] text-ink placeholder:text-ink-faint"
            />
          </div>
          <button
            onClick={onDownload}
            disabled={!canDownload}
            className={`inline-flex items-center gap-1.5 rounded-[9px] px-3 py-1.5 text-[13px] font-semibold ${
              canDownload
                ? "bg-accent text-white cursor-pointer"
                : "bg-line text-ink-faint cursor-not-allowed"
            }`}
          >
            <Download size={14} />
            Download Excel (.xlsx)
          </button>
        </div>
      </div>

      {jobs.length === 0 ? (
        <div className="flex flex-col items-center gap-3 py-16 text-center px-6">
          <Inbox size={28} className="text-ink-faint" />
          <p className="text-sm text-ink-soft max-w-sm">
            No invoices processed yet — upload a batch above to see extracted data here.
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[920px] text-left text-sm">
            <thead>
              <tr className="text-ink-faint text-xs uppercase tracking-wide">
                <th className="px-5 py-3 font-medium w-8" />
                <th className="px-5 py-3 font-medium">File</th>
                {pinnedColumns.map((key) => (
                  <th key={key} className="px-5 py-3 font-medium">
                    {humanLabel(key)}
                  </th>
                ))}
                <th className="px-5 py-3 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((job) => {
                const isExpanded = expandedId === job.id;
                const extraFieldKeys = Object.keys(job.fields ?? {}).filter(
                  (k) => !pinnedColumns.includes(k),
                );
                const canExpand =
                  job.status === "done" && (extraFieldKeys.length > 0 || (job.lineItems?.length ?? 0) > 0);

                return (
                  <>
                    <tr key={job.id} className="border-t border-line hover:bg-surface-hover">
                      <td className="px-5 py-3">
                        {canExpand && (
                          <button
                            onClick={() => setExpandedId(isExpanded ? null : job.id)}
                            className="text-ink-faint hover:text-ink cursor-pointer"
                            aria-label="Toggle details"
                          >
                            {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                          </button>
                        )}
                      </td>
                      <td className="px-5 py-3">
                        <p className="font-mono text-xs text-ink-faint flex items-center gap-1">
                          <FileText size={11} />
                          {job.fileName}
                        </p>
                      </td>
                      {job.status === "processing" ? (
                        <td colSpan={pinnedColumns.length} className="px-5 py-3">
                          <div className="h-1.5 rounded-full bg-line overflow-hidden">
                            <div
                              className="h-full bg-accent transition-[width] duration-300"
                              style={{ width: `${job.progress}%` }}
                            />
                          </div>
                        </td>
                      ) : (
                        pinnedColumns.map((key) => (
                          <td key={key} className="px-5 py-3 text-ink-soft font-mono">
                            {formatValue(job.fields?.[key])}
                          </td>
                        ))
                      )}
                      <td className="px-5 py-3">
                        <StatusBadge job={job} />
                      </td>
                    </tr>
                    {isExpanded && (
                      <tr key={`${job.id}-detail`} className="border-t border-line bg-bg/40">
                        <td />
                        <td colSpan={pinnedColumns.length + 2} className="px-5 py-4">
                          {extraFieldKeys.length > 0 && (
                            <div className="grid grid-cols-3 gap-x-6 gap-y-2 mb-4">
                              {extraFieldKeys.map((key) => (
                                <div key={key} className="text-xs">
                                  <span className="text-ink-faint">{humanLabel(key)}: </span>
                                  <span className="text-ink font-mono">
                                    {formatValue(job.fields?.[key])}
                                  </span>
                                </div>
                              ))}
                            </div>
                          )}
                          {job.lineItems && job.lineItems.length > 0 && (
                            <div className="overflow-x-auto rounded-[9px] border border-line">
                              <table className="w-full text-left text-xs">
                                <thead>
                                  <tr className="text-ink-faint uppercase tracking-wide bg-surface">
                                    {Object.keys(job.lineItems[0]).map((key) => (
                                      <th key={key} className="px-3 py-2 font-medium">
                                        {humanLabel(key)}
                                      </th>
                                    ))}
                                  </tr>
                                </thead>
                                <tbody>
                                  {job.lineItems.map((item, i) => (
                                    <tr key={i} className="border-t border-line">
                                      {Object.keys(job.lineItems![0]).map((key) => (
                                        <td key={key} className="px-3 py-2 font-mono text-ink-soft">
                                          {formatValue(item[key])}
                                        </td>
                                      ))}
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          )}
                        </td>
                      </tr>
                    )}
                  </>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
