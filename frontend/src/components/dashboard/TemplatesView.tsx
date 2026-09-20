import { CircleCheck, History } from "lucide-react";

import type { SchemaField, Template } from "@/lib/api/types";
import type { Locale } from "@/lib/i18n";
import { interpolate, type Messages } from "@/lib/messages";

import { TopBar } from "./TopBar";

/**
 * The extraction schemas, read straight from `extraction_schemas`.
 *
 * Read-only on purpose: the schema decides what the model is asked for and what
 * the review screen and the export call each field, so editing one deserves its
 * own design (versioning, a diff, a dry run) rather than a text box bolted onto a
 * list. Today a new field is a database edit, and a new row with a higher version
 * becomes what the pipeline reads.
 */
export function TemplatesView({
  templates,
  locale,
  t,
}: {
  templates: Template[];
  locale: Locale;
  t: Messages;
}) {
  return (
    <>
      <TopBar title={t.templates.title} subtitle={t.templates.subtitle} />
      {templates.length === 0 ? (
        <p className="rounded-[14px] border border-line bg-surface px-6 py-12 text-center text-sm text-ink-soft">
          {t.templates.empty}
        </p>
      ) : (
        <div className="flex flex-col gap-5">
          {templates.map((template) => (
            <TemplateCard key={template.id} template={template} locale={locale} t={t} />
          ))}
        </div>
      )}
    </>
  );
}

function labelOf(field: SchemaField, locale: Locale): string {
  const own = locale === "ar" ? field.label_ar : field.label_en;
  return own || field.label_en || field.label_ar || field.key;
}

function TemplateCard({
  template,
  locale,
  t,
}: {
  template: Template;
  locale: Locale;
  t: Messages;
}) {
  const header = template.fields.filter((field) => !field.line_item);
  const lines = template.fields.filter((field) => field.line_item);

  return (
    <section className="rounded-[14px] border border-line bg-surface">
      <header className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line px-5 py-4">
        <h2 className="text-base font-semibold text-ink">
          <bdi>{template.name ?? t.templates.title}</bdi>
        </h2>
        {template.in_use ? (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-success/15 px-2.5 py-1 text-xs font-medium text-success">
            <CircleCheck size={12} aria-hidden />
            {t.templates.inUse}
          </span>
        ) : (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-line px-2.5 py-1 text-xs font-medium text-ink-soft">
            <History size={12} aria-hidden />
            {t.templates.older}
          </span>
        )}
        <p className="tabular ms-auto flex flex-wrap items-center gap-x-4 text-xs text-ink-soft">
          <span>{interpolate(t.templates.version, { n: template.version })}</span>
          {template.queue_name ? (
            <span>
              {t.templates.queue}: <bdi>{template.queue_name}</bdi>
            </span>
          ) : null}
          <span>{interpolate(t.templates.fieldCount, { count: template.fields.length })}</span>
        </p>
      </header>

      <FieldTable title={t.templates.fields} fields={header} locale={locale} t={t} />
      {lines.length > 0 ? (
        <FieldTable title={t.templates.lineItems} fields={lines} locale={locale} t={t} />
      ) : null}
    </section>
  );
}

function FieldTable({
  title,
  fields,
  locale,
  t,
}: {
  title: string;
  fields: SchemaField[];
  locale: Locale;
  t: Messages;
}) {
  return (
    <div className="overflow-x-auto border-t border-line first:border-t-0">
      <table className="w-full min-w-[560px] text-start text-sm">
        <caption className="px-5 pb-1 pt-3 text-start text-xs font-semibold uppercase tracking-wide text-ink-faint">
          {title}
        </caption>
        <thead>
          <tr className="text-xs text-ink-faint">
            <th className="px-5 py-2 text-start font-medium">{t.templates.label}</th>
            <th className="px-5 py-2 text-start font-medium">{t.templates.key}</th>
            <th className="px-5 py-2 text-start font-medium">{t.templates.type}</th>
            <th className="px-5 py-2 text-start font-medium">{t.templates.required}</th>
          </tr>
        </thead>
        <tbody>
          {fields.map((field) => (
            <tr key={field.key} className="border-t border-line">
              <td className="px-5 py-2.5 text-ink">{labelOf(field, locale)}</td>
              <td className="px-5 py-2.5 font-mono text-xs text-ink-soft" dir="ltr">
                {field.key}
              </td>
              <td className="px-5 py-2.5 font-mono text-xs text-ink-soft" dir="ltr">
                {field.type}
              </td>
              <td className="px-5 py-2.5 text-xs text-ink-soft">
                {field.required ? t.templates.yes : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
