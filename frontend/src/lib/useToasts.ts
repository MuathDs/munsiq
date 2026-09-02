"use client";

import { useCallback, useRef, useState } from "react";

export interface Toast {
  id: string;
  message: string;
  variant: "error" | "success";
}

const TOAST_DURATION_MS = 6000;

export function useToasts() {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const counter = useRef(0);

  const dismissToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const pushToast = useCallback(
    (message: string, variant: Toast["variant"] = "error") => {
      const id = `toast-${++counter.current}`;
      setToasts((prev) => [...prev, { id, message, variant }]);
      setTimeout(() => dismissToast(id), TOAST_DURATION_MS);
    },
    [dismissToast],
  );

  return { toasts, pushToast, dismissToast };
}
