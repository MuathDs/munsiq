# Handoff: Munsiq — Cloud Dashboard UI (AI Invoice Extraction)

## Overview
Dark-mode enterprise dashboard for Munsiq, an AI invoice-extraction tool. One primary screen ("Batch Processing"): sidebar nav, stats cards, a drag-and-drop batch upload zone, a live "AI Model Processing…" progress state, a searchable extracted-data table, and a "Download Excel (.xlsx)" action.

## About the Design Files
The bundled file (`Munsiq Dashboard.dc.html`) is a **design reference** — a single self-contained HTML prototype built to show layout, visual style, and interaction behavior. It is not production code and should not be copied verbatim into the Next.js app. Recreate the UI in the existing Next.js + Tailwind + Lucide React stack using the codebase's own component/data patterns, then wire it to the real Python/Ollama backend as described below.

The prototype currently **fakes** extraction: on load it auto-populates 4 sample invoices and animates their progress bars with `setInterval`/`Math.random()` (no real files are read, no real model runs). All of that fake logic must be replaced by real API calls per the wiring section below.

## Fidelity
**High-fidelity.** Colors, type, spacing, and component states below are final — implement pixel-accurately.

## Screens / Views

### Single screen: "Batch Processing"
Two-column layout: fixed 264px sidebar + flexible main content area (`display:flex`, main has `flex:1`, `padding:32px 40px 60px`, `gap:26px` between sections, vertical stack).

## Layout & Components

### Sidebar (`<aside>`, 264px wide, sticky, full height)
- Background `oklch(0.13 0.006 258)`, right border `1px solid oklch(1 0 0 / 8%)`, padding `22px 14px`, flex column, `gap:24px`.
- **Logo row**: 34×34px square, `border-radius:9px`, solid fill `oklch(0.64 0.19 276)` (accent), bold white "M" glyph (16px). Wordmark "Munsiq" (16px/700/-0.01em) + caption "AI Invoice Extraction" (11px, `oklch(0.55 0.012 258)`). Bottom border `1px solid oklch(1 0 0/8%)` under this block.
- **Nav list** (5 items, icon + label, 14px, `gap:12px`, item padding `10px 12px`, `border-radius:10px`):
  1. Dashboard — `layout-dashboard`
  2. Batch Upload — `upload-cloud` — **active** (bg `oklch(0.64 0.19 276 / 14%)`, text `oklch(0.96 0.003 258)` weight 600, icon tinted accent `oklch(0.72 0.17 276)`)
  3. History — `history`
  4. Templates — `file-text`
  5. Settings — `settings`
  Inactive items: text `oklch(0.66 0.014 258)`, weight 500, no background.
- **Profile chip** (pinned to bottom via `margin-top:auto`): 32px circular avatar (bg `oklch(0.3 0.01 258)`, initials "JD"), name "Jordan Diaz" (13px/600) + role "Finance Ops" (11px, secondary), trailing `chevron-right` icon. Card bg `oklch(0.19 0.006 258)`, border `1px solid oklch(1 0 0/8%)`, radius 10px, padding 12px.

### Top bar
Flex row, space-between. Left: H1 "Batch Processing" (28px/700/-0.015em) + subtitle "Upload invoices and let Munsiq's extraction model turn them into structured, exportable data in seconds." (14px, `oklch(0.62 0.013 258)`). Right: 38×38px bell icon button (bg `oklch(0.19 0.006 258)`, border, radius 9px) with a 6px green unread dot (`oklch(0.72 0.15 155)`) top-right, plus a 38px circular avatar.

### Stats cards
3-column grid, `gap:16px`. Each card: bg `oklch(0.19 0.006 258)`, border `1px solid oklch(1 0 0/8%)`, radius 14px, padding `20px 22px`.
- **Invoices Processed**: `inbox` icon, big value in JetBrains Mono (28px/700), green delta line "+N this session" (`oklch(0.72 0.15 155)`).
- **Extraction Accuracy**: `percent` icon, value "99.2%", caption "Rolling 30-day average".
- **Time Saved**: `clock` icon, value "N hrs" (mono), caption "vs. manual entry".

### Upload dropzone
Full-width card, `border-radius:16px`, `padding:48px 32px`, centered flex column, `gap:10px`. Default: dashed border `2px dashed oklch(1 0 0 / 14%)`, bg `oklch(0.19 0.006 258)`. Drag-over state: border becomes solid accent `oklch(0.64 0.19 276)`, bg tints to `oklch(0.64 0.19 276 / 10%)`. Contents: 52px rounded icon tile (`upload-cloud`, accent-tinted bg), heading "Drag & drop invoices here" (16px/600), caption "PDF, PNG or JPG — batch upload up to 20 files at once" (13px, secondary), solid accent "Browse files" button (radius 9px, white text, 13px/600), hidden native `<input type="file" multiple>`. Clicking anywhere in the zone (or the button) opens the file picker.

