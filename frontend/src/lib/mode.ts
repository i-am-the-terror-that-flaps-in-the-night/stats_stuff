// Expert mode: a site-wide display state, not a property of the analysis widget.
//
// Picking the deepest tier on the Overview re-lights the whole console, and it
// has to STAY lit when you navigate to Study, Docs, Benchmarks and back --
// otherwise the mode reads as a flicker on one page rather than a state the
// machine is in. Two things follow from that:
//
//   - it lives on <body>, not in React state, because the surfaces it changes
//     (the chassis, the frame, the bars, the rules) are chrome owned by Shell
//     and the stylesheet, not by any one route;
//   - it is mirrored to localStorage, so a reload or a deep link into /study
//     comes back up in the mode the user left the site in.
//
// Everything downstream of this is CSS: see body[data-mode="expert"].

const KEY = "dae:mode";

export type Mode = "expert" | "";

/** Set the mode and remember it. Called from the tier picker. */
export function setMode(mode: Mode): void {
  document.body.dataset.mode = mode;
  try {
    if (mode) window.localStorage.setItem(KEY, mode);
    else window.localStorage.removeItem(KEY);
  } catch {
    // Private browsing / storage disabled. The mode still applies for this
    // session -- it just won't survive a reload, which is a fine degradation.
  }
}

/** Re-apply the remembered mode. Called once, from Shell. */
export function restoreMode(): void {
  try {
    if (window.localStorage.getItem(KEY) === "expert") {
      document.body.dataset.mode = "expert";
    }
  } catch {
    /* see above */
  }
}
