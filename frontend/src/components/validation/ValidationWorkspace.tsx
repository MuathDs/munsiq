"use client";

/**
 * The split-screen review page.
 *
 * Layout is a two-column CSS Grid with a draggable splitter. The columns are
 * declared in logical order — document first, fields second — so `dir="rtl"`
 * mirrors the whole thing without a single locale branch. Nothing here knows
 * which side is "left".
 *
 * Hierarchy is one primary element per region:
 *
 *   HEADER     the invoice number — which document am I looking at
 *   DOCUMENT   the page itself, fitted to the pane
 *   FIELDS     the blocker card when there is one, otherwise the values
 *
 * Compliance and provenance are header chips, not a strip of their own: they
 * summarise the document, so they sit next to its name and open on demand.
 */

import { CircleCheck, FileText, Keyboard, Languages, Loader2, TriangleAlert, X } from "lucide-react";
import Link from "next/link";
import { useCallback, useMemo, useRef, useState } from "react";

import {
  currentValue,
  fieldKeyOf,
  type AnnotationDetail,
  type ExtractedField,
} from "@/lib/api/types";
import { LOCALE_LABEL, otherLocale, type Locale } from "@/lib/i18n";
import { interpolate, messagesFor, type Messages } from "@/lib/messages";

import { BlockerList } from "./BlockerList";
import { DocumentPane } from "./DocumentPane";
import { FieldPane } from "./FieldPane";
import { labelFor, orderFields } from "./fieldModel";
import { ShortcutsOverlay } from "./ShortcutsOverlay";
import {
  useDebouncedFlush,
  useWorkspace,
  type SaveState,
  type WorkspaceState,
} from "./useAnnotationReducer";
import { useFieldNavigation } from "./useFieldNavigation";
import { SourceChip, ZatcaSummary } from "./ZatcaPanel";

const MIN_FRACTION = 0.25;
const MAX_FRACTION = 0.75;

function clampSplit(value: number): number {
  return Math.min(MAX_FRACTION, Math.max(MIN_FRACTION, value));
}

function persistSplit(value: number) {
  // One cookie, no server round trip: a reviewer's preferred proportions
  // survive the next document.
  document.cookie = `munsiq_split=${value.toFixed(3)}; path=/; max-age=31536000; samesite=lax`;
}