### Processing banner (shown only while any file is mid-extraction)
Row card: `loader-2` spinner icon (accent, `animation: spin 1s linear infinite`), label "AI Model Processing… X of Y complete" (13px/600), thin 6px progress track (`oklch(1 0 0/8%)`) with accent fill sized to the **average progress across all in-flight files**.

### Results card
Header row: title "Extracted Data" + pill badge "X of Y" (count of completed vs total). Right side: search input (left `search` icon, 220px wide, filters by vendor/filename/description) and the **"Download Excel (.xlsx)"** button (solid accent, `download` icon; disabled/greyed — bg `oklch(1 0 0/8%)`, text `oklch(0.5 0.012 258)`, `cursor:not-allowed` — until at least one row has finished extracting).

Table (horizontally scrollable container, `min-width:920px`), columns: **Vendor / File** (vendor name bold + filename in mono caption below), **Invoice Date** (mono), **Description**, **Subtotal** (mono, right-aligned), **Tax** (mono, right-aligned, secondary color), **Total** (mono, right-aligned, bold), **Status**.

Two row states per file:
- **Processing row**: filename (mono, `file-text` icon) in col 1, a progress bar spanning the middle 5 columns, "Processing" pill (neutral grey, spinner icon) in Status.
- **Done row**: full extracted data; Status shows either a green "Extracted" pill (`check` icon, `oklch(0.72 0.15 155)`) or, for flagged rows, an amber "Needs review" pill (`alert-triangle` icon, `oklch(0.75 0.15 80)`).

Row hover: bg `oklch(0.23 0.007 258)`.

Empty state (no files yet): centered `inbox` icon + "No invoices processed yet — upload a batch above to see extracted data here." (14px, secondary).

## Interactions & Behavior
- Drag-and-drop and click-to-browse both accept multiple files.
- Each uploaded file gets its own row and its own progress simulation in the prototype; in production each file's progress should reflect a **real** per-file extraction job.
- Once a file's job completes, its row flips from the processing layout to the data layout in place (no row reordering, no layout shift).
- Search input filters the table client-side by vendor, filename, or description (case-insensitive substring).
- Download button is disabled until ≥1 row has completed; the prototype currently generates the .xlsx client-side via SheetJS from already-loaded row data as a placeholder — replace with the real export call below.
- No routing/navigation exists yet — sidebar items other than "Batch Upload" are visual only.

## State Management
Minimum state needed in the real app:
- `files: Array<{ id, fileName, sizeBytes, status: 'queued'|'processing'|'done'|'error', progress, vendor?, date?, description?, subtotal?, tax?, total?, needsReview? }>`
- `search: string`
- `isDragging: boolean`
- Derived: `doneCount`, `totalCount`, `isProcessing`, `overallPercent`, `filteredFiles`

Recommend a small reducer or a query/mutation library (e.g. TanStack Query) driving `files` from server responses rather than local fake timers.

## Design Tokens

**Colors** (all `oklch`, keep as CSS variables in `globals.css` or `tailwind.config`):
| Token | Value | Use |
|---|---|---|
| `--bg` | `oklch(0.15 0.006 258)` | page background |
| `--sidebar-bg` | `oklch(0.13 0.006 258)` | sidebar |
| `--surface` | `oklch(0.19 0.006 258)` | cards |
| `--surface-hover` | `oklch(0.23 0.007 258)` | row/card hover |
| `--border` | `oklch(1 0 0 / 8%)` | default borders |
| `--border-strong` | `oklch(1 0 0 / 14%)` | dropzone dashed border |
| `--text-primary` | `oklch(0.94 0.003 258)` | body text |
| `--text-secondary` | `oklch(0.62–0.66 0.013 258)` | secondary text |
| `--text-tertiary` | `oklch(0.5 0.012 258)` | icons, placeholders |
| `--accent` | `oklch(0.64 0.19 276)` | primary actions, active states |
| `--accent-strong` | `oklch(0.72 0.17 276)` | icon tint on accent-soft bg |
| `--success` | `oklch(0.72 0.15 155)` | "Extracted" badge, unread dot |
| `--warning` | `oklch(0.75 0.15 80)` | "Needs review" badge |

**Typography**: Inter (400/500/600/700/800) for UI text; JetBrains Mono (400–700) for all numeric/monospace data (amounts, dates, filenames). Both via Google Fonts.

**Spacing/radius**: card radius 14–16px, pill radius 99px (full), button radius 9px, nav item radius 10px, gaps of 10/12/14/16/22/24/26/32/40px throughout — no arbitrary one-off values.

## Assets
No image assets. All icons are Lucide (`layout-dashboard`, `upload-cloud`, `history`, `file-text`, `settings`, `chevron-right`, `bell`, `inbox`, `percent`, `clock`, `search`, `download`, `loader-2`, `check`, `alert-triangle`).

## Files
- `Munsiq Dashboard.dc.html` — the full interactive HTML prototype (open directly in a browser).

---

## Integration Guide (Next.js + Tailwind + Python/Ollama backend)

### 1. Folder structure — what to create in `frontend/`
Don't replace `layout.tsx` wholesale — extend it. Suggested structure:

