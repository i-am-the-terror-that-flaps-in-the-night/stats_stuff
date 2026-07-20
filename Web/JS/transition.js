/* jshint esversion: 9 */
// Boot transition: a short, purely-cosmetic handoff played once, right after the
// loading splash finishes and just before the app is revealed.
//
// Contract (unchanged): script.js calls `window.playBootTransition(loaderEl)` and
// awaits the returned promise. We paint an opaque, full-screen overlay ON TOP of
// the loader (z-index above it), so we can drop the loader out from underneath
// without a flash. Then we play a brief branded beat and reveal the page beneath.
//
// This is the light "analytics console" version: a clean overlay with the brand
// mark, a sweeping accent line, and an "Engine ready" tag, then a gentle fade +
// rise. prefers-reduced-motion collapses it to a quick, still cross-fade. Kept in
// its own file so script.js stays focused on the actual app wiring.
(function () {
    "use strict";

    const HOLD_MS = 1050;  // how long the branded beat holds before revealing
    const REVEAL_MS = 520; // gentle fade + rise, ms (matches CSS)
    const FADE_MS = 420;   // calm fallback fade, ms (reduced-motion path)

    // The shared ascending-bars mark, so the transition carries the same identity
    // as the app bar and the loader. Square (no radius) with neon R/G/B fills, to
    // read on the mark's dark tile.
    const MARK_SVG =
        '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true">' +
        '<rect x="3.5" y="13" width="4.5" height="7.5" fill="#ff2bd6"/>' +
        '<rect x="9.75" y="10" width="4.5" height="10.5" fill="#8b5cf6"/>' +
        '<rect x="16" y="7" width="4.5" height="13.5" fill="#22d3ee"/>' +
        '</svg>';

    function prefersReduced() {
        return window.matchMedia &&
            window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    }

    window.playBootTransition = function (loaderEl) {
        return new Promise((resolve) => {
            // Opaque overlay stacked above the loader. Because it fully covers the
            // screen the instant it's added, we can hide the loader behind it with
            // no visible seam.
            const overlay = document.createElement("div");
            overlay.className = "boot-transition";

            const inner = document.createElement("div");
            inner.className = "boot-transition-inner";

            const mark = document.createElement("div");
            mark.className = "boot-transition-mark";
            mark.innerHTML = MARK_SVG;

            const sweep = document.createElement("div");
            sweep.className = "boot-transition-sweep";

            const label = document.createElement("p");
            label.className = "boot-transition-label";
            label.textContent = "Engine ready";

            inner.append(mark, sweep, label);
            overlay.appendChild(inner);
            document.body.appendChild(overlay);

            if (loaderEl) {
                loaderEl.classList.add("is-hidden");
            }

            // Calm reveal: a plain cross-fade. Used for reduced-motion.
            const revealCalm = () => {
                overlay.classList.add("is-fading");
                setTimeout(() => {
                    overlay.remove();
                    resolve();
                }, FADE_MS);
            };

            // Motion reveal: the overlay lifts and fades while the page rises in
            // underneath — a soft, corporate handoff rather than a hard cut.
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

            if (prefersReduced()) {
                // No motion: hold a still beat, then cross-fade.
                setTimeout(revealCalm, 260);
                return;
            }

            // Show the label partway through, then reveal once the beat has held.
            setTimeout(() => label.classList.add("is-shown"), 380);
            setTimeout(revealMotion, HOLD_MS);
        });
    };
})();
