// The boot splash: staged channel bars, a scrolling joke log, and the branded
// hand-off beat, then the app is revealed.
//
// Ported from the loader half of script.js plus transition.js. Two behaviours
// carried over deliberately:
//   * it plays once per browser SESSION, not per navigation -- sessionStorage,
//     so closing the tab earns you the intro again but clicking around doesn't;
//   * an actual reload replays it, because that reads as "starting fresh".
// Under the router this is even simpler than before: it mounts once at the app
// root, so route changes can't retrigger it and there is no initInPlace() dance.

import type { JSX } from "react";
import { useEffect, useRef, useState } from "react";
import { BrandMark } from "./Shell";

const LOADER_MIN_MS = 4000;
const HOLD_MS = 1050;
const REVEAL_MS = 520;
const FADE_MS = 420;
const BOOT_SEEN_KEY = "statsapp:booted";

const CHANNELS = [
  { key: "data", label: "Data Channels", from: 0, to: 45 },
  { key: "stat", label: "Stat Modules", from: 30, to: 80 },
  { key: "api", label: "API Link", from: 65, to: 100 },
] as const;

const VERBS = [
  "Wrangling", "Herding", "Untangling", "Massaging", "Nudging", "Coaxing",
  "Cajoling", "Befriending", "Summoning", "Juggling", "Wrestling", "Tickling",
  "Bamboozling", "Yeeting", "Sprinkling", "Bedazzling", "Turbocharging",
  "Overthinking", "Double-checking", "Alphabetizing", "Reticulating", "Placating",
];

const TARGETS = [
  "the spreadsheet gremlins", "a suspicious number of decimals", "the p-values",
  "several confidence intervals (95% confident)", "the outliers (they know what they did)",
  "one very stubborn CSV", "the bell curves", "a pile of standard deviations",
  "the correlation matrix (correlation ≠ causation ≠ my problem)",
  "some artisanal, small-batch averages", "the median (it's shy)", "3.7 billion imaginary rows",
  "the null hypothesis (still no)", "a rogue semicolon", "the error bars past last call",
  "every possible histogram", "the data (politely, then firmly)", "a heap of scatter plots",
  "the missing values (last seen in 2019)", "the regression line off a cliff",
  "the chi-square goblins", "a box plot and its whiskers", "the variance (mildly upset)",
  "the z-scores", "the entire alphabet, just in case", "the leftover NaNs into a NaN sandwich",
  "the quartiles (all four, grudgingly)", "the mode (democratically, one vote each)",
  "a wild pie chart (do not feed)", "the sample size (it's a big ask)",
  "the decimal point back where it belongs", "one p-value into significance (don't tell anyone)",
  "the R² until it looks respectable", "a dataset that swears it's normally distributed",
  "the residuals under the rug", "Bayes' theorem (priors sold separately)",
  "the t-test, the whole t-test, and nothing but the t-test", "gigabytes of vibes",
  "the confounding variables into the group chat", "a normal distribution that skipped leg day",
  "the standard error, apologetically", "the degrees of freedom (currently 3, ideally more)",
  "an Excel formula nobody remembers writing", "the trend line, wishfully",
];

function pick(pool: readonly string[]): string {
  return pool[Math.floor(Math.random() * pool.length)] ?? "";
}

function randomBootLine(): string {
  return `${pick(VERBS)} ${pick(TARGETS)}…`;
}