export function ValidationWorkspace({
  detail,
  locale,
  initialSplit,
}: {
  detail: AnnotationDetail;
  locale: Locale;
  initialSplit: number;
}) {
  const t = messagesFor(locale);
  const isArabic = locale === "ar";

  const [state, dispatch] = useWorkspace(detail);
  const { flushNow } = useDebouncedFlush(state, dispatch, detail.annotation_id);

  const schemaFields = useMemo(() => detail.schema_fields ?? [], [detail.schema_fields]);
  // The one ordering the pane renders AND the keyboard walks.
  const ordered = useMemo(
    () => orderFields(state.fields, schemaFields),
    [state.fields, schemaFields],
  );
  const blockingCount = state.findings.filter((f) => f.severity === "error" && !f.passed).length;

  const [split, setSplit] = useState(initialSplit);
  // The drag's mouseup handler is created when the drag starts, so it would
  // persist the split as it was THEN. The ref always holds the latest value.
  const splitRef = useRef(initialSplit);
  const [showHelp, setShowHelp] = useState(false);
  const gridRef = useRef<HTMLDivElement>(null);

  const applySplit = useCallback((value: number) => {
    const next = clampSplit(value);
    splitRef.current = next;
    setSplit(next);
  }, []);

  const focusKey = useCallback((key: string) => dispatch({ type: "focus", key }), [dispatch]);

  const jumpToField = useCallback(
    (fieldKey: string) => {
      const match = ordered.find((f) => f.field_key === fieldKey);
      if (match) focusKey(fieldKeyOf(match));
    },
    [ordered, focusKey],
  );

  const confirm = useCallback(async () => {
    // Flush first: confirming with unsaved edits would ask the server to judge
    // a document the reviewer has already changed on screen.
    await flushNow();
    dispatch({ type: "confirm:start" });
    try {
      const response = await fetch(`/api/bff/annotations/${detail.annotation_id}/confirm`, {
        method: "POST",
      });
      if (response.status === 409) {
        const body = (await response.json()) as {
          detail?: { detail?: string; blockers?: { rule_code: string }[] };
        };
        // The server's sentence is English-only; the banner is composed here
        // from the blocker count so it reads correctly in either language.
        dispatch({
          type: "confirm:blocked",
          message: t.errors.blockedTitle,
          blockers: (body.detail?.blockers ?? []).map((b) => b.rule_code),
        });
        return;
      }
      if (!response.ok) throw new Error(String(response.status));
      dispatch({ type: "confirm:ok" });
    } catch {
      dispatch({ type: "confirm:blocked", message: t.actions.confirmFailed, blockers: [] });
    }
  }, [detail.annotation_id, dispatch, flushNow, t]);

  useFieldNavigation(ordered, state.focusedKey, {
    onFocusKey: focusKey,
    onRevert: (field) => dispatch({ type: "revert", field }),
    onConfirm: () => void confirm(),
    onToggleHelp: () => setShowHelp((open) => !open),
  });

  const startDrag = useCallback(() => {
    document.body.classList.add("dragging");

    const onMove = (event: MouseEvent) => {
      const rect = gridRef.current?.getBoundingClientRect();
      if (!rect) return;
      const raw = (event.clientX - rect.left) / rect.width;
      // In RTL the grid's first column sits on the right, so the pointer's
      // distance from the inline start is mirrored.
      applySplit(isArabic ? 1 - raw : raw);
    };

    const onUp = () => {
      document.body.classList.remove("dragging");
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      persistSplit(splitRef.current);
    };

    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  }, [applySplit, isArabic]);

  const confirmed = state.status === "confirmed";

  return (
    <div className="flex h-dvh flex-col bg-bg">
      <Header
        detail={detail}
        state={state}
        locale={locale}
        t={t}
        blockingCount={blockingCount}
        onConfirm={() => void confirm()}
        onHelp={() => setShowHelp(true)}
      />

      {state.confirmError ? (
        <ConfirmBanner
          message={state.confirmError.message}
          blockers={state.confirmError.blockers}
          t={t}
          onJump={() => {
            const first = ordered.find((f) => f.validation_state === "blocking");
            if (first) focusKey(fieldKeyOf(first));
          }}
          onDismiss={() => dispatch({ type: "confirm:dismiss" })}
        />
      ) : null}

      <div
        ref={gridRef}
        className="grid min-h-0 flex-1"
        // Logical order: document, splitter, fields. `dir` does the mirroring.
        style={{ gridTemplateColumns: `${split}fr 9px ${1 - split}fr` }}
      >
        <div className="min-w-0 overflow-hidden">
          <DocumentPane
            pages={detail.pages}
            fields={state.fields}
            focusedKey={state.focusedKey}
            hoveredKey={state.hoveredKey}
            onSelect={focusKey}
            onHover={(key) => dispatch({ type: "hover", key })}
            t={t}
          />
        </div>

        <div
          role="separator"
          aria-orientation="vertical"
          aria-label={t.workspace.resize}
          aria-valuemin={MIN_FRACTION * 100}
          aria-valuemax={MAX_FRACTION * 100}
          aria-valuenow={Math.round(split * 100)}
          tabIndex={0}
          onMouseDown={startDrag}
          onKeyDown={(event) => {
            // Keyboard-resizable: the splitter is not mouse-only.
            if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
            event.preventDefault();
            const step = event.key === "ArrowLeft" ? -0.02 : 0.02;
            applySplit(splitRef.current + (isArabic ? -step : step));
            persistSplit(splitRef.current);
          }}
          className="group relative flex cursor-col-resize justify-center bg-bg focus-visible:outline-none"
        >
          <span
            aria-hidden
            className="h-full w-px bg-line transition-colors group-hover:bg-accent group-focus-visible:bg-accent"
          />
          <span
            aria-hidden
            className="absolute top-1/2 h-10 w-[5px] -translate-y-1/2 rounded-full border border-line-strong bg-surface transition-colors group-hover:border-accent group-hover:bg-accent group-focus-visible:border-accent group-focus-visible:bg-accent"
          />
        </div>

        <div className="min-w-0 overflow-hidden">
          <FieldPane
            fields={ordered}
            schemaFields={schemaFields}
            findings={state.findings}
            focusedKey={state.focusedKey}
            t={t}
            isArabic={isArabic}
            onFocus={focusKey}
            onHover={(key) => dispatch({ type: "hover", key })}
            onChange={(field: ExtractedField, value) => dispatch({ type: "edit", field, value })}
          >
            <BlockerList
              findings={state.findings}
              isArabic={isArabic}
              t={t}
              labelFor={(key) => labelFor(key, schemaFields, isArabic)}
              onJump={jumpToField}
            />
          </FieldPane>
        </div>
      </div>

      {/* Announces state changes to screen readers without stealing focus. */}
      <div aria-live="polite" className="sr-only">
        {state.save === "saving" ? t.actions.saving : null}
        {state.save === "saved" ? t.actions.saved : null}
        {state.save === "error" ? t.actions.saveFailed : null}
        {confirmed ? t.actions.confirmed : null}
      </div>

      {showHelp ? <ShortcutsOverlay t={t} onClose={() => setShowHelp(false)} /> : null}
    </div>
  );
}

