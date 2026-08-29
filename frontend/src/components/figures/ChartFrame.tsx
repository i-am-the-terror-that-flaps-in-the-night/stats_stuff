// The chrome every figure sits in, and the hover layer they all share.
//
// A chart here is an <svg> drawn in a FIXED internal coordinate space (720×360
// or so) and scaled to the container by its viewBox. That is what makes these
// responsive without a resize observer: the maths runs once, in numbers the
// component picked, and the browser handles the rest. The one thing that cannot
// live in SVG space is the tooltip -- it has to be an HTML box positioned in
// real pixels, or its text would scale with the chart and go unreadable on a
// phone. So the tooltip is an absolutely-positioned <div> over the SVG, placed
// from the pointer's position in the container's own coordinates.

import { useCallback, useEffect, useId, useRef, useState } from "react";
import type { JSX, ReactNode, RefObject } from "react";
import { downloadFigure } from "../../lib/svgExport";
import type { ExportFormat } from "../../lib/svgExport";

/**
 * True on a phone-width viewport.
 *
 * This exists because an SVG viewBox scales EVERYTHING, text included. A chart
 * authored 720 units wide and painted into a 330px column is running at 0.46×,
 * so its 10px tick labels render at under 5px — unreadable, and no CSS font-size
 * fixes it, because that size is in the same user units being scaled down.
 * Bumping the font instead breaks the layout, since every label offset in the
 * chart was computed for the original size.
 *
 * The fix is to author a SECOND, smaller coordinate space for narrow screens —
 * roughly 1:1 with the real pixels — so 10 units is 10 pixels again. Each chart
 * picks its layout from this flag; nothing else changes.
 */
