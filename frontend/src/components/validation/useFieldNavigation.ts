"use client";

/**
 * The keyboard path IS the product.
 *
 * A reviewer processes hundreds of documents a day. If they have to reach for
 * the mouse between fields, the tool is slower than the spreadsheet it replaced.
 *
 *   Tab / Shift+Tab   next / previous field
 *   Enter             accept the current value and advance
 *   Esc               revert the current field to what was extracted
 *   Ctrl/Cmd+Enter    confirm the document
 *   Alt+B             jump to the next blocking field
 *   ?                 show the shortcut panel
 */

import { useCallback, useEffect } from "react";

import { fieldKeyOf, type ExtractedField } from "@/lib/api/types";

export interface NavigationHandlers {
  onFocusKey: (key: string) => void;
  onRevert: (field: ExtractedField) => void;
  onConfirm: () => void;
  onToggleHelp: () => void;
}

function isBlocking(field: ExtractedField): boolean {
  return field.validation_state === "blocking";
}

export function useFieldNavigation(
  fields: ExtractedField[],
  focusedKey: string | null,
  handlers: NavigationHandlers,
) {
  const keys = fields.map(fieldKeyOf);

  const move = useCallback(
    (delta: number) => {
      if (keys.length === 0) return;
      const index = focusedKey ? keys.indexOf(focusedKey) : -1;
      // Wrap: reaching the end returns to the top rather than trapping focus.
      const next = (index + delta + keys.length) % keys.length;
      handlers.onFocusKey(keys[next]);
    },
    [keys, focusedKey, handlers],
  );

  const nextBlocker = useCallback(() => {
    const blocking = fields.filter(isBlocking).map(fieldKeyOf);
    if (blocking.length === 0) return;
    const current = focusedKey ? blocking.indexOf(focusedKey) : -1;
    handlers.onFocusKey(blocking[(current + 1) % blocking.length]);
  }, [fields, focusedKey, handlers]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      const typing =
        target?.tagName === "INPUT" ||
        target?.tagName === "TEXTAREA" ||
        target?.isContentEditable;

      // Ctrl/Cmd+Enter confirms from anywhere, including mid-edit — a reviewer
      // who has just fixed the last field should not have to leave it first.
      if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
        event.preventDefault();
        handlers.onConfirm();
        return;
      }

      if (event.altKey && (event.key === "b" || event.key === "B")) {
        event.preventDefault();
        nextBlocker();
        return;
      }

      if (event.key === "Tab") {
        event.preventDefault();
        move(event.shiftKey ? -1 : 1);
        return;
      }

      if (event.key === "Enter" && typing) {
        event.preventDefault();
        move(1);
        return;
      }

      if (event.key === "Escape" && focusedKey) {
        const field = fields.find((f) => fieldKeyOf(f) === focusedKey);
        if (field) {
          event.preventDefault();
          handlers.onRevert(field);
        }
        return;
      }

      // "?" only when not typing — otherwise it would be unreachable in a value.
      if (event.key === "?" && !typing) {
        event.preventDefault();
        handlers.onToggleHelp();
      }
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [fields, focusedKey, handlers, move, nextBlocker]);

  return { move, nextBlocker };
}