/** The value of a single (non-repeating) field, for the header. */
function headerValue(fields: ExtractedField[], key: string): string | null {
  const field = fields.find((f) => f.field_key === key && f.row_index === null);
  return field ? currentValue(field) : null;
}

const STATUS_TONE: Record<string, string> = {
  confirmed: "border-success/35 bg-success-soft text-success",
  approved: "border-success/35 bg-success-soft text-success",
  failed: "border-danger/40 bg-danger-soft text-danger",
  rejected: "border-danger/40 bg-danger-soft text-danger",
};

function Header({
  detail,
  state,
  locale,
  t,
  blockingCount,
  onConfirm,
  onHelp,
}: {
  detail: AnnotationDetail;
  state: WorkspaceState;
  locale: Locale;
  t: Messages;
  blockingCount: number;
  onConfirm: () => void;
  onHelp: () => void;
}) {
  const next = otherLocale(locale);
  const statusLabel = (t.status as Record<string, string>)[state.status] ?? state.status;
  const invoiceNumber = headerValue(state.fields, "invoice_number");
  const seller = headerValue(state.fields, "seller_name");
  const confirmed = state.status === "confirmed";
  const blocked = blockingCount > 0 && !confirmed;

  const confirmFace = confirmed
    ? "border border-success/35 bg-success-soft text-success"
    : blocked
      ? "border border-danger/50 text-danger hover:bg-danger-soft"
      : "bg-accent text-white hover:bg-accent-strong";

  return (
    <header className="flex h-16 shrink-0 items-center gap-4 border-b border-line bg-sidebar px-6">
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[10px] bg-accent/15 text-accent-strong">
        <FileText size={18} aria-hidden />
      </span>

      <div className="min-w-0">
        <p className="text-[11px] font-medium leading-4 text-ink-faint">{t.workspace.title}</p>
        <div className="flex min-w-0 items-center gap-2.5">
          <h1
            // An invoice number is an identifier: it reads left to right even
            // inside an Arabic header.
            dir={invoiceNumber ? "ltr" : undefined}
            className={`truncate text-[18px] font-semibold leading-6 text-ink ${
              invoiceNumber ? "tabular font-mono tracking-tight" : ""
            }`}
          >
            {invoiceNumber ?? t.workspace.untitled}
          </h1>
          <span
            className={`shrink-0 rounded-full border px-2 py-0.5 text-[11px] font-semibold ${
              STATUS_TONE[state.status] ?? "border-line-strong bg-line text-ink-soft"
            }`}
          >
            {statusLabel}
          </span>
          {seller ? (
            <span className="hidden min-w-0 truncate text-[13px] text-ink-soft xl:inline">
              <span className="me-2.5 text-ink-faint" aria-hidden>
                ·
              </span>
              <bdi>{seller}</bdi>
            </span>
          ) : null}
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-2">
        <ZatcaSummary hasEmbeddedUbl={detail.has_embedded_ubl} findings={state.findings} t={t} />
        <SourceChip modelVersion={detail.model_version} t={t} />
      </div>

      <div className="ms-auto flex shrink-0 items-center gap-1.5">
        <SaveIndicator state={state.save} t={t} />

        <Link
          href={`/${next}/annotations/${detail.annotation_id}`}
          className="flex h-8 items-center gap-1.5 rounded-[9px] px-2.5 text-[12px] font-medium text-ink-soft transition-colors hover:bg-surface-hover hover:text-ink"
        >
          <Languages size={15} aria-hidden />
          {LOCALE_LABEL[next]}
        </Link>

        <button
          type="button"
          onClick={onHelp}
          aria-label={t.actions.shortcuts}
          title={t.actions.shortcuts}
          className="flex h-8 w-8 items-center justify-center rounded-[9px] text-ink-soft transition-colors hover:bg-surface-hover hover:text-ink"
        >
          <Keyboard size={16} aria-hidden />
        </button>

        <span className="mx-1.5 h-6 w-px bg-line" aria-hidden />

        <button
          type="button"
          onClick={onConfirm}
          disabled={state.confirming || confirmed}
          title={blocked ? interpolate(t.actions.resolveFirst, { count: blockingCount }) : undefined}
          className={`flex h-9 items-center gap-2 rounded-[9px] px-4 text-[13px] font-semibold transition-colors disabled:cursor-default ${confirmFace} ${
            state.confirming ? "opacity-70" : ""
          }`}
        >
          {state.confirming ? (
            <Loader2 size={15} className="animate-spin" aria-hidden />
          ) : (
            <CircleCheck size={15} aria-hidden />
          )}
          {confirmed ? t.actions.confirmed : state.confirming ? t.actions.confirming : t.actions.confirm}
          {blocked && !state.confirming ? (
            <span className="tabular rounded-full bg-danger/20 px-1.5 font-mono text-[11px] leading-5">
              {blockingCount}
            </span>
          ) : null}
        </button>
      </div>
    </header>
  );
}

