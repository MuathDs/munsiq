"use client";

/**
 * The split-screen review page.
 *
 * Layout is a two-column CSS Grid with a draggable splitter. The columns are
 * declared in logical order — document first, fields second — so `dir="rtl"`
 * mirrors the whole thing without a single locale branch. Nothing here knows
 * which side is "left".
 */

import { CircleCheck, Keyboard, Languages, Loader2 } from "lucide-react";
import Link from "next/link";
import { useCallback, useRef, useState } from "react";

import { fieldKeyOf, type AnnotationDetail, type ExtractedField } from "@/lib/api/types";
import { LOCALE_LABEL, otherLocale, type Locale } from "@/lib/i18n";
import { messagesFor } from "@/lib/messages";

import { BlockerList } from "./BlockerList";
import { DocumentPane } from "./DocumentPane";
import { FieldPane } from "./FieldPane";
import { ShortcutsOverlay } from "./ShortcutsOverlay";
import { useDebouncedFlush, useWorkspace } from "./useAnnotationReducer";
import { useFieldNavigation } from "./useFieldNavigation";
import { ZatcaPanel } from "./ZatcaPanel";

const MIN_FRACTION = 0.25;
const MAX_FRACTION = 0.75;

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

  const [split, setSplit] = useState(initialSplit);
  const [showHelp, setShowHelp] = useState(false);
  const gridRef = useRef<HTMLDivElement>(null);

  const focusKey = useCallback(
    (key: string) => dispatch({ type: "focus", key }),
    [dispatch],
  );

  const confirm = useCallback(async () => {
    // Flush first: confirming with unsaved edits would ask the server to judge
    // a document the reviewer has already changed on screen.
    await flushNow();
    dispatch({ type: "confirm:start" });
    try {
      const response = await fetch(
        `/api/bff/annotations/${detail.annotation_id}/confirm`,
        { method: "POST" },
      );
      if (response.status === 409) {
        const body = (await response.json()) as {
          detail?: { detail?: string; blockers?: { rule_code: string }[] };
        };
        dispatch({
          type: "confirm:blocked",
          message: body.detail?.detail ?? t.errors.blockedTitle,
          blockers: (body.detail?.blockers ?? []).map((b) => b.rule_code),
        });
        return;
      }
      if (!response.ok) throw new Error(String(response.status));
      dispatch({ type: "confirm:ok" });
    } catch {
      dispatch({
        type: "confirm:blocked",
        message: t.actions.saveFailed,
        blockers: [],
      });
    }
  }, [detail.annotation_id, dispatch, flushNow, t]);

  useFieldNavigation(state.fields, state.focusedKey, {
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
      const fraction = isArabic ? 1 - raw : raw;
      setSplit(Math.min(MAX_FRACTION, Math.max(MIN_FRACTION, fraction)));
    };

    const onUp = () => {
      document.body.classList.remove("dragging");
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      // Persisted so a reviewer's preferred proportions survive the next
      // document. One cookie, no server round trip.
      document.cookie = `munsiq_split=${split.toFixed(3)}; path=/; max-age=31536000; samesite=lax`;
    };

    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  }, [isArabic, split]);

  const confirmed = state.status === "confirmed";

  return (
    <div className="flex h-dvh flex-col bg-bg">
      <Header
        detail={detail}
        state={state}
        locale={locale}
        onConfirm={() => void confirm()}
        onHelp={() => setShowHelp(true)}
        confirmed={confirmed}
      />

      <ZatcaPanel
        hasEmbeddedUbl={detail.has_embedded_ubl}
        findings={state.findings}
        modelVersion={detail.model_version}
        t={t}
      />

      <div
        ref={gridRef}
        className="grid min-h-0 flex-1"
        // Logical order: document, splitter, fields. `dir` does the mirroring.
        style={{ gridTemplateColumns: `${split}fr 6px ${1 - split}fr` }}
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
          aria-label="Resize panes"
          tabIndex={0}
          onMouseDown={startDrag}
          onKeyDown={(event) => {
            // Keyboard-resizable: the splitter is not mouse-only.
            if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
              event.preventDefault();
              const step = event.key === "ArrowLeft" ? -0.02 : 0.02;
              const delta = isArabic ? -step : step;
              setSplit((s) => Math.min(MAX_FRACTION, Math.max(MIN_FRACTION, s + delta)));
            }
          }}
          className="cursor-col-resize bg-line transition-colors hover:bg-accent"
        />

        <div className="flex min-w-0 flex-col overflow-hidden border-s border-line">
          <BlockerList
            findings={state.findings}
            isArabic={isArabic}
            t={t}
            onJump={(fieldKey) => {
              const match = state.fields.find((f) => f.field_key === fieldKey);
              if (match) focusKey(fieldKeyOf(match));
            }}
          />
          <FieldPane
            fields={state.fields}
            findings={state.findings}
            focusedKey={state.focusedKey}
            t={t}
            isArabic={isArabic}
            onFocus={focusKey}
            onHover={(key) => dispatch({ type: "hover", key })}
            onChange={(field: ExtractedField, value) =>
              dispatch({ type: "edit", field, value })
            }
          />
        </div>
      </div>

      {/* Announces state changes to screen readers without stealing focus. */}
      <div aria-live="polite" className="sr-only">
        {state.save === "saving" ? t.actions.saving : null}
        {state.save === "saved" ? t.actions.saved : null}
        {state.save === "error" ? t.actions.saveFailed : null}
        {confirmed ? t.actions.confirmed : null}
      </div>

      {showHelp ? (
        <ShortcutsOverlay t={t} onClose={() => setShowHelp(false)} />
      ) : null}
    </div>
  );
}

