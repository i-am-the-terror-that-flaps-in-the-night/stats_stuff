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
    const params = new URLSearchParams(window.location.search);
    const wanted = params.get("mode") ?? window.localStorage.getItem(KEY);
    if (wanted === "expert") document.body.dataset.mode = "expert";
  } catch {
    /* see above */
  }
  // The pre-paint script in index.html staged the mode on <html> so the very
  // first frame was already lit; now that <body> carries it, retire the stage.
  delete document.documentElement.dataset.bootMode;
}


// ----------------------------------------------------------------------
// THEME -- dark is the Observatory's native state; light is the alternate.
//
// Orthogonal to the tier mode above: the theme is a reading preference, the
// mode is what the analysis is doing. It lives on <html> rather than <body>
// so index.html's pre-paint script can set it before the body exists (no flash
// of the wrong ground on reload), and the exporter can read figure tokens from
// the same element the theme is declared on.
// ----------------------------------------------------------------------

const THEME_KEY = "dae:theme";

export type Theme = "light" | "";

export function currentTheme(): Theme {
  return document.documentElement.dataset.theme === "light" ? "light" : "";
}

/** Set the theme and remember it. Called from the header toggle. */
export function setTheme(theme: Theme): void {
  if (theme) document.documentElement.dataset.theme = theme;
  else delete document.documentElement.dataset.theme;
  try {
    if (theme) window.localStorage.setItem(THEME_KEY, theme);
    else window.localStorage.removeItem(THEME_KEY);
  } catch {
    /* storage disabled; the theme still applies for this session */
  }
}

/** Re-apply the remembered theme. Idempotent with index.html's pre-paint. */
export function restoreTheme(): void {
  try {
    const params = new URLSearchParams(window.location.search);
    const wanted = params.get("theme") ?? window.localStorage.getItem(THEME_KEY);
    if (wanted === "light") document.documentElement.dataset.theme = "light";
  } catch {
    /* see above */
  }
}