function prefersReducedMotion(): boolean {
  return (
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

function isReloadNavigation(): boolean {
  try {
    const [entry] = performance.getEntriesByType("navigation");
    if (entry) return (entry as PerformanceNavigationTiming).type === "reload";
  } catch {
    // Navigation Timing unavailable -- assume a fresh visit.
  }
  return false;
}

function shouldSkip(): boolean {
  try {
    return sessionStorage.getItem(BOOT_SEEN_KEY) === "1" && !isReloadNavigation();
  } catch {
    return false; // storage blocked (private mode) -- always play it
  }
}

function markSeen(): void {
  try {
    sessionStorage.setItem(BOOT_SEEN_KEY, "1");
  } catch {
    // Nothing to do; it will simply replay next time.
  }
}

type Phase = "booting" | "handoff" | "done";

export function BootLoader({ children }: { children: React.ReactNode }): JSX.Element {
  const [phase, setPhase] = useState<Phase>(() => (shouldSkip() ? "done" : "booting"));
  const [progress, setProgress] = useState(0);
  const [log, setLog] = useState<string[]>([]);
  const [handoffShown, setHandoffShown] = useState(false);
  const timers = useRef<number[]>([]);

  // Progress + log churn while the splash holds.
  useEffect(() => {
    if (phase !== "booting") return;
    const started = performance.now();

    const progressTimer = window.setInterval(() => {
      const pct = Math.min(100, ((performance.now() - started) / LOADER_MIN_MS) * 100);
      setProgress(pct);
      if (pct >= 100) {
        window.clearInterval(progressTimer);
        setPhase("handoff");
      }
    }, 60);

    const logTimer = window.setInterval(() => {
      setLog((prev) => [...prev.slice(-6), randomBootLine()]);
    }, 260);

    timers.current.push(progressTimer, logTimer);
    return () => {
      window.clearInterval(progressTimer);
      window.clearInterval(logTimer);
    };
  }, [phase]);

  // The branded hand-off beat, then reveal.
  useEffect(() => {
    if (phase !== "handoff") return;
    markSeen();
    if (prefersReducedMotion()) {
      const t = window.setTimeout(() => setPhase("done"), FADE_MS);
      return () => window.clearTimeout(t);
    }
    const label = window.setTimeout(() => setHandoffShown(true), 380);
    const reveal = window.setTimeout(() => setPhase("done"), HOLD_MS + REVEAL_MS);
    return () => {
      window.clearTimeout(label);
      window.clearTimeout(reveal);
    };
  }, [phase]);

  const channelState = (from: number, to: number): number => {
    if (progress <= from) return 0;
    if (progress >= to) return 100;
    return ((progress - from) / (to - from)) * 100;
  };

  return (
    <>
      {phase !== "done" && (
        <div
          className={`loader-overlay${phase === "handoff" ? " is-hidden" : ""}`}
          id="loader"
          role="status"
          aria-label="Loading, please wait"
        >
          <div className="loader-card" aria-hidden="true">
            <header className="loader-head">
              <span className="loader-mark">
                <BrandMark />
              </span>
              <p className="loader-brand">Data Analysis Engine</p>
              <p className="loader-sub">Statistical Engine · v1.3.1</p>
              <p className="loader-build">Build 2026.08.29 · FastAPI Core · Statistics Module</p>
            </header>

            <ul className="boot-channels" id="boot-channels">
              {CHANNELS.map((c) => {
                const pct = channelState(c.from, c.to);
                const full = pct >= 100;
                return (
                  <li className="boot-channel" key={c.key}>
                    <span className="boot-channel-label">{c.label}</span>
                    <span className="boot-channel-track">
                      <span
                        className={`boot-channel-fill${full ? " is-full" : ""}`}
                        style={{ width: `${pct}%` }}
                      />
                    </span>
                    <span className={`boot-channel-pct${full ? " is-on" : ""}`}>
                      {Math.round(pct)}
                    </span>
                  </li>
                );
              })}
            </ul>

            <div className="boot-log" id="boot-log">
              {log.map((line, i) => (
                <p className="boot-log-line" key={`${i}-${line}`}>
                  {line}
                </p>
              ))}
            </div>

            <p className="boot-status" id="boot-status">
              {CHANNELS.map((c) => {
                const on = channelState(c.from, c.to) >= 100;
                return (
                  <span
                    className={`boot-status-item${on ? " is-on" : ""}`}
                    data-key={c.key}
                    key={c.key}
                  >
                    {c.label} <b>{on ? "OK" : "…"}</b>
                  </span>
                );
              })}
            </p>
          </div>
        </div>
      )}

      {phase === "handoff" && (
        <div className="boot-transition is-revealing">
          <div className="boot-transition-inner">
            <div className="boot-transition-mark">
              <BrandMark />
            </div>
            <div className="boot-transition-sweep" />
            <p className={`boot-transition-label${handoffShown ? " is-shown" : ""}`}>
              Engine ready
            </p>
          </div>
        </div>
      )}

      {children}
    </>
  );
}
