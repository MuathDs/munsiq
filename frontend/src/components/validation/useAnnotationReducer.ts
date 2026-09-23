"use client";

/**
 * One reducer owns the whole workspace.
 *
 * The payload sent to the server is a batch of correction EVENTS, never the
 * whole annotation. A snapshot PUT would let one reviewer's stale copy silently
 * revert another's work; an event batch describes only what this reviewer
 * actually changed.
 *
 * Edits are optimistic and roll back on failure, because a reviewer typing
 * through forty fields cannot wait on a round trip per keystroke.
 */

import { useCallback, useEffect, useReducer, useRef } from "react";

import {
  currentValue,
  fieldKeyOf,
  type AnnotationDetail,
  type CorrectionEvent,
  type ExtractedField,
  type ValidationFinding,
} from "@/lib/api/types";

/** What the confirm endpoint's 409 body carries per blocking finding — enough
 * to render one item AND key it uniquely, without pulling in the full
 * ValidationFinding shape (severity/passed are implied: every one is an
 * unresolved error, or it would not be here). */
export type ConfirmBlocker = Pick<ValidationFinding, "id" | "rule_code" | "field_key">;

const FLUSH_DELAY_MS = 800;

export type SaveState = "idle" | "saving" | "saved" | "error";

export interface WorkspaceState {
  fields: ExtractedField[];
  findings: ValidationFinding[];
  blockers: string[];
  status: string;
  /** Composite key (`field_key` or `field_key[row]`) of the focused field. */
  focusedKey: string | null;
  hoveredKey: string | null;
  /** Edits made since the last successful flush. */
  pending: Map<string, CorrectionEvent>;
  /** Values as they were before the current unflushed edits, for rollback. */
  rollback: Map<string, string | null>;
  save: SaveState;
  saveError: string | null;
  confirmError: { message: string; blockers: ConfirmBlocker[] } | null;
  confirming: boolean;
}

export type Action =
  | { type: "edit"; field: ExtractedField; value: string | null }
  | { type: "revert"; field: ExtractedField }
  | { type: "focus"; key: string | null }
  | { type: "hover"; key: string | null }
  | { type: "flush:start" }
  | { type: "flush:ok"; detail: Pick<AnnotationDetail, "fields" | "findings" | "blockers"> }
  | { type: "flush:fail"; message: string }
  | { type: "confirm:start" }
  | { type: "confirm:ok" }
  | { type: "confirm:blocked"; message: string; blockers: ConfirmBlocker[] }
  | { type: "confirm:dismiss" }
  | { type: "export:ok" };

export function initialState(detail: AnnotationDetail): WorkspaceState {
  return {
    fields: detail.fields,
    findings: detail.findings,
    blockers: detail.blockers,
    status: detail.status,
    focusedKey: null,
    hoveredKey: null,
    pending: new Map(),
    rollback: new Map(),
    save: "idle",
    saveError: null,
    confirmError: null,
    confirming: false,
  };
}

function withValue(
  fields: ExtractedField[],
  target: ExtractedField,
  value: string | null,
): ExtractedField[] {
  const key = fieldKeyOf(target);
  return fields.map((f) =>
    fieldKeyOf(f) === key ? { ...f, value_final: value, source: "human" as const } : f,
  );
}

export function reducer(state: WorkspaceState, action: Action): WorkspaceState {
  switch (action.type) {
    case "edit": {
      const key = fieldKeyOf(action.field);
      if (currentValue(action.field) === action.value) return state;

      const rollback = new Map(state.rollback);
      // Record the pre-edit value once per flush cycle, so a rollback restores
      // what was there before this batch rather than before the last keystroke.
      if (!rollback.has(key)) rollback.set(key, currentValue(action.field));

      const pending = new Map(state.pending);
      pending.set(key, {
        field_key: action.field.field_key,
        row_index: action.field.row_index,
        new_value: action.value,
        action: "edit",
      });

      return {
        ...state,
        fields: withValue(state.fields, action.field, action.value),
        pending,
        rollback,
        save: "idle",
        saveError: null,
      };
    }

    case "revert": {
      // Esc restores what was extracted, discarding the human correction.
      return reducer(state, {
        type: "edit",
        field: action.field,
        value: action.field.value_extracted,
      });
    }

    case "focus":
      return { ...state, focusedKey: action.key };

    case "hover":
      return { ...state, hoveredKey: action.key };

    case "flush:start":
      return { ...state, save: "saving", saveError: null };

    case "flush:ok":
      // The server is authoritative after a flush: it returns fields with fresh
      // validation_state and the re-run findings, so a correction that cleared
      // a blocker is reflected immediately.
      return {
        ...state,
        fields: action.detail.fields,
        findings: action.detail.findings,
        blockers: action.detail.blockers,
        pending: new Map(),
        rollback: new Map(),
        save: "saved",
        confirmError: null,
      };

    case "flush:fail": {
      // Roll the optimistic edits back rather than leaving the reviewer looking
      // at values the server never accepted.
      const fields = state.fields.map((f) => {
        const key = fieldKeyOf(f);
        return state.rollback.has(key)
          ? { ...f, value_final: state.rollback.get(key) ?? null }
          : f;
      });
      return {
        ...state,
        fields,
        pending: new Map(),
        rollback: new Map(),
        save: "error",
        saveError: action.message,
      };
    }

    case "confirm:start":
      return { ...state, confirming: true, confirmError: null };

    case "confirm:ok":
      return { ...state, confirming: false, status: "confirmed", confirmError: null };

    case "confirm:blocked":
      return {
        ...state,
        confirming: false,
        confirmError: { message: action.message, blockers: action.blockers },
      };

    case "confirm:dismiss":
      return { ...state, confirmError: null };

    case "export:ok":
      // Export is a lifecycle state. Only a confirmed invoice moves to it; an
      // exported one stays exported.
      return state.status === "confirmed" ? { ...state, status: "exported" } : state;
  }
}

/**
 * Debounced flush of the pending event batch.
 *
 * One PATCH per pause, not per keystroke. The timer resets on every edit, so a
 * reviewer moving quickly through a form produces one request rather than
 * dozens — and the server revalidates once instead of once per field.
 */
export function useDebouncedFlush(
  state: WorkspaceState,
  dispatch: React.Dispatch<Action>,
  annotationId: string,
) {
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inFlight = useRef(false);

  const flush = useCallback(async () => {
    if (inFlight.current || state.pending.size === 0) return;
    const events = [...state.pending.values()];
    inFlight.current = true;
    dispatch({ type: "flush:start" });
    try {
      const response = await fetch(`/api/bff/annotations/${annotationId}/fields`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ events }),
      });
      if (!response.ok) throw new Error(`save failed (${response.status})`);
      const detail = (await response.json()) as {
        fields: ExtractedField[];
        findings: ValidationFinding[];
        blockers: string[];
      };
      dispatch({ type: "flush:ok", detail });
    } catch (error) {
      dispatch({
        type: "flush:fail",
        message: error instanceof Error ? error.message : "save failed",
      });
    } finally {
      inFlight.current = false;
    }
  }, [annotationId, dispatch, state.pending]);

  useEffect(() => {
    if (state.pending.size === 0) return;
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => void flush(), FLUSH_DELAY_MS);
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [state.pending, flush]);

  return { flushNow: flush };
}

export function useWorkspace(detail: AnnotationDetail) {
  return useReducer(reducer, detail, initialState);
}
