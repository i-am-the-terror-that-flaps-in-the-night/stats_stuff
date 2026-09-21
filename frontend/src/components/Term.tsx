// A label with its definition on hover, focus or tap.
//
// The site prints a lot of vocabulary -- "kurtosis", "VIF", "standardized β",
// "HbA1c" -- and a reader who blanks on one of them should not have to leave
// the number to find out. <Term> looks the label up in lib/glossary; if there
// is an entry it draws the word with a dotted underline and shows the
// definition in a small card beneath it. If there is no entry it renders the
// children untouched, so it is safe to wrap every label on the site.
//
// Keyboard and touch both work: the wrapper is focusable, and the card is shown
// on :hover and :focus-within alike. The card is position:fixed with its
// coordinates measured on hover, because the labels live inside stat grids,
// result panels and scrolling tables that clip overflow -- an absolutely
// positioned card would be cut off at the cell edge. It flips to hang off the
// right edge when it would otherwise leave the viewport.

import type { JSX, ReactNode } from "react";
import type React from "react";
import { useEffect, useRef, useState } from "react";
import { lookup } from "../lib/glossary";

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
  const [pos, setPos] = useState<React.CSSProperties>({});
  const [shown, setShown] = useState(false);

  const place = (): void => {
    const el = ref.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const width = Math.min(320, window.innerWidth * 0.82);
    const flip = rect.left + width > window.innerWidth - 12;
    const below = rect.bottom + 8;
    // Hang above the word when it sits in the bottom quarter of the screen.
    const up = below + 160 > window.innerHeight;
    setPos({
      left: flip ? Math.max(8, rect.right - width) : rect.left,
      top: up ? undefined : below,
      bottom: up ? window.innerHeight - rect.top + 8 : undefined,
      maxWidth: width,
    });
  };

  // Focusing a label can scroll it into view AFTER the first measurement, and
  // a fixed card measured against the old position ends up nowhere near the
  // word. Re-measure once the frame settles, and again on any scroll while the
  // card is open.
  const open = (): void => {
    setShown(true);
    place();
    window.requestAnimationFrame(place);
  };
  const close = (): void => setShown(false);

  useEffect(() => {
    if (!shown) return;
    window.addEventListener("scroll", place, { passive: true, capture: true });
    return () => window.removeEventListener("scroll", place, { capture: true });
  }, [shown]);

  if (!entry) return <>{children}</>;

  return (
    <span
      ref={ref}
      className={`term${className ? ` ${className}` : ""}`}
      tabIndex={0}
      onMouseEnter={open}
      onMouseLeave={close}
      onFocus={open}
      onBlur={close}
    >
      <span className="term-label">{children}</span>
      <span className="term-tip" role="tooltip" style={pos}>
        <b className="term-tip-head">
          {entry.term}
          {entry.unit && <i className="term-tip-unit">{entry.unit}</i>}
        </b>
        {entry.def}
      </span>
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
