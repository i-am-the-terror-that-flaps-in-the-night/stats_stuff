/* jshint esversion: 11 */
// Client-side navigation for the main site (Overview / Methodology / Benchmarks
// / Changelog). Instead of a full document load, an internal link swaps the
// <div class="page"> content in place -- so returning to the Overview never
// replays its multi-second boot splash, and moving between pages is instant.
//
// Only same-origin links that land on one of our own pages are taken over.
// Studio/Docs (marked data-ext, server-rendered) and external links (GitHub,
// mailto, the framework docs) navigate normally. Anything this can't handle --
// a fetch error, a page with no .page block -- falls back to a real navigation,
// so a served page always works even with JS disabled or this file missing.
(function () {
    "use strict";

    const PAGE_SELECTOR = ".page";

    // Should this anchor be handled in place? Same-origin, not data-ext, and it
    // resolves to one of our pages: an .html file or a site directory (the
    // Overview link is "./" or "../../", which the server answers with index).
    function isInternal(a) {
        if (!a || a.target === "_blank" || a.hasAttribute("data-ext")) {
            return false;
        }
        let url;
        try {
            url = new URL(a.href, document.baseURI);
        } catch {
            return false;
        }
        if (url.origin !== location.origin) {
            return false; // external host, or a mailto: (opaque origin)
        }
        return url.pathname.endsWith("/") || url.pathname.endsWith(".html");
    }

    // Fetch `url`, swap its .page into the live document, retitle, and (if we
    // landed on the Overview) re-init the analysis app. `push` records history.
    async function swapTo(url, push) {
        let html;
        try {
            const res = await fetch(url, { headers: { "X-Requested-With": "spa" } });
            if (!res.ok) {
                throw new Error("HTTP " + res.status);
            }
            html = await res.text();
        } catch {
            location.href = url; // server/network error -- let the browser try
            return;
        }

        const doc = new DOMParser().parseFromString(html, "text/html");
        const incoming = doc.querySelector(PAGE_SELECTOR);
        const current = document.querySelector(PAGE_SELECTOR);
        if (!incoming || !current) {
            location.href = url; // not a page we can swap (e.g. Studio) -- hard nav
            return;
        }

        current.replaceWith(incoming);
        if (doc.title) {
            document.title = doc.title;
        }
        if (push) {
            history.pushState({ spa: true }, "", url);
        }
        window.scrollTo(0, 0);

        // The Overview carries the analysis widget; re-wire it against the fresh
        // markup. initInPlace deliberately skips the boot splash.
        if (incoming.querySelector("#tier-grid") && window.StatsApp) {
            window.StatsApp.initInPlace();
        }
    }

    document.addEventListener("click", (e) => {
        // Leave modified clicks (new tab, download, etc.) to the browser.
        if (e.defaultPrevented || e.button !== 0 ||
            e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) {
            return;
        }
        const a = e.target.closest("a");
        if (!a || !isInternal(a)) {
            return;
        }
        const url = new URL(a.href, document.baseURI);
        // Same page (ignoring any #hash): let the browser handle it natively.
        if (url.pathname === location.pathname && url.search === location.search) {
            return;
        }
        e.preventDefault();
        swapTo(url.href, true);
    });

    // Back/forward: re-render the target without pushing a new entry.
    window.addEventListener("popstate", () => {
        swapTo(location.href, false);
    });
})();
