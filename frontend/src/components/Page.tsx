// Shared page furniture.
//
// Every route is built from the same parts in the same order: crumbs, a
// masthead, an optional ribbon of headline figures, then numbered modules. That
// markup used to be copy-pasted into each page (it was hand-written HTML once),
// which meant five slightly different versions of the same header drifting apart
// over time. Declaring it once here is what keeps the routes symmetrical: a
// route file supplies content, never chrome.

import type { JSX, ReactNode } from "react";
import { Link } from "react-router";

/** One key/value row in the masthead's right-hand nameplate. */
export interface SpecRow {
  k: string;
  v: ReactNode;
}

/** One headline figure in the ribbon. */
export interface RibbonCell {
  /** The figure itself. A `small` unit inside reads as "0.6 ms". */
  v: ReactNode;
  k: string;
}

/** One labelled cell in a stat grid. */
export interface StatCell {
  k: string;
  v: ReactNode;
  note?: string;
}

/**
 * Breadcrumbs. Uses <Link>, not <a>: these used to be relative hrefs like
 * "../../" carried over from the multi-document site, which under the router
 * would trigger a full document reload (and resolve to the wrong path anyway).
 */
export function Crumbs({ here }: { here: string }): JSX.Element {
  return (
    <p className="crumbs">
      <Link to="/">Overview</Link>
      <span className="sep">/</span>
      <b>{here}</b>
    </p>
  );
}

export interface MastheadProps {
  eyebrow: string;
  title: string;
  tagline?: ReactNode;
  byline?: string;
  spec?: SpecRow[];
  specLabel?: string;
}

export function Masthead({
  eyebrow,
  title,
  tagline,
  byline,
  spec,
  specLabel = "Specification",
}: MastheadProps): JSX.Element {
  return (
    <header className="masthead">
      <div className="masthead-main">
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        {tagline && <p className="tagline">{tagline}</p>}
        {byline && <p className="byline">{byline}</p>}
      </div>
      {spec && spec.length > 0 && (
        <dl className="masthead-spec" aria-label={specLabel}>
          {spec.map((row) => (
            <div className="spec-row" key={row.k}>
              <dt className="spec-k">{row.k}</dt>
              <dd className="spec-v">{row.v}</dd>
            </div>
          ))}
        </dl>
      )}
    </header>
  );
}

export function Ribbon({
  cells,
  label = "At a glance",
}: {
  cells: RibbonCell[];
  label?: string;
}): JSX.Element {
  return (
    <div className="ribbon" aria-label={label}>
      {cells.map((cell) => (
        <div className="ribbon-cell" key={cell.k}>
          <p className="ribbon-v">{cell.v}</p>
          <p className="ribbon-k">{cell.k}</p>
        </div>
      ))}
    </div>
  );
}

export interface ModuleProps {
  /** The two-digit index in the module head. Modules are numbered per page. */
  index: string;
  title: string;
  meta?: ReactNode;
  children: ReactNode;
}

export function Module({ index, title, meta, children }: ModuleProps): JSX.Element {
  // Derive the heading id from the title so aria-labelledby is wired up without
  // every caller having to invent and pass a unique string.
  const id = `mod-${title.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
  return (
    <section className="module" aria-labelledby={id}>
      <div className="module-head">
        <span className="module-index">{index}</span>
        <span className="module-tick" aria-hidden="true" />
        <h2 id={id} className="module-title">
          {title}
        </h2>
        {meta && <span className="module-meta">{meta}</span>}
      </div>
      <div className="module-body">{children}</div>
    </section>
  );
}

export function StatGrid({ cells }: { cells: StatCell[] }): JSX.Element {
  return (
    <div className="stat-grid">
      {cells.map((cell) => (
        <div className="stat-cell" key={cell.k}>
          <p className="stat-k">{cell.k}</p>
          <p className="stat-v">{cell.v}</p>
          {cell.note && <p className="stat-note">{cell.note}</p>}
        </div>
      ))}
    </div>
  );
}

/**
 * A ruled content table (`.sheet`). The first cell of each row is its row key,
 * matching how the hand-written pages marked up their left-hand column.
 *
 * Deliberately NOT `.matrix`: that class is the heat-shaded comparison grid in
 * ResultView, and it styles its row headers as `.matrix-row-label`. `.rowkey` is
 * only styled under `.sheet`, so borrowing the wrong table class silently drops
 * the bold left column. Content tables use this; the result matrix uses that.
 *
 * `numeric` marks the columns that should right-align with tabular figures --
 * a column of durations reads much better than the same numbers ragged-left.
 * Indices count the row-key column as 0.
 *
 * Always wrapped so a wide table scrolls inside itself rather than stretching
 * the page.
 */
export function Table({
  head,
  rows,
  corner,
  caption,
  numeric,
}: {
  head: string[];
  rows: ReactNode[][];
  corner?: string;
  caption?: string;
  numeric?: number[];
}): JSX.Element {
  const isNum = (index: number): boolean => numeric?.includes(index) ?? false;
  return (
    <div className="results-scroll">
      <table className="sheet">
        {caption && <caption>{caption}</caption>}
        <thead>
          <tr>
            {corner !== undefined && <th>{corner}</th>}
            {head.map((h, i) => (
              <th className={isNum(i + (corner === undefined ? 0 : 1)) ? "num" : undefined} key={h}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {row.map((cell, j) => (
                <td className={j === 0 ? "rowkey" : isNum(j) ? "num" : undefined} key={j}>
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** A definition list of term/description pairs. */
export function Legend({
  rows,
}: {
  rows: { term: string; tag?: string; def: ReactNode }[];
}): JSX.Element {
  return (
    <dl className="legend">
      {rows.map((row) => (
        <div className="legend-row" key={row.term}>
          <dt className="legend-term">
            {row.term}
            {row.tag && <span className="legend-tag">{row.tag}</span>}
          </dt>
          <dd className="legend-def">{row.def}</dd>
        </div>
      ))}
    </dl>
  );
}

/** An error or status line, used identically by every data-backed route. */
export function Status({
  message,
  isError = false,
}: {
  message: string;
  isError?: boolean;
}): JSX.Element {
  return (
    <p className={`status${isError ? " error" : ""}`} role="status" aria-live="polite">
      {message}
    </p>
  );
}
