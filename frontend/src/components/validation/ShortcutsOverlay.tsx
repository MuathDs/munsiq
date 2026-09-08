"use client";

import { X } from "lucide-react";

import type { Messages } from "@/lib/messages";

const KEYS: { combo: string[]; key: keyof Messages["shortcuts"] }[] = [
  { combo: ["Tab"], key: "nextField" },
  { combo: ["Shift", "Tab"], key: "prevField" },
  { combo: ["Enter"], key: "accept" },
  { combo: ["Esc"], key: "revert" },
  { combo: ["Ctrl", "Enter"], key: "confirm" },
  { combo: ["Alt", "B"], key: "nextBlocker" },
  { combo: ["?"], key: "help" },
];

export function ShortcutsOverlay({ t, onClose }: { t: Messages; onClose: () => void }) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      role="dialog"
      aria-modal="true"
      aria-label={t.shortcuts.title}
      onClick={onClose}
    >
      <div
        className="w-full max-w-sm rounded-xl border border-line-strong bg-surface p-4"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-ink">{t.shortcuts.title}</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label={t.actions.close}
            className="rounded-md p-1 text-ink-faint hover:bg-surface-hover hover:text-ink"
          >
            <X size={15} />
          </button>
        </div>

        <dl className="mt-3 space-y-1.5">
          {KEYS.map(({ combo, key }) => (
            <div key={key} className="flex items-center justify-between gap-4">
              <dt className="text-xs text-ink-soft">{t.shortcuts[key]}</dt>
              <dd className="flex shrink-0 gap-1">
                {combo.map((part) => (
                  <kbd
                    key={part}
                    className="rounded border border-line-strong bg-bg px-1.5 py-0.5 font-mono text-[10px] text-ink"
                  >
                    {part}
                  </kbd>
                ))}
              </dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  );
}
