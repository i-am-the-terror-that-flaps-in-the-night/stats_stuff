// A label with its definition on hover, focus or tap.
//
// The site prints a lot of vocabulary -- "kurtosis", "VIF", "standardized β",
// "HbA1c" -- and a reader who blanks on one of them should not have to leave
// the number to find out. <Term> looks the label up in lib/glossary; if there
// is an entry it draws the word with a dotted underline and shows the
// definition in a small card beside it. If there is no entry it renders the
// children untouched, so it is safe to wrap every label on the site.
//
// THREE THINGS HERE ARE LOAD-BEARING, EACH FROM A BUG.
//
// 1. The card is a PORTAL onto <body>. The labels sit inside stat grids and
//    .results-scroll tables that clip overflow, so an absolutely positioned
//    card is cut off at the cell edge -- and position:fixed does not rescue it,
//    because .results, .module-head and .step-panel run `animation: rise` and
//    an element with a transform animation in effect becomes the containing
//    block for its fixed descendants. A card measured against the viewport
//    then rendered offset by wherever that panel sat. <body> is nobody's
//    transformed descendant, so the portal escapes both.
//
// 2. The card is MEASURED BEFORE IT IS PLACED. It renders once invisibly at
//    its final width, and a layout effect reads the height it actually took
//    before deciding above-or-below. A guessed height threw tall cards a few
//    hundred pixels off the word they belonged to.
//
// 3. Exactly ONE card exists for the whole app, enforced by the store below
//    rather than by each Term closing itself. Self-closing looked right and
//    was not: a missed mouseleave, or two labels resolving to the same entry,
//    left a second card stranded on screen.

import type { CSSProperties, JSX, ReactNode } from "react";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import { createPortal } from "react-dom";
import { lookup } from "../lib/glossary";

/** Card width, matched by .term-tip's max-width. */
const WIDTH = 320;
/** Space between the word and the card, and the least distance to a screen edge. */
const GAP = 8;
const EDGE = 12;

// ---------------------------------------------------------------------------
// Which card is open -- one id for the whole app, so opening any card closes
// every other one without the two components having to know about each other.
// ---------------------------------------------------------------------------

let nextId = 1;
let openId = 0;
const listeners = new Set<() => void>();

