/* jshint esversion: 9 */
// Front end for the FastAPI backend (Backend/app.py).
//
// This page can be served three ways, and the API lives in different places in
// each:
//   * by the backend itself (uvicorn) -> the API is on the SAME origin
//   * by a separate static server (e.g., VS Code Live Server) -> API elsewhere
//   * opened straight off disk (file://) -> API elsewhere
// So instead of guessing, we try the same origin first and fall back to the
// default local backend. The first one that answers /api/columns wins, and we
// reuse it for the stat calls. (A 404 here means "served, but not by the API"
// -- that's the case we're handling.)
(function () {
    "use strict";

    const API_CANDIDATES = ["", "http://127.0.0.1:8000", "http://localhost:8000"];
    let apiBase = "";

    const statusEl = document.getElementById("status");
    const resultsEl = document.getElementById("results");
    const channelGrid = document.getElementById("channel-grid");
    const tierGrid = document.getElementById("tier-grid");
    const groupGrid = document.getElementById("group-grid");
    const groupControl = document.getElementById("group-control");
    const loader = document.getElementById("loader");
    const loaderMessage = document.getElementById("loader-message");
    const loaderBarFill = document.getElementById("loader-bar-fill");
    const loaderPercent = document.getElementById("loader-percent");

    // The analysis tiers. basic/medium/advanced run on numeric columns;
    // categorical runs on label columns (and swaps the column list to match).
    const TIERS = ["basic", "medium", "advanced", "categorical"];
    // Only these tiers do group comparisons, so only they show the group-by picker.
    const GROUPING_TIERS = new Set(["medium", "advanced"]);

    // Current selection. group === "" means "no grouping".
    const state = { tier: "basic", column: null, group: "" };

    // Column lists from /api/columns, filled on load.
    let numericColumns = [];
    let categoricalColumns = [];

    // Guard against overlapping analyses from rapid chip clicks.
    let busy = false;

    // Loading splash: keep it up for at least this long so the intro animation
    // reads as intentional rather than a flicker. A progress bar fills while a
    // fast-scrolling "module log" churns beneath it (see below).
    const LOADER_MIN_MS = 3000;

    // Boot log played for laughs: a silly present-progressive verb crossed with
    // an absurd, stats-flavored target. The two pools multiply out to hundreds of
    // one-line jokes, so cycling them fast reads as a busy engine with a sense of
    // humor rather than a real build log.
    const LOADER_VERBS = [
        "Wrangling", "Herding", "Untangling", "Massaging", "Nudging", "Coaxing",
        "Cajoling", "Befriending", "Summoning", "Juggling", "Wrestling", "Tickling",
        "Bamboozling", "Yeeting", "Sprinkling", "Bedazzling", "Turbocharging",
        "Overthinking", "Double-checking", "Alphabetizing", "Reticulating", "Placating",
    ];
    const LOADER_TARGETS = [
        "the spreadsheet gremlins", "a suspicious number of decimals", "the p-values",
        "several confidence intervals", "the outliers", "one very stubborn CSV",
        "the bell curves", "a pile of standard deviations", "the correlation matrix",
        "some artisanal averages", "the median (it's shy)", "3.7 billion imaginary rows",
        "the null hypothesis", "a rogue semicolon", "the error bars", "every possible histogram",
        "the data (politely)", "a heap of scatter plots", "the missing values",
        "the regression line", "the chi-square goblins", "a box plot or two", "the variance",
        "the z-scores", "the entire alphabet, just in case", "the leftover NaNs",
        "the quartiles", "the mode (democratically)", "a wild pie chart", "the sample size",
    ];

    function pick(pool) {
        return pool[(Math.random() * pool.length) | 0];
    }

    function randomBootLine() {
        return `${pick(LOADER_VERBS)} ${pick(LOADER_TARGETS)}…`;
    }

    function setStatus(message, isError = false) {
        statusEl.textContent = message;
        statusEl.classList.toggle("error", isError);
    }

    function tierSupportsGroup(tier) {
        return GROUPING_TIERS.has(tier);
    }

    function columnsForTier(tier) {
        return tier === "categorical" ? categoricalColumns : numericColumns;
    }

    // Find a backend that answers /api/columns and render the selectors.
    async function loadColumns() {
        for (const base of API_CANDIDATES) {
            let res;
            try {
                res = await fetch(`${base}/api/columns`);
            } catch {
                continue; // network error (server not here) -- try the next candidate
            }
            if (!res.ok) {
                continue; // answered, but not the API (e.g., 404) -- next candidate
            }

            const data = await res.json();
            apiBase = base;

            numericColumns = data.columns || [];
            categoricalColumns = data.categorical || [];

            buildTierButtons();
            buildColumnButtons(columnsForTier(state.tier));
            buildGroupButtons(categoricalColumns);
            updateGroupVisibility();

            // The numeric columns double as the live "Analyzable" telemetry count.
            const numericEl = document.getElementById("tel-numeric");
            if (numericEl) {
                numericEl.textContent = numericColumns.length;
            }
            setStatus(`Loaded ${numericColumns.length} columns from ${data.dataset}. Pick a tier and a column.`);
            await loadOverview();
            return;
        }

        setStatus("Could not reach the backend. Start it with: uvicorn main:app (from the repo root).", true);
    }

    // ---- Selectors ---------------------------------------------------------

    // Render one chip per tier; the active tier is highlighted.
    function buildTierButtons() {
        if (!tierGrid) {
            return;
        }
        tierGrid.innerHTML = "";
        for (const tier of TIERS) {
            const li = document.createElement("li");
            const btn = document.createElement("button");
            btn.type = "button";
            btn.className = "channel";
            btn.dataset.tier = tier;
            btn.setAttribute("aria-pressed", tier === state.tier ? "true" : "false");
            btn.classList.toggle("is-active", tier === state.tier);
            btn.textContent = tier;
            li.appendChild(btn);
            tierGrid.appendChild(li);
        }
    }

    // Render one chip per column for the current tier; clicking one analyzes it.
    function buildColumnButtons(columns) {
        if (!channelGrid) {
            return;
        }
        channelGrid.innerHTML = "";
        if (!columns.length) {
            const li = document.createElement("li");
            li.className = "channel-empty";
            li.textContent = "No columns for this tier.";
            channelGrid.appendChild(li);
            return;
        }
        for (const name of columns) {
            const li = document.createElement("li");
            const btn = document.createElement("button");
            btn.type = "button";
            btn.className = "channel";
            btn.dataset.column = name;
            btn.setAttribute("aria-label", `Analyze ${name}`);
            btn.setAttribute("aria-pressed", "false");
            btn.textContent = name;
            li.appendChild(btn);
            channelGrid.appendChild(li);
        }
    }

    // Group-by chips: a "None" default plus one per categorical column.
    function buildGroupButtons(columns) {
        if (!groupGrid) {
            return;
        }
        groupGrid.innerHTML = "";
        const options = [{ label: "none", value: "" }].concat(
            columns.map((c) => ({ label: c, value: c }))
        );
        for (const opt of options) {
            const li = document.createElement("li");
            const btn = document.createElement("button");
            btn.type = "button";
            btn.className = "channel";
            btn.dataset.group = opt.value;
            btn.setAttribute("aria-pressed", opt.value === state.group ? "true" : "false");
            btn.classList.toggle("is-active", opt.value === state.group);
            btn.textContent = opt.label;
            li.appendChild(btn);
            groupGrid.appendChild(li);
        }
    }

    // Mark the active chip in a grid (matched on a data-attribute value).
    function setActive(grid, attr, value) {
        if (!grid) {
            return;
        }
        for (const btn of grid.querySelectorAll(".channel")) {
            const active = btn.dataset[attr] === value;
            btn.classList.toggle("is-active", active);
            btn.setAttribute("aria-pressed", active ? "true" : "false");
        }
    }

    function updateGroupVisibility() {
        if (groupControl) {
            groupControl.hidden = !tierSupportsGroup(state.tier);
        }
    }

    // ---- Selection handlers ------------------------------------------------

    function selectTier(tier) {
        if (tier === state.tier) {
            return;
        }
        state.tier = tier;
        setActive(tierGrid, "tier", tier);
        updateGroupVisibility();

        // Swap the column list to the tier's column set. If the current column
        // isn't valid for the new tier, drop it and clear the readout.
        const columns = columnsForTier(tier);
        buildColumnButtons(columns);
        if (state.column && columns.includes(state.column)) {
            setActive(channelGrid, "column", state.column);
            analyze();
        } else {
            state.column = null;
            resultsEl.hidden = true;
            setStatus(`${tier} tier — select a column.`);
        }
    }

    function selectColumn(column) {
        state.column = column;
        setActive(channelGrid, "column", column);
        analyze();
    }

    function selectGroup(group) {
        state.group = group;
        setActive(groupGrid, "group", group);
        if (state.column) {
            analyze();
        }
    }

    // Fill the Dataset Telemetry readout from real, derived numbers. Best-effort:
    // if the endpoint is unreachable the honest static defaults in the HTML stand.
    async function loadOverview() {
        try {
            const res = await fetch(`${apiBase}/api/overview`);
            if (!res.ok) {
                return;
            }
            const o = await res.json();
            const set = (id, val) => {
                const el = document.getElementById(id);
                if (el && val !== undefined && val !== null) {
                    el.textContent = val;
                }
            };
            set("tel-source", o.dataset);
            set("tel-rows", o.rows);
            set("tel-cols", o.columns);
            set("tel-numeric", o.numeric);
            set("tel-categorical", o.categorical);
            set("tel-complete", o.complete);
            set("tel-reduced", o.reduced);
        } catch {
            // leave the static defaults in place
        }
    }

    // ---- Analysis + rendering ---------------------------------------------

    // Fetch the selected tier/column/group and render the (possibly nested) result.
    async function analyze() {
        if (!state.column || busy) {
            return;
        }

        busy = true;
        resultsEl.hidden = true;
        const grouped = tierSupportsGroup(state.tier) && state.group;
        const groupLabel = grouped ? ` grouped by ${state.group}` : "";
        setStatus(`Running ${state.tier} analysis of ${state.column}${groupLabel}…`);

        let url = `${apiBase}/api/analyze/${state.tier}/${encodeURIComponent(state.column)}`;
        if (grouped) {
            url += `?group=${encodeURIComponent(state.group)}`;
        }

        try {
            const res = await fetch(url);
            const data = await res.json();

            if (res.ok) {
                renderResult(data);
                setStatus(`${state.tier} analysis of ${state.column}${groupLabel}:`);
            } else {
                const detail = data.detail || `HTTP ${res.status}`;
                setStatus(`Could not analyze ${state.column}: ${detail}`, true);
            }
        } catch (err) {
            setStatus(`Could not analyze ${state.column}: ${err.message}`, true);
        } finally {
            busy = false;
        }
    }

    function isPlainObject(v) {
        return v !== null && typeof v === "object" && !Array.isArray(v);
    }

    // Turn "ci_lower" -> "ci lower" (the CSS uppercases the label).
    function prettify(key) {
        return String(key).replace(/_/g, " ");
    }

    // Render a leaf value as a DOM node, with a few readability touches:
    // booleans become a colored YES/NO verdict, nulls a faint dash, arrays a list.
    function formatValue(value) {
        if (value === null || value === undefined) {
            const s = document.createElement("span");
            s.className = "value-null";
            s.textContent = "—";
            return s;
        }
        if (typeof value === "boolean") {
            const s = document.createElement("span");
            s.className = "value-flag " + (value ? "is-true" : "is-false");
            s.textContent = value ? "YES" : "NO";
            return s;
        }
        if (Array.isArray(value)) {
            return document.createTextNode(value.length ? value.join(", ") : "—");
        }
        return document.createTextNode(String(value));
    }

    function renderRow(key, value) {
        const tr = document.createElement("tr");
        const label = document.createElement("td");
        label.className = "label";
        label.textContent = prettify(key);
        const val = document.createElement("td");
        val.className = "value";
        val.appendChild(formatValue(value));
        tr.append(label, val);
        return tr;
    }

    // Recursively render a result object: scalar entries collect into a table,
    // nested objects become titled sub-groups (which recurse). This renders every
    // tier's shape without hard-coding any one of them.
    function renderInto(container, obj) {
        const rows = [];
        const groups = [];
        for (const [k, v] of Object.entries(obj)) {
            if (isPlainObject(v) || (Array.isArray(v) && v.some(isPlainObject))) {
                groups.push([k, v]);
            } else {
                rows.push([k, v]);
            }
        }

        if (rows.length) {
            const table = document.createElement("table");
            const tbody = document.createElement("tbody");
            for (const [k, v] of rows) {
                tbody.appendChild(renderRow(k, v));
            }
            table.appendChild(tbody);
            container.appendChild(table);
        }

        for (const [k, v] of groups) {
            const group = document.createElement("div");
            group.className = "result-group";
            const title = document.createElement("p");
            title.className = "result-group-title";
            title.textContent = prettify(k);
            group.appendChild(title);
            if (Array.isArray(v)) {
                v.forEach((item) => {
                    if (isPlainObject(item)) {
                        renderInto(group, item);
                    }
                });
            } else {
                renderInto(group, v);
            }
            container.appendChild(group);
        }
    }

    function renderResult(data) {
        resultsEl.innerHTML = "";
        renderInto(resultsEl, data);
        resultsEl.hidden = false;
    }

    // ---- Wiring ------------------------------------------------------------

    const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

    function setLoaderProgress(pct) {
        if (loaderBarFill) {
            loaderBarFill.style.width = `${pct}%`;
        }
        if (loaderPercent) {
            loaderPercent.textContent = `${Math.round(pct)}%`;
        }
    }

    // Drive the boot bar: churn the module log fast while easing the fill toward
    // ~97% (an ease-out that keeps creeping so it never visually stalls). Under
    // prefers-reduced-motion, skip the strobing log and just fill calmly.
    // Returns the timer id to clear when the real load settles.
    function runLoaderSequence() {
        const reduce = window.matchMedia &&
            window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        let progress = 0;

        if (reduce) {
            if (loaderMessage) {
                loaderMessage.textContent = "Loading…";
            }
            return setInterval(() => {
                progress = Math.min(96, progress + 4);
                setLoaderProgress(progress);
            }, 120);
        }

        // Uneven pacing: advance through a handful of checkpoints instead of one
        // smooth glide. Each surge covers a random slice of the remaining bar at a
        // bimodal speed (clearly fast or clearly slow), then stalls for a variable
        // beat before releasing to the next -- so some parts race and some hang,
        // and no two boots pace the same.
        let ceiling = 0;
        let speed = 0;
        let dwell = 0;
        const nextCheckpoint = () => {
            ceiling += (97 - ceiling) * (0.25 + Math.random() * 0.5);
            speed = Math.random() < 0.5
                ? 0.18 + Math.random() * 0.14   // fast surge
                : 0.05 + Math.random() * 0.05;  // slow crawl
            dwell = Math.random() < 0.55
                ? (Math.random() * 4) | 0        // barely pauses
                : (6 + Math.random() * 16) | 0;  // noticeable hang
        };
        nextCheckpoint();

        // The bar ticks fast for smooth motion, but the joke line only refreshes
        // every few ticks so each one lingers long enough to actually read.
        const TEXT_EVERY = 0.5; // 6 * 45ms ≈ 270ms per line
        let tick = 0;
        if (loaderMessage) {
            loaderMessage.textContent = randomBootLine();
        }

        return setInterval(() => {
            if (progress < ceiling - 0.4) {
                progress = Math.min(97, progress + (ceiling - progress) * speed + 0.25);
            } else if (dwell > 0) {
                dwell -= 1; // stall at the checkpoint
            } else if (ceiling < 96) {
                nextCheckpoint(); // release into the next surge
            }
            setLoaderProgress(progress);
            tick += 1;
            if (loaderMessage && tick % TEXT_EVERY === 0) {
                loaderMessage.textContent = randomBootLine();
            }
        }, 45);
    }

    // Snap the bar to 100% and settle the log on a final line.
    function finishLoaderSequence(timer) {
        clearInterval(timer);
        setLoaderProgress(100);
        if (loaderMessage) {
            loaderMessage.textContent = "Done. No data was harmed.";
        }
    }

    // Show the splash, then reveal the app once BOTH the minimum display time has
    // passed AND the initial column load has settled. Waiting on the load too
    // means the splash also covers the real latency of a cold Render start,
    // instead of uncovering a still-empty dropdown.
    async function boot() {
        if (!loader) {
            loadColumns();
            return;
        }
        const timer = runLoaderSequence();
        await Promise.all([delay(LOADER_MIN_MS), loadColumns()]);
        finishLoaderSequence(timer);
        await delay(200); // hold on "Done." for a beat before the transition

        // Hand off to the cosmetic boot transition (Web/JS/transition.js), which
        // covers the screen, hides the loader behind it, plays its flourish, then
        // fades to reveal the app. If the file isn't present, just fade the loader.
        if (typeof window.playBootTransition === "function") {
            await window.playBootTransition(loader);
        } else {
            loader.classList.add("is-hidden");
        }
    }

    // Each grid is a selector: a chip click drives the corresponding choice.
    if (tierGrid) {
        tierGrid.addEventListener("click", (e) => {
            const btn = e.target.closest(".channel");
            if (btn) {
                selectTier(btn.dataset.tier);
            }
        });
    }
    if (channelGrid) {
        channelGrid.addEventListener("click", (e) => {
            const btn = e.target.closest(".channel");
            if (btn) {
                selectColumn(btn.dataset.column);
            }
        });
    }
    if (groupGrid) {
        groupGrid.addEventListener("click", (e) => {
            const btn = e.target.closest(".channel");
            if (btn) {
                selectGroup(btn.dataset.group);
            }
        });
    }

    boot();
})();
