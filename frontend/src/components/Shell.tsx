// The frame every page sits in: status bar, primary nav, and footer.
//
// The nav used to be hand-rolled history interception (Web/JS/nav.js) because
// the site was a set of separate HTML documents. Under the router those are real
// routes, so <NavLink> handles the in-place swap and the aria-current state for
// free -- and the "returning to Overview replays the boot splash" problem that
// nav.js existed to solve simply doesn't arise, because the splash lives in a
// component that mounts once at the app root.

import type { JSX } from "react";
import { NavLink, Outlet } from "react-router";
import { useEffect, useState } from "react";
import { knownApiBase, measureLatency } from "../lib/api";

/** The ascending-bars mark, shared by the bar, the loader and the transition. */
export function BrandMark(): JSX.Element {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <rect x="3.5" y="13" width="4.5" height="7.5" fill="#ff2bd6" />
      <rect x="9.75" y="10" width="4.5" height="10.5" fill="#8b5cf6" />
      <rect x="16" y="7" width="4.5" height="13.5" fill="#22d3ee" />
    </svg>
  );
}

function navClass({ isActive }: { isActive: boolean }): string {
  return isActive ? "mainnav-link is-current" : "mainnav-link";
}

export function Shell(): JSX.Element {
  const [latency, setLatency] = useState<number | null>(null);

  // One real round trip, shown in the top bar. A genuine number reads as a
  // monitored engine; when no backend answers, the chip simply never appears.
  useEffect(() => {
    let live = true;
    void measureLatency().then((ms) => {
      if (live) setLatency(ms);
    });
    return () => {
      live = false;
    };
  }, []);

  return (
    <div className="page">
      <div className="console-bar">
        <span className="brand">
          <span className="brand-mark" aria-hidden="true">
            <BrandMark />
          </span>
          <span className="brand-name">Data Analysis Engine</span>
          <span className="brand-ver">v1.0.0</span>
        </span>
        <div className="bar-meta">
          <span className="bar-meta-item">Engine · FastAPI</span>
          <span className="bar-meta-item">Tiers · 05</span>
          {latency !== null && (
            <span className="bar-meta-item bar-live">
              Link · <b>{latency} ms</b>
            </span>
          )}
          <span className="pips" aria-hidden="true">
            <i />
            <i />
            <i />
          </span>
          <span className="live">Live demo</span>
        </div>
      </div>

      <nav className="mainnav" aria-label="Primary">
        <NavLink className={navClass} to="/" end>
          Overview
        </NavLink>
        <NavLink className={navClass} to="/methodology">
          Methodology
        </NavLink>
        <NavLink className={navClass} to="/benchmarks">
          Benchmarks
        </NavLink>
        <NavLink className={navClass} to="/changelog">
          Changelog
        </NavLink>
        <NavLink className={navClass} to="/studio">
          Studio
        </NavLink>
        <NavLink className={navClass} to="/guide">
          Docs
        </NavLink>
      </nav>

      <div className="rgb-rule" aria-hidden="true" />

      <Outlet />

      <footer className="page-footer">
        <p>Built with FastAPI, Pandas, React and TypeScript</p>
        <p>
          <a href={`${knownApiBase() ?? ""}/docs`}>API docs</a> ·{" "}
          <a href="https://github.com/i-am-the-terror-that-flaps-in-the-night">GitHub</a> ·{" "}
          <a href="mailto:anirudh.gupta.sa@gmail.com">Contact</a> ·{" "}
          <a href="https://404-page-62v.pages.dev/">About Me</a>
        </p>
        <p className="footer-meta">© 2026 Anirudh Gupta</p>
      </footer>
    </div>
  );
}
