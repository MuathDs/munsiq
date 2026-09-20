"use client";

import { AlertTriangle, CheckCircle2, X } from "lucide-react";
import type { Toast } from "@/lib/useToasts";

interface ToastStackProps {
  toasts: Toast[];
  onDismiss: (id: string) => void;
}

export function ToastStack({ toasts, onDismiss }: ToastStackProps) {
  if (toasts.length === 0) return null;

  return (
    <div className="fixed bottom-6 end-6 z-50 flex w-[340px] flex-col gap-2">
      {toasts.map((toast) => {
        const isError = toast.variant === "error";
        return (
          <div
            key={toast.id}
            role="alert"
            className={`flex items-start gap-2 rounded-[10px] border bg-surface px-4 py-3 text-[13px] shadow-lg ${
              isError ? "border-warning/30 text-warning" : "border-success/30 text-success"
            }`}
          >
            {isError ? (
              <AlertTriangle size={15} className="shrink-0 mt-0.5" />
            ) : (
              <CheckCircle2 size={15} className="shrink-0 mt-0.5" />
            )}
            <p className="flex-1 text-ink">{toast.message}</p>
            <button onClick={() => onDismiss(toast.id)} className="shrink-0 text-ink-faint">
              <X size={14} />
            </button>
          </div>
        );
      })}
    </div>
  );
}
