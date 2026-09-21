// The frame every page sits in: the instrument strip, the page, the colophon.
//
// The nav used to be hand-rolled history interception (Web/JS/nav.js) because
// the site was a set of separate HTML documents. Under the router those are real
// routes, so <NavLink> handles the in-place swap and the aria-current state for
// free -- and the "returning to Overview replays the boot splash" problem that
// nav.js existed to solve simply doesn't arise, because the splash lives in a
// component that mounts once at the app root.
//
// OBSERVATORY LAYOUT
//   One sticky strip carries everything that is chrome: the brand mark, the
//   ten routes, the live readouts and the theme switch. It is the only thing
//   that floats over the page; the page itself is a single measure on the deep
//   ground with no frame. The strip's lower edge is a hairline with one accent
//   tick (.strip-rule) -- the site's signature mark, used nowhere else.

import type { JSX } from "react";
import { NavLink, Outlet } from "react-router";
import { useEffect, useState } from "react";
import { measureLatency } from "../lib/api";
import { currentTheme, restoreMode, restoreTheme, setTheme } from "../lib/mode";
import type { Theme } from "../lib/mode";

/** The ascending-bars mark, shared by the strip, the loader and the transition.
 *  Painted in currentColor so it follows whatever ink it sits in. */
export function BrandMark(): JSX.Element {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <rect className="brand-bar brand-bar-1" x="3.5" y="13" width="4.5" height="7.5" />
      <rect className="brand-bar brand-bar-2" x="9.75" y="10" width="4.5" height="10.5" />
      <rect className="brand-bar brand-bar-3" x="16" y="7" width="4.5" height="13.5" />
    </svg>
  );
}

const ROUTES: { to: string; label: string; end?: boolean }[] = [
  { to: "/", label: "Overview", end: true },
  { to: "/study", label: "Study" },
  { to: "/predict", label: "Predict" },
  { to: "/figures", label: "Figures" },
  { to: "/downloads", label: "Downloads" },
  { to: "/methodology", label: "Methodology" },
  { to: "/benchmarks", label: "Benchmarks" },
  { to: "/changelog", label: "Changelog" },
  { to: "/studio", label: "Studio" },
  { to: "/guide", label: "Docs" },
];

function navClass({ isActive }: { isActive: boolean }): string {
  return isActive ? "mainnav-link is-current" : "mainnav-link";
}

export function Shell(): JSX.Element {
  const [latency, setLatency] = useState<number | null>(null);
  const [theme, setThemeState] = useState<Theme>("");

  // Expert mode and the theme are remembered across reloads and deep links;
  // Shell mounts once for every route, so this is the one place they need
  // restoring. The theme is read back into state so the toggle's label is
  // right on the first render rather than after a click.
  useEffect(() => {
    restoreTheme();
    restoreMode();
    setThemeState(currentTheme());
  }, []);

  // One real round trip, shown in the strip. A genuine number reads as a
  // monitored engine; when no backend answers, the readout simply never appears.
  useEffect(() => {
    let live = true;
    void measureLatency().then((ms) => {
      if (live) setLatency(ms);
    });
    return () => {
      live = false;
    };
  }, []);

  const toggleTheme = (): void => {
    const next: Theme = theme === "light" ? "" : "light";
    setTheme(next);
    setThemeState(next);
  };

  return (
    <div className="page">
      <header className="strip">
        <div className="strip-row strip-row-brand">
          <NavLink to="/" className="brand" end>
            <span className="brand-mark" aria-hidden="true">
              <BrandMark />
            </span>
            <span className="brand-name">Data Analysis Engine</span>
            <span className="brand-ver">v4.1</span>
          </NavLink>

          <div className="strip-meta">
            <span className="strip-readout">
              <span className="strip-readout-k">Engine</span>
              <span className="strip-readout-v">FastAPI</span>
            </span>
            <span className="strip-readout">
              <span className="strip-readout-k">Tiers</span>
              <span className="strip-readout-v">05</span>
            </span>
            <span className="strip-readout strip-live" aria-live="polite">
              <i className="strip-dot" aria-hidden="true" />
              <span className="strip-readout-k">Link</span>
              <span className="strip-readout-v">{latency === null ? "—" : `${latency} ms`}</span>
            </span>
            <button
              type="button"
              className="theme-toggle"
              onClick={toggleTheme}
              aria-pressed={theme === "light"}
              title={theme === "light" ? "Switch to the dark theme" : "Switch to the light theme"}
            >
              <span className="theme-toggle-track" aria-hidden="true">
                <span className="theme-toggle-knob" />
              </span>
              <span className="theme-toggle-label">{theme === "light" ? "Day" : "Night"}</span>
            </button>
          </div>
        </div>

        <nav className="mainnav" aria-label="Primary">
          {ROUTES.map((route, index) => (
            <NavLink key={route.to} className={navClass} to={route.to} end={route.end ?? false}>
              <span className="mainnav-index" aria-hidden="true">
                {String(index + 1).padStart(2, "0")}
              </span>
              <span className="mainnav-label">{route.label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="strip-rule" aria-hidden="true" />
      </header>

      <Outlet />

      <footer className="colophon">
        <div className="colophon-col">
          <span className="colophon-mark" aria-hidden="true">
            <BrandMark />
          </span>
          <p className="colophon-title">Data Analysis Engine</p>
          <p className="colophon-text">
            A statistical engine and the companion demo to a Medicine &amp; Health science-fair
            project on liver stress in U.S. adolescents.
          </p>
        </div>
        <div className="colophon-col">
          <p className="colophon-head">Built with</p>
          <p className="colophon-text">FastAPI · Pandas · statsmodels · LightGBM</p>
          <p className="colophon-text">React · TypeScript · Vite</p>
          <p className="colophon-text">Young Serif · Sora · Martian Mono</p>
        </div>
        <div className="colophon-col">
          <p className="colophon-head">Elsewhere</p>
          <p className="colophon-links">
            <a href="https://fastapi.tiangolo.com/reference/">API docs</a>
            <a href="https://github.com/i-am-the-terror-that-flaps-in-the-night">GitHub</a>
            <a href="mailto:anirudh.gupta.sa@gmail.com">Contact</a>
            <a href="https://404-page-62v.pages.dev/">About me</a>
          </p>
          <p className="colophon-meta">© 2026 Anirudh Gupta</p>
        </div>
      </footer>
    </div>
  );
}