```
frontend/
  app/
    layout.tsx                 # add Inter + JetBrains Mono via next/font, keep dark mode default
    (dashboard)/
      page.tsx                 # renders <BatchProcessingPage />
  components/
    dashboard/
      Sidebar.tsx               # nav list + profile chip
      TopBar.tsx                # title/subtitle + bell + avatar
      StatsCards.tsx            # 3-card grid, takes stats as props
      UploadDropzone.tsx        # drag/drop + file input, calls onFilesSelected(files)
      ProcessingBanner.tsx      # shown while isProcessing
      ResultsTable.tsx          # search input + table, takes files[] + onDownload
      StatusBadge.tsx           # Extracted / Needs review / Processing pill
    BatchProcessingPage.tsx    # top-level client component owning state, composes the above
  lib/
    api.ts                     # uploadInvoices(), pollJobStatus(), downloadExcel()
    types.ts                   # InvoiceFile, ExtractionResult, JobStatus
  app/api/
    invoices/upload/route.ts   # proxies to Python backend
    invoices/[jobId]/route.ts  # polls job status from Python backend
    invoices/export/route.ts   # requests the .xlsx from Python backend and streams it back
```

`page.tsx` should be a thin server component that renders the client component `BatchProcessingPage` (mark that one `"use client"` since it owns interactive state).

### 2. Dependencies to install
```bash
npm install lucide-react
npm install xlsx            # only if you want the frontend to build the .xlsx itself;
                             # skip this if the Python backend generates the file (recommended — see below)
```
Tailwind: no extra plugins required. Add the two fonts via `next/font/google` in `layout.tsx` (`Inter`, `JetBrains_Mono`) and expose them as CSS variables (`--font-inter`, `--font-mono`) referenced in `tailwind.config.js` under `theme.extend.fontFamily`. Add the token colors above to `tailwind.config.js` under `theme.extend.colors` (or keep them as CSS custom properties in `globals.css` — either works with `oklch()` since Tailwind v3.4+/v4 support arbitrary `oklch()` values directly, e.g. `bg-[oklch(0.19_0.006_258)]`).

Dark mode: set `darkMode: 'class'` in Tailwind config and put `className="dark"` on `<html>` in `layout.tsx` so it's dark by default with no flash.

### 3. Wiring "Upload Invoices" to the Python/Ollama backend
Recommended flow — async job pattern, since Qwen-via-Ollama extraction takes real time per invoice:

1. **Frontend**: `UploadDropzone` collects `File[]` → `BatchProcessingPage` calls `lib/api.ts#uploadInvoices(files)`.
2. **Next.js API route** `app/api/invoices/upload/route.ts`: receives the `multipart/form-data`, forwards it to your Python backend (e.g. `POST http://localhost:8000/extract`), which should immediately return a `jobId` per file (or one batch `jobId`) rather than blocking on the model.
3. **Python backend** (FastAPI/Flask): on upload, save the file, kick off extraction against Ollama/Qwen as a background task per file, and expose `GET /jobs/{jobId}` returning `{ status: 'processing'|'done'|'error', progress, result? }`.
4. **Polling**: the frontend polls `app/api/invoices/[jobId]/route.ts` (which forwards to `GET /jobs/{jobId}`) every ~1–2s per in-flight file and updates that row's `progress`/`status` in state — this replaces the prototype's fake `setInterval`. If you want live updates instead of polling, expose an SSE or WebSocket endpoint from the Python side and swap the polling loop for an `EventSource`/socket subscription.
5. On `status: 'done'`, merge `result` (vendor, date, description, subtotal, tax, total, confidence) into that file's row. If your model returns a confidence score, use it to set `needsReview` (e.g. `confidence < 0.85`) instead of the prototype's fake modulo flag.

### 4. Wiring "Download Excel (.xlsx)"
Two valid approaches — pick one:
- **Backend-generated (recommended)**: `app/api/invoices/export/route.ts` posts the current batch's extracted rows (or just the `jobId`s) to a Python endpoint like `POST /export` that builds the workbook server-side (e.g. with `openpyxl` or `pandas.DataFrame.to_excel`) and returns the binary `.xlsx`. The Next.js route streams that response back with `Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` and `Content-Disposition: attachment; filename="munsiq-invoices.xlsx"`; the button triggers a normal `<a download>`/`window.location` to that route. This keeps formatting logic (currency, column widths, multiple sheets) in one place and avoids shipping the `xlsx` npm package to the client.
- **Client-generated**: keep the prototype's approach — install `xlsx` (SheetJS) and build the workbook in the browser from the rows already in state (`XLSX.utils.json_to_sheet` → `XLSX.writeFile`). Simpler, but limited to whatever data already reached the client.

Either way, disable the button while `doneCount === 0`, exactly as in the prototype.

### 5. Environment
Add to `.env.local`:
```
PYTHON_BACKEND_URL=http://localhost:8000
```
and read it in the three API routes above via `process.env.PYTHON_BACKEND_URL` — never call the Python backend directly from client components (keeps the backend off the public network and lets you add auth later).
