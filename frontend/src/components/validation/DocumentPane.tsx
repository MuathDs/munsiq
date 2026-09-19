"use client";

/**
 * The document, fitted to its pane, with every grounded value outlined.
 *
 * FIT. The page is sized to the pane so a reviewer sees the whole invoice at
 * once rather than the top two thirds of an overflowing page. Zoom is for
 * detail, not for finding the page.
 *
 * The fit is pure CSS: the pane is a size container, and the page's width is
 * `min(pane width, pane height ÷ aspect ratio)` in container units. No
 * ResizeObserver, no measured state — so it is right on the server render, on
 * the first paint, and in a background tab, where an observer never fires.
 *
 * OVERLAY. An SVG with `viewBox="0 0 1 1"` and `preserveAspectRatio="none"`, so
 * a normalized 0–1 bounding box is placed with no arithmetic: x0 is x, y0 is y,
 * and the box scales with the page at any zoom. That is the entire reason boxes
 * are stored normalized rather than in pixels.
 *
 * Coordinates here are PHYSICAL on purpose. A page image does not mirror in an
 * RTL interface — the invoice's top-left is its top-left in either language — so
 * page geometry is the one place in this UI that must not follow `dir`.
 */

import { Maximize, Minus, Plus } from "lucide-react";
import { useState } from "react";
import { TransformComponent, TransformWrapper } from "react-zoom-pan-pinch";

import { fieldKeyOf, type ExtractedField, type PageInfo } from "@/lib/api/types";
import type { Messages } from "@/lib/messages";

interface Props {
  pages: PageInfo[];
  fields: ExtractedField[];
  focusedKey: string | null;
  hoveredKey: string | null;
  onSelect: (key: string) => void;
  onHover: (key: string | null) => void;
  t: Messages;
}

/** Space kept clear on every side of the page. */
const PAGE_GUTTER = 32;
/** Room kept free at the bottom for the floating zoom control. */
const TOOLBAR_RESERVE = 56;
const MIN_PAGE_WIDTH = 240;
/** Breathing room around each box, so the outline does not sit on the glyphs. */
const PAD_X = 0.006;
const PAD_Y = 0.004;
/** A4 portrait, for a page the rasterizer did not record dimensions for. */
const A4_RATIO = 842 / 595;

/** Outline colour follows provenance, matching the badge in the field pane. */
function colourFor(field: ExtractedField): string {
  if (field.validation_state === "blocking") return "var(--color-danger)";
  switch (field.source) {
    case "ubl_xml":
      return "var(--color-success)";
    case "human":
      return "var(--color-accent-strong)";
    case "vlm":
      return "var(--color-warning)";
    default:
      return "var(--color-ink-faint)";
  }
}

function ratioOf(page: PageInfo): number {
  return page.width_px && page.height_px ? page.height_px / page.width_px : A4_RATIO;
}

/** The page's CSS width: as large as the pane allows in both directions. */
function fitWidth(ratio: number): string {
  const byWidth = `100cqw - ${PAGE_GUTTER * 2}px`;
  const byHeight = `(100cqh - ${PAGE_GUTTER * 2 + TOOLBAR_RESERVE}px) / ${ratio.toFixed(4)}`;
  return `max(${MIN_PAGE_WIDTH}px, min(${byWidth}, ${byHeight}))`;
}

