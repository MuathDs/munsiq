import Link from "next/link";
import type { ReactNode } from "react";

import type { Org, SystemInfo } from "@/lib/api/types";
import { LOCALE_LABEL, LOCALES, type Locale } from "@/lib/i18n";
import { interpolate, type Messages } from "@/lib/messages";

import { TopBar } from "./TopBar";

/**
 * Only what exists.
 *
 * The prototype's Settings was a nav label with nothing behind it. Everything
 * here is a real value read from the backend, and it is read-only — except the
 * language, which is the one setting the UI actually owns. There is no theme
 * switch, no notification preference, no profile form: none of those have
 * anything behind them, so none of them are here.
 */
export function SettingsView({
  org,
  system,
  locale,
  t,
}: {
  org: Org | null;
  system: SystemInfo | null;
  locale: Locale;
  t: Messages;
}) {
  return (
    <>
      <TopBar title={t.settings.title} subtitle={t.settings.subtitle} />

      <Section title={t.settings.language}>
        <p className="text-[13px] text-ink-soft">{t.settings.languageHint}</p>
        <div className="mt-3 flex gap-2">
          {LOCALES.map((code) => (
            <Link
              key={code}
              href={`/${code}/settings`}
              aria-current={code === locale ? "true" : undefined}
              className={`rounded-[9px] border px-4 py-2 text-[13px] font-semibold transition-colors ${
                code === locale
                  ? "border-accent bg-accent/14 text-ink"
                  : "border-line text-ink-soft hover:bg-surface-hover hover:text-ink"
              }`}
            >
              {LOCALE_LABEL[code]}
            </Link>
          ))}
        </div>
      </Section>

      {org ? (
        <Section title={t.settings.organization}>
          <Rows>
            <Row label={t.settings.orgName}>
              <bdi>{org.name}</bdi>
            </Row>
            {org.vat_number ? (
              <Row label={t.settings.vat} mono>
                {org.vat_number}
              </Row>
            ) : null}
            {org.data_region ? (
              <Row label={t.settings.region} mono>
                {org.data_region}
              </Row>
            ) : null}
          </Rows>
        </Section>
      ) : null}

      {system ? (
        <Section title={t.settings.processing}>
          <Rows>
            <Row label={t.settings.model} mono>
              {system.inference_model}
            </Row>
            <Row label={t.settings.vision}>
              {system.extraction_use_vision ? t.settings.on : t.settings.off}
            </Row>
            <Row label={t.settings.ocr} mono>
              {system.ocr_engine}
            </Row>
            <Row label={t.settings.maxUpload}>
              {interpolate(t.settings.megabytes, {
                count: Math.round(system.max_upload_bytes / (1024 * 1024)),
              })}
            </Row>
            <Row label={t.settings.grounding} mono>
              {system.grounding_threshold}
            </Row>
            <Row label={t.settings.stalledAfter}>
              {interpolate(t.settings.minutes, {
                count: Math.round(system.stalled_after_s / 60),
              })}
            </Row>
            <Row label={t.settings.environment} mono>
              {system.environment}
            </Row>
          </Rows>
        </Section>
      ) : null}
    </>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-[14px] border border-line bg-surface p-5">
      <h2 className="mb-3 text-base font-semibold text-ink">{title}</h2>
      {children}
    </section>
  );
}

function Rows({ children }: { children: ReactNode }) {
  return <dl className="divide-y divide-line">{children}</dl>;
}

function Row({ label, children, mono }: { label: string; children: ReactNode; mono?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-6 py-2.5 first:pt-0 last:pb-0">
      <dt className="text-[13px] text-ink-soft">{label}</dt>
      <dd
        className={`text-[13px] text-ink ${mono ? "tabular font-mono" : ""}`}
        dir={mono ? "ltr" : undefined}
      >
        {children}
      </dd>
    </div>
  );
}