function Header({
  detail,
  state,
  locale,
  onConfirm,
  onHelp,
  confirmed,
}: {
  detail: AnnotationDetail;
  state: ReturnType<typeof useWorkspace>[0];
  locale: Locale;
  onConfirm: () => void;
  onHelp: () => void;
  confirmed: boolean;
}) {
  const t = messagesFor(locale);
  const next = otherLocale(locale);
  const statusLabel =
    (t.status as Record<string, string>)[state.status] ?? state.status;

  return (
    <header className="flex items-center gap-3 border-b border-line bg-sidebar px-4 py-2.5">
      <h1 className="text-sm font-semibold text-ink">{t.workspace.title}</h1>
      <span className="tabular rounded-full bg-line px-2 py-0.5 text-[11px] text-ink-soft">
        {statusLabel}
      </span>

      <div className="ms-auto flex items-center gap-2">
        <SaveIndicator state={state.save} t={t} />

        <Link
          href={`/${next}/annotations/${detail.annotation_id}`}
          className="flex items-center gap-1.5 rounded-lg border border-line px-2.5 py-1.5 text-xs text-ink-soft hover:bg-surface-hover hover:text-ink"
        >
          <Languages size={14} />
          {LOCALE_LABEL[next]}
        </Link>

        <button
          type="button"
          onClick={onHelp}
          aria-label={t.actions.shortcuts}
          className="rounded-lg border border-line p-1.5 text-ink-soft hover:bg-surface-hover hover:text-ink"
        >
          <Keyboard size={14} />
        </button>

        <button
          type="button"
          onClick={onConfirm}
          disabled={state.confirming || confirmed}
          className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors ${
            confirmed
              ? "bg-success-soft text-success"
              : "bg-accent text-white hover:bg-accent-strong disabled:opacity-60"
          }`}
        >
          {state.confirming ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <CircleCheck size={14} />
          )}
          {confirmed
            ? t.actions.confirmed
            : state.confirming
              ? t.actions.confirming
              : t.actions.confirm}
        </button>
      </div>
    </header>
  );
}

function SaveIndicator({
  state,
  t,
}: {
  state: "idle" | "saving" | "saved" | "error";
  t: ReturnType<typeof messagesFor>;
}) {
  if (state === "idle") return null;
  const tone =
    state === "error" ? "text-danger" : state === "saved" ? "text-success" : "text-ink-soft";
  const label =
    state === "saving"
      ? t.actions.saving
      : state === "saved"
        ? t.actions.saved
        : t.actions.saveFailed;
  return <span className={`text-[11px] ${tone}`}>{label}</span>;
}
