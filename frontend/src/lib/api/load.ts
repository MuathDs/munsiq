import "server-only";

import { ApiError } from "./server";

export type Loaded<T> = { ok: true; data: T } | { ok: false; detail: string };

/**
 * Run a backend read and keep the failure as data.
 *
 * A page whose backend call fails should still render its shell and say why —
 * not throw to the framework's error page, which tells a reviewer nothing about
 * the one thing they can fix (the backend is down, or the BFF env is unset).
 */
export async function attempt<T>(read: () => Promise<T>): Promise<Loaded<T>> {
  try {
    return { ok: true, data: await read() };
  } catch (error) {
    if (error instanceof ApiError) {
      const body =
        typeof error.body === "object" && error.body !== null ? JSON.stringify(error.body) : "";
      return { ok: false, detail: `${error.status} ${error.message} ${body}`.trim() };
    }
    return { ok: false, detail: error instanceof Error ? error.message : String(error) };
  }
}
