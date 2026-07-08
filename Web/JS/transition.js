/* jshint esversion: 9 */
// Boot transition: a short, purely-cosmetic "engine spin-up" flourish played once,
// right after the loading splash reads "Done. No data was harmed." and just before
// the app is revealed.
//
// Contract: script.js calls `window.playBootTransition(loaderEl)` and awaits the
// returned promise. We paint our own opaque, full-screen canvas ON TOP of the
// loader (z-index above it), so we can drop the loader out from underneath without
// any flash. Then we run a ~1.5s warp-in on <canvas> and fade ourselves out to
// reveal the page. prefers-reduced-motion collapses this to a quick, still fade.
//
// Kept in its own file so script.js stays focused on the actual app wiring.
(function () {
    "use strict";

    const DURATION = 1500; // main animation, ms
    const REVEAL_MS = 560; // motion "punch-through" reveal, ms (matches CSS)
    const FADE_MS = 420;   // calm fallback fade, ms (reduced-motion path)

    // A minority of streaks are cyan so the site's rare-accent rule holds; the
    // rest are steel so the field reads as structure, not decoration.
    const CYAN_SHARE = 0.18;

    function prefersReduced() {
        return window.matchMedia &&
            window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    }

    // Radial warp field: points streaking outward from center, leaving trails.
    function makeStreaks(count, radius) {
        const streaks = [];
        for (let i = 0; i < count; i++) {
            streaks.push({
                ang: Math.random() * Math.PI * 2,
                dist: Math.random() * radius * 0.18, // start clustered near center
                speed: 0.5 + Math.random() * 1.6,    // per-streak velocity factor
                trailFrac: 0.05 + Math.random() * 0.13,
                cyan: Math.random() < CYAN_SHARE,
                width: Math.random() < 0.3 ? 2 : 1,
            });
        }
        return streaks;
    }

    // HUD ring: concentric rings that counter-rotate, with arc segments and
    // crosshair ticks -- an instrument acquiring a lock, matching the loader's
    // reticle motif. The opposed spin reads as machinery under load.
    function drawRing(ctx, cx, cy, r, spin, dpr) {
        if (r < 2) {
            return;
        }
        // Outer ring + three rotating segments.
        ctx.strokeStyle = "rgba(34, 211, 238, 0.75)";
        ctx.lineWidth = 1.5 * dpr;
        ctx.beginPath();
        ctx.arc(cx, cy, r, 0, Math.PI * 2);
        ctx.stroke();

        ctx.lineWidth = 3 * dpr;
        ctx.strokeStyle = "rgba(34, 211, 238, 0.95)";
        for (let i = 0; i < 3; i++) {
            const a0 = spin + (i * Math.PI * 2) / 3;
            ctx.beginPath();
            ctx.arc(cx, cy, r + 7 * dpr, a0, a0 + 0.55);
            ctx.stroke();
        }

        // Inner ring, counter-rotating faster.
        const ir = r * 0.62;
        ctx.lineWidth = 2 * dpr;
        ctx.strokeStyle = "rgba(103, 232, 249, 0.9)";
        for (let i = 0; i < 4; i++) {
            const a0 = -spin * 1.7 + (i * Math.PI) / 2;
            ctx.beginPath();
            ctx.arc(cx, cy, ir, a0, a0 + 0.42);
            ctx.stroke();
        }

        // Crosshair ticks straddling the outer ring.
        ctx.strokeStyle = "rgba(34, 211, 238, 0.5)";
        ctx.lineWidth = 1 * dpr;
        const tick = 7 * dpr;
        for (let i = 0; i < 4; i++) {
            const a = spin * 0.5 + (i * Math.PI) / 2;
            const dx = Math.cos(a);
            const dy = Math.sin(a);
            ctx.beginPath();
            ctx.moveTo(cx + dx * (r - tick), cy + dy * (r - tick));
            ctx.lineTo(cx + dx * (r + tick), cy + dy * (r + tick));
            ctx.stroke();
        }
    }

    window.playBootTransition = function (loaderEl) {
        return new Promise((resolve) => {
            // Opaque overlay stacked above the loader. Because it fully covers the
            // screen the instant it's added, we can hide the loader behind it with
            // no visible seam.
            const overlay = document.createElement("div");
            overlay.className = "boot-transition";
            const canvas = document.createElement("canvas");
            const label = document.createElement("p");
            label.className = "boot-transition-label";
            label.textContent = "Engine Online";
            overlay.append(canvas, label);
            document.body.appendChild(overlay);

            if (loaderEl) {
                loaderEl.classList.add("is-hidden");
            }

            // Calm reveal: a plain cross-fade. Used for reduced-motion / no-canvas.
            const revealCalm = () => {
                overlay.classList.add("is-fading");
                setTimeout(() => {
                    overlay.remove();
                    resolve();
                }, FADE_MS);
            };

            // Motion reveal: the flashed scene punches toward the viewer and
            // dissolves while the page rises in underneath -- a payoff with
            // momentum instead of a passive fade.
            const revealMotion = () => {
                overlay.classList.add("is-revealing");
                if (document.body) {
                    document.body.classList.add("boot-page-enter");
                }
                setTimeout(() => {
                    overlay.remove();
                    if (document.body) {
                        document.body.classList.remove("boot-page-enter");
                    }
                    resolve();
                }, REVEAL_MS);
            };

            const ctx = canvas.getContext("2d");
            if (prefersReduced() || !ctx) {
                // No motion (or no canvas): hold a still beat, then reveal.
                setTimeout(revealCalm, 220);
                return;
            }

            let w, h, cx, cy, dpr, radius, streaks;

            function resize() {
                dpr = Math.min(window.devicePixelRatio || 1, 2);
                w = canvas.width = Math.floor(window.innerWidth * dpr);
                h = canvas.height = Math.floor(window.innerHeight * dpr);
                canvas.style.width = window.innerWidth + "px";
                canvas.style.height = window.innerHeight + "px";
                cx = w / 2;
                cy = h / 2;
                radius = Math.hypot(w, h) / 2;
                // Scale the field density with the viewport so it reads the same
                // on a phone and a monitor.
                if (!streaks) {
                    streaks = makeStreaks(Math.round(160 + (w * h) / (12000 * dpr * dpr)), radius);
                }
            }

            resize();
            window.addEventListener("resize", resize);

            const rings = [];     // expanding shockwave circles
            let lastRingBeat = -1;
            // noinspection SpellCheckingInspection
            let bursted = false;
            let start = null;

            function frame(ts) {
                if (start === null) {
                    start = ts;
                }
                const t = ts - start;
                const p = Math.min(t / DURATION, 1); // 0..1

                // Accelerating warp with a swirl: quicker off the line than a plain
                // starburst, and the whole field rotates so it reads as a vortex.
                const accel = 1.0 + p * p * 20;
                const swirl = 0.012 + p * 0.05;

                // Motion-blur trail: lay down a translucent background each frame so
                // streaks smear instead of drawing crisp dots.
                ctx.fillStyle = "rgba(7, 10, 14, 0.28)";
                ctx.fillRect(0, 0, w, h);
                ctx.lineCap = "round";

                // Camera shake ramps in toward the flash for impact. Applied to the
                // field/rings only -- the trail wash and flash stay full-bleed.
                let sx = 0;
                let sy = 0;
                if (p > 0.68) {
                    const mag = ((p - 0.68) / 0.32) * 11 * dpr;
                    sx = (Math.random() * 2 - 1) * mag;
                    sy = (Math.random() * 2 - 1) * mag;
                }
                ctx.save();
                ctx.translate(sx, sy);

                for (const s of streaks) {
                    s.ang += swirl;
                    s.dist += s.speed * accel * (radius / 260);
                    if (s.dist > radius * 1.15) {
                        s.dist = Math.random() * radius * 0.05; // recycle from center
                        s.ang = Math.random() * Math.PI * 2;
                    }
                    const trail = s.dist * s.trailFrac + 6;
                    const cos = Math.cos(s.ang);
                    const sin = Math.sin(s.ang);
                    const a = Math.min(0.15 + s.dist / radius, 1);
                    ctx.strokeStyle = s.cyan ?
                        `rgba(34, 211, 238, ${a})` :
                        `rgba(120, 145, 170, ${a * 0.7})`;
                    ctx.lineWidth = s.width * dpr;
                    ctx.beginPath();
                    ctx.moveTo(cx + cos * s.dist, cy + sin * s.dist);
                    ctx.lineTo(cx + cos * (s.dist - trail), cy + sin * (s.dist - trail));
                    ctx.stroke();
                }

                // Shockwave rings: a steady pulse (~every 240ms) plus a burst when
                // the flash fires -- expanding circles that add a sense of force.
                const beat = Math.floor(t / 240);
                if (beat !== lastRingBeat) {
                    lastRingBeat = beat;
                    rings.push({r: radius * 0.04, alpha: 0.5, width: 1.5 * dpr, cyan: Math.random() < 0.4});
                }
                if (!bursted && p >= 0.82) {
                    bursted = true;
                    for (let k = 0; k < 3; k++) {
                        rings.push({r: radius * (0.03 + k * 0.03), alpha: 0.95, width: 2.5 * dpr, cyan: true});
                    }
                }
                for (const rg of rings) {
                    rg.r += radius * 0.011 * accel;
                    rg.alpha -= 0.011;
                    if (rg.alpha <= 0) {
                        continue;
                    }
                    ctx.strokeStyle = rg.cyan ?
                        `rgba(34, 211, 238, ${rg.alpha})` :
                        `rgba(120, 145, 170, ${rg.alpha * 0.7})`;
                    ctx.lineWidth = rg.width;
                    ctx.beginPath();
                    ctx.arc(cx, cy, rg.r, 0, Math.PI * 2);
                    ctx.stroke();
                }

                // HUD ring scales in, spins faster than before, and kicks bigger as
                // the flash fires.
                const ringP = Math.min(p / 0.8, 1);
                const kick = p > 0.82 ? 1 + ((p - 0.82) / 0.18) * 0.35 : 1;
                drawRing(ctx, cx, cy, radius * 0.16 * ringP * kick, t * 0.006, dpr);

                ctx.restore();

                // Reveal the label once the ring is established.
                if (p > 0.5) {
                    label.classList.add("is-shown");
                }

                // Closing flash: a cyan-white bloom that peaks then drops (drawn
                // without shake so it fills cleanly) right before the reveal.
                if (p > 0.82) {
                    const fp = (p - 0.82) / 0.18;
                    const flash = Math.min(fp * 2, 1); // ramp up, then hold at peak into the reveal
                    const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, radius);
                    g.addColorStop(0, `rgba(224, 250, 255, ${0.95 * flash})`);
                    g.addColorStop(0.5, `rgba(34, 211, 238, ${0.5 * flash})`);
                    g.addColorStop(1, "rgba(34, 211, 238, 0)");
                    ctx.fillStyle = g;
                    ctx.fillRect(0, 0, w, h);
                }

                if (p < 1) {
                    requestAnimationFrame(frame);
                } else {
                    window.removeEventListener("resize", resize);
                    revealMotion();
                }
            }

            requestAnimationFrame(frame);
        });
    };
})();
