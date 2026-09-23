// A label with its definition on hover, focus or tap.
//
// The site prints a lot of vocabulary -- "kurtosis", "VIF", "standardized β",
// "HbA1c" -- and a reader who blanks on one of them should not have to leave
// the number to find out. <Term> looks the label up in lib/glossary; if there
// is an entry it draws the word with a dotted underline and shows the
// definition in a small card beside it. If there is no entry it renders the
// children untouched, so it is safe to wrap every label on the site.
//
// THE CARD IS A PORTAL ON <body>, AND HAS TO BE.
//   Two separate things make an in-place card wrong. The labels sit inside
//   stat grids, result panels and .results-scroll tables that clip overflow,
//   so an absolutely positioned card is cut off at the cell edge. And
//   position:fixed does not fix that either: .results, .module-head and
//   .step-panel all run `animation: rise ... both`, and an element with a
//   transform animation in effect becomes the containing block for its fixed
//   descendants -- so a card measured against the viewport renders offset by
//   wherever that panel happens to sit. Portalling to <body> escapes both,
//   because <body> is nobody's transformed descendant.
//
//   The cost is that `.term:hover .term-tip` can no longer show it: the card is
//   not a descendant of the word any more. Visibility is React state instead,
//   which is also what makes Escape and the scroll re-measure possible.

import type { CSSProperties, JSX, ReactNode } from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { lookup } from "../lib/glossary";

/** Card width, matched by .term-tip's max-width. */
const WIDTH = 320;
/** Enough room for the tallest card; below this it flips above the word. */
const HEIGHT = 190;
const GAP = 8;
const EDGE = 12;

/** The card currently open, so a second one closes the first.
 *
 * Without this, two cards can sit on screen at once: mouseleave does not fire
 * if the pointer leaves the window, and a focused label keeps its card while
 * the mouse opens another. One definition at a time is the whole idea. */
let openCard: (() => void) | null = null;

export function Term({
  k,
  children,
  className,
}: {
  /** The label to look up. Defaults to the children when they are a string. */
  k?: string;
  children: ReactNode;
  className?: string;
}): JSX.Element {
  const key = k ?? (typeof children === "string" ? children : "");
  const entry = key ? lookup(key) : null;
  const ref = useRef<HTMLSpanElement | null>(null);
  const [pos, setPos] = useState<CSSProperties | null>(null);

  // Stable identity: the singleton below compares functions, and a fresh
  // closure each render would make "am I the open one?" always false.
  const close = useCallback((): void => {
    if (openCard === close) openCard = null;
    setPos(null);
  }, []);

  const place = useCallback((): void => {
    const el = ref.current;
    if (!el) return;
    if (openCard && openCard !== close) openCard();
    openCard = close;
    const rect = el.getBoundingClientRect();
    const width = Math.min(WIDTH, window.innerWidth - EDGE * 2);
    // Hug the word's left edge, but never hang off the right of the viewport.
    const left = Math.min(Math.max(EDGE, rect.left), window.innerWidth - EDGE - width);
    // Below the word by default; above it when there is no room below.
    const below = rect.bottom + GAP;
    const above = rect.top - GAP;
    const fitsBelow = below + HEIGHT <= window.innerHeight - EDGE;
    setPos(
      fitsBelow
        ? { left, top: below, width }
        : { left, bottom: Math.max(EDGE, window.innerHeight - above), width },
    );
  }, [close]);


  // While the card is open, follow the word: any scroll (including inside the
  // tables the labels live in, hence capture) re-measures, and Escape dismisses
  // it for keyboard users, who cannot "move the mouse away".
  useEffect(() => close, [close]);

  useEffect(() => {
    if (!pos) return;
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === "Escape") close();
    };
    window.addEventListener("scroll", place, { passive: true, capture: true });
    window.addEventListener("resize", place, { passive: true });
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("scroll", place, { capture: true });
      window.removeEventListener("resize", place);
      window.removeEventListener("keydown", onKey);
    };
  }, [pos !== null, close, place]);

  if (!entry) return <>{children}</>;

  return (
    <span
      ref={ref}
      className={`term${className ? ` ${className}` : ""}`}
      tabIndex={0}
      onMouseEnter={place}
      onMouseLeave={close}
      onFocus={place}
      onBlur={close}
    >
      <span className="term-label">{children}</span>
      {pos !== null &&
        createPortal(
          <span className="term-tip" role="tooltip" style={pos}>
            <b className="term-tip-head">
              {entry.term}
              {entry.unit && <i className="term-tip-unit">{entry.unit}</i>}
            </b>
            {entry.def}
          </span>,
          document.body,
        )}
    </span>
  );
}

/**
 * A boxed plain-language helper: "what this means" under a control or a
 * table. Distinct from .footnote (a caveat) -- this is the friendly reading
 * for someone who is unsure, so it sits before the data it explains.
 */
export function Hint({
  title = "In plain words",
  children,
}: {
  title?: string;
  children: ReactNode;
}): JSX.Element {
  return (
    <aside className="hint">
      <span className="hint-k">{title}</span>
      <div className="hint-v">{children}</div>
    </aside>
  );
}