function setOpen(id: number): void {
  if (openId === id) return;
  openId = id;
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

const getOpen = (): number => openId;

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
  const tipRef = useRef<HTMLSpanElement | null>(null);
  const idRef = useRef(0);
  if (idRef.current === 0) idRef.current = nextId++;
  const id = idRef.current;

  const current = useSyncExternalStore(subscribe, getOpen, getOpen);
  const isOpen = current === id;

  // `tick` forces a re-place; the word's box is never stored, only read live
  // in the layout effect below. Snapshotting it was wrong: focusing a label
  // scrolls it into view AFTER the handler has run, so the stored rect was one
  // scroll out of date and the card landed where the word used to be.
  const [tick, setTick] = useState(0);
  const [pos, setPos] = useState<CSSProperties | null>(null);
  const replace = useCallback((): void => setTick((t) => t + 1), []);

  const open = useCallback((): void => {
    if (!ref.current) return;
    if (openId === id) {
      // Already ours. A tap fires mouseenter AND focus, and blanking the
      // position on that second call left the card stranded at its unplaced
      // origin, because the layout effect had no reason to run again.
      replace();
      return;
    }
    setPos(null);
    setOpen(id);
  }, [id, replace]);

  // Only ever closes THIS Term's card. Unguarded, moving from one word to the
  // next shut the new card instead of the old one: the second word's
  // mouseenter opens its card, and the first word's blur then arrives and
  // clears the shared id out from under it.
  const close = useCallback((): void => {
    if (openId === id) setOpen(0);
  }, [id]);

  // Hover is MOUSE ONLY, and that is not fussiness -- it is the only way to
  // keep a phone honest. A tap emits a burst of compatibility mouse events
  // (mouseover, mouseenter, ... mouseout, mouseleave) around the real touch,
  // and the browser aims the trailing ones at wherever the synthetic cursor
  // last sat, which is the PREVIOUS word. Reacting to those reopened the card
  // you had just tapped away from, roughly 30ms after the right one appeared.
  // Filtering on pointerType leaves touch to focus, where it belongs.
  const enter = useCallback(
    (event: { pointerType: string }): void => {
      if (event.pointerType === "mouse") open();
    },
    [open],
  );

  const leave = useCallback(
    (event: { pointerType: string }): void => {
      // A word that holds focus keeps its card: the pointer wandering off a
      // label the reader tabbed to should not take the definition with it.
      if (event.pointerType === "mouse" && ref.current !== document.activeElement) close();
    },
    [close],
  );

  // Losing the card to another Term clears this one's position, so re-opening
  // it measures afresh instead of flashing where it sat last time.
  useEffect(() => {
    if (!isOpen && pos !== null) setPos(null);
  }, [isOpen, pos]);

  useEffect(() => () => close(), [close]);

  useLayoutEffect(() => {
    const el = ref.current;
    const tip = tipRef.current;
    if (!isOpen || !el || !tip) return;
    const anchor = el.getBoundingClientRect();
    const { width, height } = tip.getBoundingClientRect();

    // Stay attached to the word: align to its left edge; if that would overflow
    // the right of the screen, align the card's right edge to the word's right
    // edge instead, so the card still sits under the word it explains rather
    // than sliding off to the nearest margin. Clamp only as a last resort.
    let left = anchor.left;
    if (left + width > window.innerWidth - EDGE) left = anchor.right - width;
    left = Math.min(Math.max(EDGE, left), Math.max(EDGE, window.innerWidth - EDGE - width));

    // Below the word, unless the measured card does not fit there.
    const below = anchor.bottom + GAP;
    const top =
      below + height <= window.innerHeight - EDGE
        ? below
        : Math.max(EDGE, anchor.top - GAP - height);

    setPos((previous) => {
      const next = { left, top, width: Math.min(WIDTH, window.innerWidth - EDGE * 2) };
      // Same answer, same object: re-placing on every scroll frame would
      // otherwise loop through this effect forever.
      return previous &&
        previous.left === next.left &&
        previous.top === next.top &&
        previous.width === next.width
        ? previous
        : next;
    });
  }, [isOpen, tick, pos === null]);

  useEffect(() => {
    if (!isOpen) return;
    // Focus scrolls the word into view a frame after the card opens; re-place
    // once the browser has settled so the card follows it there.
    const frame = window.requestAnimationFrame(replace);
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === "Escape") close();
    };
    // Touch has no "leave": a tap opens the card and the next tap anywhere
    // else dismisses it. (pointerover was tried here and is wrong -- the
    // synthetic pointer events a tap generates closed the card before it could
    // ever be seen on a phone.)
    const onPointerDown = (event: Event): void => {
      const el = ref.current;
      if (el && event.target instanceof Node && !el.contains(event.target)) close();
    };
    window.addEventListener("scroll", replace, { passive: true, capture: true });
    window.addEventListener("resize", replace, { passive: true });
    window.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPointerDown, true);
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("scroll", replace, { capture: true });
      window.removeEventListener("resize", replace);
      window.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onPointerDown, true);
    };
  }, [isOpen, close, replace]);

  if (!entry) return <>{children}</>;

  return (
    <span
      ref={ref}
      className={`term${className ? ` ${className}` : ""}`}
      tabIndex={0}
      onPointerEnter={enter}
      onPointerLeave={leave}
      onFocus={open}
      onBlur={close}
    >
      <span className="term-label">{children}</span>
      {isOpen &&
        createPortal(
          <span
            ref={tipRef}
            className={pos ? "term-tip is-placed" : "term-tip"}
            role="tooltip"
            style={
              pos ?? {
                // The measuring pass: laid out at the width it will really
                // have, so the height read back is the height it will take.
                left: 0,
                top: 0,
                width: Math.min(WIDTH, window.innerWidth - EDGE * 2),
                visibility: "hidden",
              }
            }
          >
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
