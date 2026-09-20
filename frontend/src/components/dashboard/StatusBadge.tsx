import { Check, CircleAlert, Eye, Loader2, ShieldAlert, TriangleAlert } from "lucide-react";

import type { DocumentListItem } from "@/lib/api/types";
import type { Locale } from "@/lib/i18n";
import type { Messages } from "@/lib/messages";

import { categoryOf, type Category } from "./docState";

const STYLE: Record<Category, string> = {
  processing: "bg-line text-ink-soft",
  review: "bg-warning/15 text-warning",
  blocked: "bg-danger/15 text-danger",
  confirmed: "bg-success/15 text-success",
  failed: "bg-danger/15 text-danger",
};

function labelFor(doc: DocumentListItem, category: Category, t: Messages): string {
  if (category === "blocked") return t.status.blocked;
  const known = (t.status as Record<string, string>)[doc.state];
  return known ?? doc.state;
}

export function StatusBadge({
  doc,
  t,
  locale,
}: {
  doc: DocumentListItem;
  t: Messages;
  locale: Locale;
}) {
  const category = categoryOf(doc);
  const Icon = {
    processing: Loader2,
    review: Eye,
    blocked: ShieldAlert,
    confirmed: Check,
    failed: doc.state === "stalled" ? TriangleAlert : CircleAlert,
  }[category];

  // A failed document says why on hover, in the reviewer's language.
  const reason = locale === "ar" ? doc.error_ar : doc.error_en;

  return (
    <span
      title={category === "failed" && reason ? reason : undefined}
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-3 py-1 text-xs font-medium ${STYLE[category]}`}
    >
      <Icon size={12} className={category === "processing" ? "animate-spin" : ""} aria-hidden />
      {labelFor(doc, category, t)}
    </span>
  );
}
