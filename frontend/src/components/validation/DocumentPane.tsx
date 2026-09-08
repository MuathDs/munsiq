"use client";

/**
 * The document, with the extracted regions drawn over it.
 *
 * The overlay is an SVG with `viewBox="0 0 1 1"` and
 * `preserveAspectRatio="none"`, so a normalized 0–1 bounding box is placed with
 * no arithmetic at all: x0 is x, y0 is y, and the box scales with the image at
 * any zoom level. That is the entire reason boxes are stored normalized rather
 * than in pixels.
 */

import { Maximize2, ZoomIn, ZoomOut } from "lucide-react";
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

function strokeFor(field: ExtractedField, active: boolean): string {
  if (active) return "var(--color-accent-strong)";
  if (field.validation_state === "blocking") return "var(--color-danger)";
  if (field.source === "ubl_xml") return "var(--color-success)";
  return "var(--color-warning)";
}

export function DocumentPane({
  pages,
  fields,
  focusedKey,
  hoveredKey,
  onSelect,
  onHover,
  t,
}: Props) {
  if (pages.length === 0) {
    return (
      <div className="flex h-full items-center justify-center p-8 text-sm text-ink-soft">
        {t.workspace.noPages}
      </div>
    );
  }

  return (
    <TransformWrapper
      initialScale={1}
      minScale={0.5}
      maxScale={6}
      centerOnInit
      doubleClick={{ disabled: true }}
      wheel={{ step: 0.08 }}
    >
      {({ zoomIn, zoomOut, resetTransform }) => (
        <div className="relative h-full overflow-hidden bg-sidebar">
          {/* Controls are positioned with logical insets, so they sit in the
              trailing corner in both directions without a locale branch. */}
          <div className="absolute top-3 end-3 z-10 flex gap-1 rounded-lg border border-line bg-surface/90 p-1 backdrop-blur">
            <ControlButton onClick={() => zoomIn()} label="+">
              <ZoomIn size={15} />
            </ControlButton>
            <ControlButton onClick={() => zoomOut()} label="−">
              <ZoomOut size={15} />
            </ControlButton>
            <ControlButton onClick={() => resetTransform()} label="reset">
              <Maximize2 size={15} />
            </ControlButton>
          </div>

          <TransformComponent
            wrapperClass="!h-full !w-full"
            contentClass="!h-full !w-full flex flex-col items-center gap-4 py-4"
          >
            {pages.map((page) => (
              <PageCanvas
                key={page.page_number}
                page={page}
                fields={fields.filter((f) => f.bbox?.page === page.page_number)}
                focusedKey={focusedKey}
                hoveredKey={hoveredKey}
                onSelect={onSelect}
                onHover={onHover}
                t={t}
              />
            ))}
          </TransformComponent>
        </div>
      )}
    </TransformWrapper>
  );
}

function ControlButton({
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
      className="flex h-7 w-7 items-center justify-center rounded-md text-ink-soft hover:bg-surface-hover hover:text-ink"
    >
      {children}
    </button>
  );
}

function PageCanvas({
  page,
  fields,
  focusedKey,
  hoveredKey,
  onSelect,
  onHover,
  t,
}: {
  page: PageInfo;
  fields: ExtractedField[];
  focusedKey: string | null;
  hoveredKey: string | null;
  onSelect: (key: string) => void;
  onHover: (key: string | null) => void;
  t: Messages;
}) {
  const ratio =
    page.width_px && page.height_px ? page.height_px / page.width_px : 842 / 595;

  return (
    <figure className="relative w-[min(92%,780px)] shadow-lg">
      <div className="relative w-full" style={{ paddingBottom: `${ratio * 100}%` }}>
        {page.image_url ? (
          // Deliberately a plain <img>: the URL is a short-lived signed token
          // served by the backend, so it must not be routed through the Next
          // image optimizer (which would cache it past its expiry).
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={page.image_url}
            alt={`${t.workspace.page} ${page.page_number}`}
            className="absolute inset-0 h-full w-full bg-white object-contain"
            draggable={false}
          />
        ) : (
          <div className="absolute inset-0 bg-surface" />
        )}

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
            const active = key === focusedKey || key === hoveredKey;
            return (
              <rect
                key={key}
                x={box.x0}
                y={box.y0}
                width={Math.max(0, box.x1 - box.x0)}
                height={Math.max(0, box.y1 - box.y0)}
                fill={active ? "var(--color-accent)" : "transparent"}
                fillOpacity={active ? 0.22 : 0}
                stroke={strokeFor(field, active)}
                strokeWidth={active ? 0.004 : 0.002}
                // Boxes are drawn in a 0–1 space, so a scalar stroke would be
                // stretched by the aspect ratio. This keeps it even.
                vectorEffect="non-scaling-stroke"
                className="cursor-pointer transition-[fill-opacity]"
                onClick={() => onSelect(key)}
                onMouseEnter={() => onHover(key)}
                onMouseLeave={() => onHover(null)}
              />
            );
          })}
        </svg>
      </div>
      <figcaption className="tabular mt-1 text-center text-[11px] text-ink-faint">
        {t.workspace.page} {page.page_number}
      </figcaption>
    </figure>
  );
}
