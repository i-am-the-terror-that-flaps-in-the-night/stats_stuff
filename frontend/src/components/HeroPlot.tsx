// The plot behind the masthead.
//
// This replaced a full-viewport drifting "mote field". That version failed for
// a specific, instructive reason: unbounded dark specks scattered over a light
// background have no frame of reference, so they read as dirt on the screen
// rather than as an image. The fix is not fewer particles or lower opacity --
// it is a FRAME and a MODEL. Here the points are bounded by the masthead panel,
// they scatter around a visible regression line, and they carry the axis ticks
// of the plot they belong to. Same technique, now legible as a scatter plot,
// which is exactly what this site is about.
//
// It sits on the dark observatory panel, so the points glow instead of
// soiling -- and behind the plot box there is a second, fainter field of
// seeded stars, which is the one place on the site where an unbounded scatter
// is allowed: it is the sky the instrument is pointed at, and the ruled plot
// in front of it is the frame that makes the difference legible.
//
// COLOURS COME FROM THE STYLESHEET. The canvas reads four custom properties
// (--hero-grid, --hero-dot, --hero-line, --hero-line-end) off itself at paint
// time, so the day theme repaints it without this file knowing a hex value.
//
// The data is synthetic but not arbitrary: a correlated cloud (r ~ 0.6) drawn
// from a seeded generator, so the picture is identical on every load and every
// machine -- a decorative element that reshuffles on each visit would undercut
// the "deterministic engine" claim the page makes two inches below it.

import { useEffect, useRef } from "react";
import type { JSX } from "react";

const POINTS = 90;
/** Background stars: sub-pixel, seeded, static. */
const STARS = 170;
/** Fixed seed -- see the note above on why this must not be Math.random(). */
const SEED = 0x5eed1a;
/** How tightly the cloud hugs the trend. Lower = more correlated. */
const NOISE = 0.42;

/** Mulberry32: a tiny seeded PRNG. Deterministic across browsers, unlike any
 *  approach that reaches for Math.random(). */
function rng(seed: number): () => number {
  let a = seed;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Two uniforms -> one standard normal. The cloud has to look sampled, and a
 *  uniform scatter visibly does not: it fills its box with hard edges. */
function gauss(next: () => number): number {
  const u = Math.max(next(), 1e-9);
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * next());
}

export function HeroPlot(): JSX.Element {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    // Unit-space cloud (0..1 on both axes), generated once and reused across
    // resizes so the picture doesn't reshuffle when the window changes.
    const next = rng(SEED);
    const cloud = Array.from({ length: POINTS }, () => {
      const x = next();
      const y = Math.min(0.98, Math.max(0.02, x + gauss(next) * NOISE * 0.5));
      return { x, y, r: 1.4 + next() * 2.2 };
    });
    const stars = Array.from({ length: STARS }, () => ({
      x: next(),
      y: next(),
      r: 0.4 + next() * 1.1,
      a: 0.15 + next() * 0.4,
    }));

    /** A token off the canvas, resolved by the cascade -- theme-aware. */
    const token = (name: string, fallback: string): string => {
      const value = window.getComputedStyle(canvas!).getPropertyValue(name).trim();
      return value || fallback;
    };

    const still = window.matchMedia("(prefers-reduced-motion: reduce)");
    let frame = 0;
    let start = 0;

    function paint(progress: number) {
      const rect = canvas!.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const w = rect.width;
      const h = rect.height;
      if (w === 0 || h === 0) return;
      canvas!.width = Math.floor(w * dpr);
      canvas!.height = Math.floor(h * dpr);
      ctx!.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx!.clearRect(0, 0, w, h);

      const gridInk = token("--hero-grid", "rgba(140,190,255,0.1)");
      const dotInk = token("--hero-dot", "rgba(160,230,255,0.7)");
      const lineInk = token("--hero-line", "#5ee7ff");
      const lineEndInk = token("--hero-line-end", "#9ef1ff");
      const starInk = token("--hero-star", "rgba(200,225,255,0.5)");

      // The sky: static stars over the whole panel, behind the plot box.
      for (const st of stars) {
        ctx!.globalAlpha = st.a;
        ctx!.fillStyle = starInk;
        ctx!.beginPath();
        ctx!.arc(st.x * w, st.y * h, st.r, 0, Math.PI * 2);
        ctx!.fill();
      }
      ctx!.globalAlpha = 1;

      // Plot box, inset from the panel edges so the cloud never collides with
      // the headline sitting on top of it.
      const padX = w * 0.06;
      const padY = h * 0.14;
      const bw = w - padX * 2;
      const bh = h - padY * 2;
      const px = (u: number) => padX + u * bw;
      const py = (v: number) => padY + (1 - v) * bh;

      // Grid: the plot's own reference frame. This is what stops the points
      // reading as noise -- specks in a ruled box are data.
      ctx!.lineWidth = 1;
      ctx!.strokeStyle = gridInk;
      for (let i = 1; i < 5; i++) {
        ctx!.beginPath();
        ctx!.moveTo(px(i / 5), py(0));
        ctx!.lineTo(px(i / 5), py(1));
        ctx!.moveTo(px(0), py(i / 5));
        ctx!.lineTo(px(1), py(i / 5));
        ctx!.stroke();
      }

      // The fit line, drawn to `progress` -- it sweeps in left to right on
      // load, the way a plot is actually rendered.
      const lineEnd = Math.min(1, progress * 1.15);
      const grad = ctx!.createLinearGradient(px(0), 0, px(1), 0);
      grad.addColorStop(0, lineInk);
      grad.addColorStop(1, lineEndInk);
      ctx!.strokeStyle = grad;
      ctx!.lineWidth = 2;
      // A canvas has no export path, so a glow is allowed here where it is
      // forbidden inside the SVG figures.
      ctx!.shadowColor = lineInk;
      ctx!.shadowBlur = 10;
      ctx!.beginPath();
      ctx!.moveTo(px(0.02), py(0.06));
      ctx!.lineTo(px(0.02 + 0.96 * lineEnd), py(0.06 + 0.88 * lineEnd));
      ctx!.stroke();
      ctx!.shadowBlur = 0;

      // Points fade up in x-order, trailing just behind the line.
      ctx!.fillStyle = dotInk;
      for (const p of cloud) {
        const local = Math.min(1, Math.max(0, (progress - p.x * 0.55) * 3));
        if (local <= 0) continue;
        ctx!.globalAlpha = local;
        ctx!.beginPath();
        ctx!.arc(px(p.x), py(p.y), p.r, 0, Math.PI * 2);
        ctx!.fill();
      }
      ctx!.globalAlpha = 1;
    }

    function run(now: number) {
      if (!start) start = now;
      // 1.5s draw-in, then the plot is STATIC. Nothing on this page should
      // move forever in the corner of a judge's eye while they read.
      const progress = Math.min(1, (now - start) / 1500);
      paint(progress);
      if (progress < 1) frame = window.requestAnimationFrame(run);
    }

    if (still.matches) {
      paint(1);
    } else {
      frame = window.requestAnimationFrame(run);
    }

    // Repaint complete on resize; re-running the draw-in on every resize tick
    // would look like a glitch.
    const onResize = () => paint(1);
    window.addEventListener("resize", onResize);
    // The theme toggle rewrites html[data-theme]; repaint with the new tokens.
    const themed = new MutationObserver(() => paint(1));
    themed.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("resize", onResize);
      themed.disconnect();
    };
  }, []);

  return <canvas ref={canvasRef} className="hero-plot" aria-hidden="true" />;
}