export function useNarrowChart(): boolean {
  const query = "(max-width: 560px)";
  const [narrow, setNarrow] = useState(
    () => typeof window !== "undefined" && window.matchMedia(query).matches,
  );
  useEffect(() => {
    const media = window.matchMedia(query);
    const update = (): void => setNarrow(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  return narrow;
}

/** A chart's coordinate space: the viewBox plus its axis gutters. */
export interface Layout {
  W: number;
  H: number;
  margin: { top: number; right: number; bottom: number; left: number };
}

/** What a hovered mark reports: a heading and a few label/value rows. */
export interface TipContent {
  title: string;
  rows: [string, string][];
  /**
   * Optional trailing note, e.g. what the mark excludes. Explicitly `| undefined`
   * because the project runs `exactOptionalPropertyTypes` — a caller that
   * computes the note conditionally passes `undefined`, and under that flag an
   * optional property is not automatically allowed to receive one.
   */
  note?: string | undefined;
}

interface TipState extends TipContent {
  x: number;
  y: number;
}

/**
 * Hover state for one figure.
 *
 * `show` takes the pointer event and the content; position is derived from the
 * event's offset within `currentTarget`, so it works the same whether the mark
 * is a rect, a circle or a table cell, and needs no layout measurement.
 */
export function useTooltip(): {
  tip: TipState | null;
  show: (event: { clientX: number; clientY: number; currentTarget: Element }, content: TipContent) => void;
  hide: () => void;
} {
  const [tip, setTip] = useState<TipState | null>(null);

  const show = useCallback(
    (
      event: { clientX: number; clientY: number; currentTarget: Element },
      content: TipContent,
    ) => {
      // The SVG is the event target, but the tooltip is positioned against the
      // figure container, so measure the box we are actually placing inside.
      const host = event.currentTarget.closest(".fig-plot") ?? event.currentTarget;
      const box = host.getBoundingClientRect();
      setTip({ ...content, x: event.clientX - box.left, y: event.clientY - box.top });
    },
    [],
  );

  const hide = useCallback(() => setTip(null), []);
  return { tip, show, hide };
}

/** The tooltip box itself. Rendered inside `.fig-plot`, which is position:relative. */
export function Tooltip({ tip }: { tip: TipState | null }): JSX.Element | null {
  if (!tip) return null;
  return (
    <div
      className="fig-tip"
      // Inline positioning is unavoidable -- it changes with every pointer move,
      // and a CSS custom property would just be the same value one level out.
      style={{ left: `${tip.x}px`, top: `${tip.y}px` }}
      role="tooltip"
      aria-hidden="true"
    >
      <p className="fig-tip-title">{tip.title}</p>
      {tip.rows.map(([k, v]) => (
        <p className="fig-tip-row" key={k}>
          <span>{k}</span>
          <b>{v}</b>
        </p>
      ))}
      {tip.note && <p className="fig-tip-note">{tip.note}</p>}
    </div>
  );
}

// Every optional slot below is `?: ReactNode` — which already includes
// undefined — so callers may compute them conditionally under
// exactOptionalPropertyTypes without each one needing a `| undefined`.
export interface FigureProps {
  title: string;
  /** One line under the title: what the figure shows and how to read it. */
  caption?: ReactNode;
  /** Right-aligned metadata in the head — n, method, sampling. */
  meta?: ReactNode;
  /** The controls row. Per the house rule, filters sit ABOVE the plot, never beside it. */
  controls?: ReactNode;
  /** A key for encoded marks. Only present when colour or shape carries meaning. */
  legend?: ReactNode;
  /** Rendered under the plot: caveats, what was excluded, the data source. */
  footnote?: ReactNode;
  /**
   * Turns off the PDF/PNG/SVG control. Only for a "figure" that is really a
   * table — there is nothing to export and the buttons would be a dead end.
   */
  noDownload?: boolean;
  children: ReactNode;
}


/**
 * The download control every figure carries.
 *
 * It exports the <svg> that is on screen right now rather than re-drawing the
 * figure from its data, which is what makes the file match what the reader is
 * looking at — the same group selected, the same column, the same marks. The
 * work is in lib/svgExport.ts; this is the button.
 *
 * PDF is listed first because it is the one to take to a printer: it comes out
 * as real vector paths and real text, so it stays sharp at poster size. PNG is
 * for pasting into a slide or a document. SVG is for anyone who wants to open
 * the figure in a drawing program and change it.
 */
function DownloadBar({
  plotRef,
  title,
}: {
  plotRef: RefObject<HTMLDivElement | null>;
  title: string;
}): JSX.Element {
  const [busy, setBusy] = useState<ExportFormat | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(
    async (format: ExportFormat): Promise<void> => {
      // Null when the figure is showing its data table instead of its chart,
      // which is a normal state rather than a fault — say so and do nothing.
      const svg = plotRef.current?.querySelector("svg");
      if (!svg) {
        setError("Show the chart to download it.");
        return;
      }
      setBusy(format);
      setError(null);
      try {
        await downloadFigure(svg as SVGSVGElement, title, format);
      } catch (err: unknown) {
        setError(err instanceof Error ? err.message : "Could not export the figure.");
      } finally {
        setBusy(null);
      }
    },
    [plotRef, title],
  );

  return (
    <span className="fig-save">
      <span className="fig-save-label">Save</span>
      {(["pdf", "png", "svg"] as const).map((format) => (
        <button
          key={format}
          type="button"
          className="fig-save-btn"
          disabled={busy !== null}
          onClick={() => void run(format)}
          title={`Download this figure as ${format.toUpperCase()}`}
        >
          {busy === format ? "…" : format.toUpperCase()}
        </button>
      ))}
      {error && (
        <span className="fig-save-error" role="status">
          {error}
        </span>
      )}
    </span>
  );
}

export function Figure({
  title,
  caption,
  meta,
  controls,
  legend,
  footnote,
  noDownload,
  children,
}: FigureProps): JSX.Element {
  // The download path reads the live <svg> out of the plot, so the frame keeps
  // a handle on it. A ref rather than a query by class: two figures on a page
  // would both match the selector, and the wrong one exports silently.
  const plotRef = useRef<HTMLDivElement | null>(null);
  return (
    <figure className="fig">
      <div className="fig-head">
        <h3 className="fig-title">{title}</h3>
        <span className="fig-head-end">
          {meta && <span className="fig-meta">{meta}</span>}
          {!noDownload && <DownloadBar plotRef={plotRef} title={title} />}
        </span>
      </div>
      {caption && <figcaption className="fig-caption">{caption}</figcaption>}
      {controls && <div className="fig-controls">{controls}</div>}
      {legend && <div className="fig-legend">{legend}</div>}
      <div className="fig-plot" ref={plotRef}>
        {children}
      </div>
      {footnote && <p className="fig-footnote">{footnote}</p>}
    </figure>
  );
}

/** A labelled <select>. The figures' only input type, so it is declared once. */
export function Picker({
  label,
  value,
  options,
  onChange,
  allowNone,
  noneLabel = "None",
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (next: string) => void;
  /** Adds an empty option — used by the group picker, where "no split" is valid. */
  allowNone?: boolean;
  noneLabel?: string;
}): JSX.Element {
  // useId, not a slug of the label. Slugging stripped every non-ASCII character,
  // so a picker labelled "α" got the id "pick-" — and two such pickers on a page
  // would share it, pointing both <label for> attributes at the same control.
  const id = useId();
  return (
    <span className="fig-pick">
      <label className="fig-pick-label" htmlFor={id}>
        {label}
      </label>
      <select
        id={id}
        className="fig-pick-input"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        {allowNone && <option value="">{noneLabel}</option>}
        {options.map((option) => (
          <option value={option} key={option}>
            {option}
          </option>
        ))}
      </select>
    </span>
  );
}

/**
 * Axis furniture. Grid lines and tick text are deliberately recessive -- they
 * are a reading aid, not data, and a dark grid competes with the marks it exists
 * to support.
 */
export function GridLine({
  x1,
  x2,
  y1,
  y2,
}: {
  x1: number;
  x2: number;
  y1: number;
  y2: number;
}): JSX.Element {
  return <line className="fig-grid" x1={x1} x2={x2} y1={y1} y2={y2} />;
}

export function AxisLabel({
  x,
  y,
  children,
  anchor = "middle",
  className = "",
}: {
  x: number;
  y: number;
  children: ReactNode;
  anchor?: "start" | "middle" | "end";
  className?: string;
}): JSX.Element {
  return (
    <text className={`fig-axis-text ${className}`.trim()} x={x} y={y} textAnchor={anchor}>
      {children}
    </text>
  );
}