/**
 * Why a confirm attempt did not go through. Previously the reducer recorded
 * this and nothing rendered it, so a blocked confirm looked like a dead button.
 */
function ConfirmBanner({
  message,
  blockers,
  t,
  onJump,
  onDismiss,
}: {
  message: string;
  blockers: string[];
  t: Messages;
  onJump: () => void;
  onDismiss: () => void;
}) {
  const count = blockers.length;
  return (
    <div
      role="alert"
      className="flex shrink-0 items-center gap-3 border-b border-danger/30 bg-danger-soft px-6 py-2.5"
    >
      <TriangleAlert size={16} className="shrink-0 text-danger" aria-hidden />
      <p className="shrink-0 text-[13px] font-semibold text-danger">{message}</p>
      {count > 0 ? (
        <p className="min-w-0 truncate text-[13px] text-ink-soft">
          {count === 1 ? t.blockers.countOne : interpolate(t.blockers.countMany, { count })}
        </p>
      ) : null}
      {count > 0 ? (
        <div className="hidden min-w-0 items-center gap-1.5 lg:flex">
          {blockers.map((code) => (
            <code
              key={code}
              dir="ltr"
              className="rounded-[6px] bg-danger/15 px-1.5 py-0.5 font-mono text-[11px] font-semibold text-danger"
            >
              {code}
            </code>
          ))}
        </div>
      ) : null}
      <div className="ms-auto flex shrink-0 items-center gap-1">
        {count > 0 ? (
          <button
            type="button"
            onClick={onJump}
            className="h-7 rounded-[9px] px-2.5 text-[12px] font-semibold text-danger transition-colors hover:bg-danger/15"
          >
            {t.blockers.openField}
          </button>
        ) : null}
        <button
          type="button"
          onClick={onDismiss}
          aria-label={t.actions.close}
          title={t.actions.close}
          className="flex h-7 w-7 items-center justify-center rounded-[9px] text-danger/80 transition-colors hover:bg-danger/15 hover:text-danger"
        >
          <X size={15} aria-hidden />
        </button>
      </div>
    </div>
  );
}

function SaveIndicator({ state, t }: { state: SaveState; t: Messages }) {
  if (state === "idle") return null;
  const tone =
    state === "error" ? "text-danger" : state === "saved" ? "text-success" : "text-ink-soft";
  const dot = state === "error" ? "bg-danger" : state === "saved" ? "bg-success" : "bg-ink-faint";
  const label =
    state === "saving" ? t.actions.saving : state === "saved" ? t.actions.saved : t.actions.saveFailed;
  return (
    <span className={`me-1 flex items-center gap-1.5 text-[12px] ${tone}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${dot}`} aria-hidden />
      {label}
    </span>
  );
}