export function DocumentPane({ pages, fields, focusedKey, hoveredKey, onSelect, onHover, t }: Props) {
  const [scale, setScale] = useState(1);

  if (pages.length === 0) {
    return (
      <div className="doc-canvas flex h-full items-center justify-center p-8 text-sm text-ink-soft">
        {t.workspace.noPages}
      </div>
    );
  }

  const activeKey = hoveredKey ?? focusedKey;

  return (
    <div className="doc-canvas relative h-full overflow-hidden" style={{ containerType: "size" }}>
      <TransformWrapper
        initialScale={1}
        minScale={0.5}
        maxScale={6}
        doubleClick={{ disabled: true }}
        wheel={{ step: 0.08 }}
        onTransformed={(_, state) => setScale(state.scale)}
      >
        {({ zoomIn, zoomOut, resetTransform }) => (
          <>
            <TransformComponent
              wrapperClass="!h-full !w-full"
              contentClass="!w-full !min-h-full flex flex-col items-center justify-center gap-6 py-8"
            >
              {pages.map((page) => (
                <PageCanvas
                  key={page.page_number}
                  page={page}
                  fields={fields.filter((f) => f.bbox?.page === page.page_number)}
                  activeKey={activeKey}
                  onSelect={onSelect}
                  onHover={onHover}
                  t={t}
                />
              ))}
            </TransformComponent>

            <div className="pointer-events-none absolute inset-x-0 bottom-5 z-10 flex justify-center">
              <div className="pointer-events-auto flex items-center gap-0.5 rounded-full border border-line-strong bg-surface/95 p-1 shadow-lg backdrop-blur">
                <ToolButton onClick={() => zoomOut()} label={t.workspace.zoomOut}>
                  <Minus size={15} />
                </ToolButton>
                <span className="tabular w-12 text-center font-mono text-[12px] text-ink-soft">
                  {Math.round(scale * 100)}%
                </span>
                <ToolButton onClick={() => zoomIn()} label={t.workspace.zoomIn}>
                  <Plus size={15} />
                </ToolButton>
                <span className="mx-1 h-5 w-px bg-line" aria-hidden />
                <ToolButton onClick={() => resetTransform()} label={t.workspace.fit}>
                  <Maximize size={14} />
                </ToolButton>
              </div>
            </div>
          </>
        )}
      </TransformWrapper>
    </div>
  );
}

function ToolButton({
  onClick,
  label,
  children,
}: {
  onClick: () => void;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      className="flex h-8 w-8 items-center justify-center rounded-full text-ink-soft transition-colors hover:bg-surface-hover hover:text-ink"
    >
      {children}
    </button>
  );
}

function PageCanvas({
  page,
  fields,
  activeKey,
  onSelect,
  onHover,
  t,
}: {
  page: PageInfo;
  fields: ExtractedField[];
  activeKey: string | null;
  onSelect: (key: string) => void;
  onHover: (key: string | null) => void;
  t: Messages;
}) {
  const ratio = ratioOf(page);

  return (
    <figure className="relative shrink-0" style={{ width: fitWidth(ratio) }}>
      <div
        className="relative w-full overflow-hidden rounded-[4px] bg-white shadow-[0_24px_60px_-16px_oklch(0_0_0/70%)] ring-1 ring-line-strong"
        style={{ aspectRatio: `1 / ${ratio}` }}
      >
        {page.image_url ? (
          // A plain <img>: the URL is a short-lived signed token served by the
          // backend, so it must not go through the Next image optimizer, which
          // would cache it past its expiry.
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={page.image_url}
            alt={`${t.workspace.page} ${page.page_number}`}
            className="absolute inset-0 h-full w-full object-contain"
            draggable={false}
          />
        ) : null}

        <svg
          className="absolute inset-0 h-full w-full"
          viewBox="0 0 1 1"
          preserveAspectRatio="none"
          role="presentation"
        >
          {fields.map((field) => {
            const box = field.bbox;
            if (!box) return null;
            const key = fieldKeyOf(field);
            const active = key === activeKey;
            const dimmed = activeKey !== null && !active;
            const colour = colourFor(field);
            const x = Math.max(0, box.x0 - PAD_X);
            const y = Math.max(0, box.y0 - PAD_Y);
            return (
              <rect
                key={key}
                x={x}
                y={y}
                width={Math.max(0, Math.min(1, box.x1 + PAD_X) - x)}
                height={Math.max(0, Math.min(1, box.y1 + PAD_Y) - y)}
                fill={colour}
                fillOpacity={active ? 0.26 : dimmed ? 0.04 : 0.13}
                stroke={colour}
                strokeOpacity={active ? 1 : dimmed ? 0.35 : 0.85}
                strokeWidth={active ? 2 : 1.25}
                // Boxes live in a 0–1 space, so a scalar stroke would stretch with
                // the aspect ratio. This keeps the outline an even hairline.
                vectorEffect="non-scaling-stroke"
                className="cursor-pointer transition-[fill-opacity,stroke-opacity]"
                onClick={() => onSelect(key)}
                onMouseEnter={() => onHover(key)}
                onMouseLeave={() => onHover(null)}
              />
            );
          })}
        </svg>
      </div>
      <figcaption className="tabular mt-2 text-center font-mono text-[11px] text-ink-faint">
        {page.page_number}
      </figcaption>
    </figure>
  );
}
