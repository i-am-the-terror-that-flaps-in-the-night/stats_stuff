/* jshint esversion: 11 */
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

    // DOM handles, (re)populated by queryElements(). They are `let`, not `const`,
    // because the SPA router (Web/JS/nav.js) swaps the page markup in place when
    // you return to the Overview, and initInPlace() re-grabs the fresh nodes.
    let statusEl, resultsEl, channelGrid, tierGrid, groupGrid, groupControl;
    let loader, bootChannelsEl, bootLogEl, bootStatusEl;

    function queryElements() {
        statusEl = document.getElementById("status");
        resultsEl = document.getElementById("results");
        channelGrid = document.getElementById("channel-grid");
        tierGrid = document.getElementById("tier-grid");
        groupGrid = document.getElementById("group-grid");
        groupControl = document.getElementById("group-control");
        loader = document.getElementById("loader");
        bootChannelsEl = document.getElementById("boot-channels");
        bootLogEl = document.getElementById("boot-log");
        bootStatusEl = document.getElementById("boot-status");
    }

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
    const LOADER_MIN_MS = 5000;

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

    function pick(pool) {
        return pool[Math.floor(Math.random() * pool.length)];
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

    // Show the real API round-trip in the top bar. A genuine, live number -- it
    // reads as a monitored, fast engine. The chip hides itself while empty, so a
    // backend-less static preview simply never shows it.
    function setLinkLatency(ms) {
        const el = document.getElementById("link-latency");
        if (el) {
            el.innerHTML = `Link · <b>${ms} ms</b>`;
        }
    }

    // Find a backend that answers /api/columns and render the selectors.
    async function loadColumns() {
        for (const base of API_CANDIDATES) {
            let res;
            const probeStart = performance.now();
            try {
                res = await fetch(`${base}/api/columns`);
            } catch {
                continue; // network error (server not here) -- try the next candidate
            }
            if (!res.ok) {
                continue; // answered, but not the API (e.g., 404) -- next candidate
            }
            setLinkLatency(Math.round(performance.now() - probeStart));

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

    function prefersReducedMotion() {
        return Boolean(window.matchMedia &&
            window.matchMedia("(prefers-reduced-motion: reduce)").matches);
    }

    const easeOutCubic = (t) => 1 - Math.pow(1 - t, 3);

    // The real stages the engine walks for each tier -- coerce, drop missing,
    // aggregate, and (for the deeper tiers) fit and test. Surfacing them as a
    // running pipeline shows the work the engine actually does, paced so it reads
    // instead of flickering past. Heavier tiers legitimately list more steps.
    const RUN_STAGES = {
        basic: ["Loading column", "Coercing to numeric", "Dropping missing values",
            "Aggregating statistics", "Formatting output"],
        medium: ["Loading column", "Coercing to numeric", "Profiling distribution",
            "Estimating confidence interval", "Comparing groups", "Formatting output"],
        advanced: ["Aligning columns", "Coercing to numeric", "Building correlation matrix",
            "Fitting OLS regression", "Testing significance", "Scanning for confounders",
            "Formatting output"],
        categorical: ["Loading column", "Tallying categories", "Cross-tabulating",
            "Testing independence (χ²)", "Formatting output"],
    };
    // Nominal run length per tier, ms. The bar holds near the end until the real
    // response lands, so a cold Render start naturally stretches this, never cuts
    // it short.
    const RUN_TOTAL_MS = { basic: 720, medium: 980, advanced: 1300, categorical: 820 };

    // The live dataset shape, pulled from the telemetry readout, to label the run
    // ("Σ 50 rows · 12 fields") -- concrete scale, not a spinner.
    function datasetShape() {
        const rows = document.getElementById("tel-rows");
        const cols = document.getElementById("tel-cols");
        return {
            rows: rows ? rows.textContent.trim() : null,
            cols: cols ? cols.textContent.trim() : null,
        };
    }

    // Build the compute panel and drive it. Returns handles the caller uses to
    // gate on the real response: minTime resolves once the nominal run elapses;
    // finish() releases the bar to 100%; complete resolves when it lands there.
    function runCompute(tier) {
        const stages = RUN_STAGES[tier] || RUN_STAGES.basic;
        const totalMs = RUN_TOTAL_MS[tier] || 800;

        const panel = document.createElement("div");
        panel.className = "compute";

        const head = document.createElement("div");
        head.className = "compute-head";
        const title = document.createElement("span");
        title.className = "compute-title";
        title.textContent = "Computing";
        const tierTag = document.createElement("span");
        tierTag.className = "compute-tier";
        tierTag.textContent = tier;
        const spacer = document.createElement("span");
        spacer.className = "compute-spacer";
        const msEl = document.createElement("span");
        msEl.className = "compute-ms";
        msEl.textContent = "0 ms";
        const pctEl = document.createElement("span");
        pctEl.className = "compute-pct";
        pctEl.textContent = "0%";
        head.append(title, tierTag, spacer, msEl, pctEl);

        const track = document.createElement("div");
        track.className = "compute-track";
        const fillEl = document.createElement("div");
        fillEl.className = "compute-fill";
        track.appendChild(fillEl);

        const list = document.createElement("ul");
        list.className = "compute-stages";
        const stageEls = stages.map((label) => {
            const li = document.createElement("li");
            li.className = "compute-stage";
            const glyph = document.createElement("span");
            glyph.className = "compute-glyph";
            const name = document.createElement("span");
            name.className = "compute-name";
            name.textContent = label;
            const st = document.createElement("span");
            st.className = "compute-state";
            li.append(glyph, name, st);
            list.appendChild(li);
            return li;
        });

        const foot = document.createElement("p");
        foot.className = "compute-foot";
        const shape = datasetShape();
        foot.textContent = shape.rows && shape.cols
            ? `Σ ${shape.rows} rows · ${shape.cols} fields · single pass`
            : "single pass";

        panel.append(head, track, list, foot);
        resultsEl.classList.remove("is-fresh");
        resultsEl.innerHTML = "";
        resultsEl.appendChild(panel);
        resultsEl.hidden = false;

        const n = stageEls.length;
        function apply(p) {
            fillEl.style.width = (p * 100).toFixed(1) + "%";
            pctEl.textContent = Math.round(p * 100) + "%";
            stageEls.forEach((row, i) => {
                const st = row.querySelector(".compute-state");
                row.classList.remove("is-active", "is-done");
                if (p >= (i + 1) / n - 0.0001) {
                    row.classList.add("is-done");
                    st.textContent = "done";
                } else if (p >= i / n) {
                    row.classList.add("is-active");
                    st.textContent = "running";
                } else {
                    st.textContent = "";
                }
            });
        }

        // Reduced motion: no run animation. Mark everything settled and let the
        // caller reveal as soon as the response is in.
        if (prefersReducedMotion()) {
            apply(1);
            return {
                minTime: Promise.resolve(),
                complete: Promise.resolve(),
                finish() {},
                stop() {},
                elapsed: () => 0,
            };
        }

        const start = performance.now();
        let finished = false;
        let raf = 0;
        let stopped = false;
        let resolveMin;
        let resolveComplete;
        let minDone = false;
        const minTime = new Promise((r) => (resolveMin = r));
        const complete = new Promise((r) => (resolveComplete = r));

        function tick() {
            if (stopped) {
                return;
            }
            const now = performance.now();
            const t = (now - start) / totalMs;
            const cap = finished ? 1 : 0.92; // hold shy of done until data lands
            const p = Math.min(cap, easeOutCubic(Math.min(t, 1)));
            apply(p);
            msEl.textContent = Math.round(now - start) + " ms";
            if (t >= 1 && !minDone) {
                minDone = true;
                resolveMin();
            }
            if (finished && p >= 1) {
                apply(1);
                msEl.textContent = Math.round(now - start) + " ms";
                resolveComplete();
                return;
            }
            raf = requestAnimationFrame(tick);
        }
        raf = requestAnimationFrame(tick);

        return {
            minTime,
            complete,
            finish() { finished = true; },
            stop() { stopped = true; cancelAnimationFrame(raf); },
            elapsed: () => Math.round(performance.now() - start),
        };
    }

    // Fetch the selected tier/column/group, run the compute pipeline, and reveal
    // the (possibly nested) result once BOTH the response and the run have landed.
    async function analyze() {
        if (!state.column || busy) {
            return;
        }

        busy = true;
        const grouped = tierSupportsGroup(state.tier) && state.group;
        const groupLabel = grouped ? ` grouped by ${state.group}` : "";
        setStatus(`Analyzing ${state.column}${groupLabel}…`);

        let url = `${apiBase}/api/analyze/${state.tier}/${encodeURIComponent(state.column)}`;
        if (grouped) {
            url += `?group=${encodeURIComponent(state.group)}`;
        }

        const run = runCompute(state.tier);
        try {
            const netStart = performance.now();
            const fetchResult = fetch(url).then(async (res) => {
                // Real network round-trip, refreshed on every run so the top-bar
                // latency chip stays live as you use the engine.
                setLinkLatency(Math.round(performance.now() - netStart));
                return { ok: res.ok, status: res.status, data: await res.json() };
            });
            // Wait for the response AND the nominal run, then let the bar finish.
            const [res] = await Promise.all([fetchResult, run.minTime]);
            run.finish();
            await run.complete;

            if (res.ok) {
                const ms = run.elapsed();
                renderResult(res.data, ms);
                setStatus(
                    `${state.tier} analysis of ${state.column}${groupLabel} — computed in ${ms} ms`
                );
            } else {
                run.stop();
                resultsEl.hidden = true;
                const detail = res.data.detail || `HTTP ${res.status}`;
                setStatus(`Could not analyze ${state.column}: ${detail}`, true);
            }
        } catch (err) {
            run.stop();
            resultsEl.hidden = true;
            setStatus(`Could not analyze ${state.column}: ${err.message}`, true);
        } finally {
            busy = false;
        }
    }

    // Count a freshly-rendered numeric value up from zero so the readout reads as
    // just-computed. Scalars only (the .stat-v headline cells); flags, dashes, and
    // list values are left alone. No-op under reduced motion.
    function animateCounts(root) {
        if (prefersReducedMotion()) {
            return;
        }
        for (const el of root.querySelectorAll(".stat-v")) {
            if (el.childElementCount) {
                continue; // holds a flag/list node, not a bare number
            }
            const raw = el.textContent.trim();
            if (!/^-?\d+(\.\d+)?$/.test(raw)) {
                continue;
            }
            const target = parseFloat(raw);
            const decimals = raw.includes(".") ? raw.split(".")[1].length : 0;
            const start = performance.now();
            const dur = 480;
            (function step(now) {
                const t = Math.min(1, (now - start) / dur);
                el.textContent = (target * easeOutCubic(t)).toFixed(decimals);
                if (t < 1) {
                    requestAnimationFrame(step);
                } else {
                    el.textContent = raw; // land exactly on the real value
                }
            })(start);
        }
    }

    function isPlainObject(v) {
        return v !== null && typeof v === "object" && !Array.isArray(v);
    }

    // A "leaf" is anything formatValue can render in a single cell: a scalar,
    // null, or an array of scalars (never a nested object).
    function isLeaf(v) {
        if (v === null || v === undefined) {
            return true;
        }
        const t = typeof v;
        if (t === "number" || t === "string" || t === "boolean") {
            return true;
        }
        if (Array.isArray(v)) {
            return !v.some(isPlainObject);
        }
        return false;
    }

    // A "record" is a flat object whose every value is a leaf — i.e., a single
    // row's worth of data. A group of same-shaped records renders as a matrix.
    function isRecord(v) {
        if (!isPlainObject(v)) {
            return false;
        }
        const vals = Object.values(v);
        return vals.length > 0 && vals.every(isLeaf);
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

    // A value that won't fit the narrow right half of a label–value cell: a
    // list (predictors, confounders, group order) or a long string. These get
    // the full row so they read left-to-right instead of stacking one word per
    // line in a cramped column.
    function isWideValue(value) {
        if (Array.isArray(value)) {
            return value.length > 2;
        }
        return typeof value === "string" && value.length > 28;
    }

    // One statistic as a compact label–value cell. These tile into a grid
    // (.stat-list) so each value sits next to its label, instead of a two-column
    // table that strands the value at the far side of a wide, hard-to-track row.
    // Wide values (see isWideValue) span the whole row with the label above.
    function renderStat(key, value) {
        const cell = document.createElement("div");
        cell.className = isWideValue(value) ? "stat is-wide" : "stat";
        const label = document.createElement("span");
        label.className = "stat-k";
        label.textContent = prettify(key);
        const val = document.createElement("span");
        val.className = "stat-v";
        val.appendChild(formatValue(value));
        cell.append(label, val);
        return cell;
    }

    // Render a set of same-shaped record groups as one comparison matrix: a row
    // per group, a column per metric. The column set is the union of the records'
    // keys (first-seen order), so ragged records still line up and gaps show as a
    // dash. Far easier to scan than a stack of identical two-column tables.
    function renderMatrix(entries) {
        const cols = [];
        const seen = new Set();
        for (const [, rec] of entries) {
            for (const key of Object.keys(rec)) {
                if (!seen.has(key)) {
                    seen.add(key);
                    cols.push(key);
                }
            }
        }

        const table = document.createElement("table");
        table.className = "matrix";

        const thead = document.createElement("thead");
        const headRow = document.createElement("tr");
        const corner = document.createElement("th");
        corner.className = "matrix-corner";
        headRow.appendChild(corner);
        for (const col of cols) {
            const th = document.createElement("th");
            th.textContent = prettify(col);
            headRow.appendChild(th);
        }
        thead.appendChild(headRow);
        table.appendChild(thead);

        const tbody = document.createElement("tbody");
        for (const [name, rec] of entries) {
            const tr = document.createElement("tr");
            const rowLabel = document.createElement("th");
            rowLabel.className = "matrix-row-label";
            rowLabel.scope = "row";
            rowLabel.textContent = prettify(name);
            tr.appendChild(rowLabel);
            for (const col of cols) {
                const td = document.createElement("td");
                td.className = "value";
                td.appendChild(formatValue(col in rec ? rec[col] : null));
                tr.appendChild(td);
            }
            tbody.appendChild(tr);
        }
        table.appendChild(tbody);

        // Wrap so a wide matrix scrolls sideways instead of stretching the page.
        const scroll = document.createElement("div");
        scroll.className = "results-scroll";
        scroll.appendChild(table);
        return scroll;
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
            const list = document.createElement("div");
            list.className = "stat-list";
            for (const [k, v] of rows) {
                list.appendChild(renderStat(k, v));
            }
            container.appendChild(list);
        }

        // Two or more sibling groups that are all flat, same-kind records (e.g.
        // one correlation per column, or per-group stats) collapse into a single
        // comparison matrix instead of a stack of identical little tables.
        if (groups.length >= 2 && groups.every(([, v]) => isRecord(v))) {
            container.appendChild(renderMatrix(groups));
            return;
        }

        for (const [k, v] of groups) {
            const group = document.createElement("div");
            group.className = "result-group";
            const title = document.createElement("p");
            title.className = "result-group-title";
            title.textContent = prettify(k);
            group.appendChild(title);
            if (Array.isArray(v)) {
                for (const item of v) {
                    if (isPlainObject(item)) {
                        renderInto(group, item);
                    }
                }
            } else {
                renderInto(group, v);
            }
            container.appendChild(group);
        }
    }

    function renderResult(data, ms) {
        resultsEl.innerHTML = "";

        // Result header: what ran, and how long the engine took. The timing is
        // real (measured across the run above), which is the point -- it reads as
        // a fast instrument, not a stalled one.
        const head = document.createElement("div");
        head.className = "results-head";
        const k = document.createElement("span");
        k.className = "results-head-k";
        k.textContent = "Result";
        const tierTag = document.createElement("span");
        tierTag.className = "results-head-tier";
        tierTag.textContent = state.tier;
        const spacer = document.createElement("span");
        spacer.className = "compute-spacer";
        const msTag = document.createElement("span");
        msTag.className = "results-head-ms";
        if (ms != null) {
            msTag.textContent = `${ms} ms`;
        }
        head.append(k, tierTag, spacer, msTag);
        resultsEl.appendChild(head);

        renderInto(resultsEl, data);
        resultsEl.hidden = false;

        // Re-trigger the staggered reveal, then count the headline numbers up.
        resultsEl.classList.remove("is-fresh");
        void resultsEl.offsetWidth; // reflow so the animation restarts each run
        resultsEl.classList.add("is-fresh");
        animateCounts(resultsEl);
    }

    // ---- Wiring ------------------------------------------------------------

    const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

    // ---- Boot splash: staged channels + console feed + status strip --------

    // Staged progress channels. Each fills as the single overall boot value
    // crosses its [start, full] window, so subsystems light up in sequence
    // instead of one bar sliding across.
    const BOOT_CHANNELS = [
        { label: "Core Systems", start: 0, full: 46 },
        { label: "Data Pipeline", start: 12, full: 72 },
        { label: "Stat Modules", start: 32, full: 90 },
        { label: "Interface", start: 52, full: 100 },
    ];

    // Tagged milestone lines, emitted in order as progress passes each `at`.
    const BOOT_MILESTONES = [
        { at: 0, tag: "SYS", text: "Boot sequence initiated" },
        { at: 12, tag: "CORE", text: "Core systems nominal" },
        { at: 26, tag: "DATA", text: "Dataset interface mounted" },
        { at: 44, tag: "STAT", text: "Statistical engine online" },
        { at: 62, tag: "UI", text: "Rendering interface" },
        { at: 80, tag: "NET", text: "API connection established" },
    ];

    // Status tokens that flip from "…" to a lit state as boot proceeds.
    const BOOT_STATUS_STAGES = [
        { key: "data", at: 28, word: "ONLINE" },
        { key: "stat", at: 60, word: "READY" },
        { key: "api", at: 84, word: "CONNECTED" },
    ];

    // Channel tags for the filler (joke) lines that fill the gaps between
    // milestones -- keeps the busy-engine churn with a sense of humor.
    const FILLER_TAGS = ["PROC", "CALC", "DATA", "STAT", "SYS", "MEM"];
    const BOOT_LOG_MAX = 10;

    const bootChannelNodes = [];
    let nextMilestone = 0;

    // Build one channel row (label · track · percent) per BOOT_CHANNELS entry.
    function buildBootChannels() {
        if (!bootChannelsEl) {
            return;
        }
        bootChannelsEl.innerHTML = "";
        bootChannelNodes.length = 0;
        for (const cfg of BOOT_CHANNELS) {
            const li = document.createElement("li");
            li.className = "boot-channel";

            const label = document.createElement("span");
            label.className = "boot-channel-label";
            label.textContent = cfg.label;

            const track = document.createElement("span");
            track.className = "boot-channel-track";
            const fill = document.createElement("span");
            fill.className = "boot-channel-fill";
            track.appendChild(fill);

            const pct = document.createElement("span");
            pct.className = "boot-channel-pct";
            pct.textContent = "0%";

            li.append(label, track, pct);
            bootChannelsEl.appendChild(li);
            bootChannelNodes.push({ cfg, fill, pct });
        }
    }

    // Append a tagged line to the console feed, trimming the oldest so the feed
    // scrolls within its fixed window.
    function addBootLine(tag, text, ok = false) {
        if (!bootLogEl) {
            return;
        }
        const line = document.createElement("div");
        line.className = "boot-log-line";

        const t = document.createElement("span");
        t.className = ok ? "boot-log-tag is-ok" : "boot-log-tag";
        t.textContent = tag;

        const m = document.createElement("span");
        m.className = "boot-log-msg";
        m.textContent = text;

        line.append(t, m);
        bootLogEl.appendChild(line);
        while (bootLogEl.children.length > BOOT_LOG_MAX) {
            bootLogEl.removeChild(bootLogEl.firstChild);
        }
    }

    // Emit any milestone lines whose threshold the progress has now crossed.
    function emitMilestones(overall) {
        while (
            nextMilestone < BOOT_MILESTONES.length &&
            overall >= BOOT_MILESTONES[nextMilestone].at
        ) {
            const m = BOOT_MILESTONES[nextMilestone];
            addBootLine(m.tag, m.text, true);
            nextMilestone += 1;
        }
    }

    // Flip the status tokens as their thresholds are reached.
    function updateBootStatus(overall) {
        if (!bootStatusEl) {
            return;
        }
        for (const s of BOOT_STATUS_STAGES) {
            const item = bootStatusEl.querySelector(`[data-key="${s.key}"]`);
            if (!item) {
                continue;
            }
            const on = overall >= s.at;
            item.classList.toggle("is-on", on);
            const word = item.querySelector("b");
            if (word) {
                word.textContent = on ? s.word : "…";
            }
        }
    }

    // Fan the single overall progress value out across the staged channel bars
    // and the status strip.
    function setLoaderProgress(overall) {
        for (const { cfg, fill, pct } of bootChannelNodes) {
            const span = cfg.full - cfg.start;
            let p = span > 0 ? ((overall - cfg.start) / span) * 100 : 100;
            p = Math.max(0, Math.min(100, p));
            fill.style.width = `${p}%`;
            fill.classList.toggle("is-full", p >= 99.5);
            pct.textContent = `${Math.round(p)}%`;
            pct.classList.toggle("is-on", p >= 99.5);
        }
        updateBootStatus(overall);
    }

    // Drive the boot: ease a single overall value toward ~97%, fanning it out to
    // the channel bars while milestone + filler lines churn in the console feed.
    // Under prefers-reduced-motion, skip the strobing filler and just fill calmly
    // (milestones still post). Returns the timer id to clear when load settles.
    function runLoaderSequence() {
        const reduce = window.matchMedia &&
            window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        let progress = 0;

        if (reduce) {
            return setInterval(() => {
                progress = Math.min(96, progress + 4);
                setLoaderProgress(progress);
                emitMilestones(progress);
            }, 140);
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
            speed = Math.random() < 0.5 ?
                0.18 + Math.random() * 0.14 :   // fast surge
                0.05 + Math.random() * 0.05;    // slow crawl
            dwell = Math.random() < 0.55 ?
                Math.floor(Math.random() * 4) :        // barely pauses
                Math.floor(6 + Math.random() * 16);    // noticeable hang
        };
        nextCheckpoint();

        // The bar ticks fast for smooth motion, but a filler line only posts
        // every few ticks so each one lingers long enough to actually read.
        const FILLER_EVERY = 12; // ~270ms per filler line at 45ms/tick
        let tick = 0;

        return setInterval(() => {
            if (progress < ceiling - 0.4) {
                progress = Math.min(97, progress + (ceiling - progress) * speed + 0.25);
            } else if (dwell > 0) {
                dwell -= 1; // stall at the checkpoint
            } else if (ceiling < 96) {
                nextCheckpoint(); // release into the next surge
            }
            setLoaderProgress(progress);
            emitMilestones(progress);
            tick += 1;
            if (tick % FILLER_EVERY === 0) {
                addBootLine(pick(FILLER_TAGS), randomBootLine());
            }
        }, 45);
    }

    // Snap all channels to 100%, flush any remaining milestones, and sign off.
    function finishLoaderSequence(timer) {
        clearInterval(timer);
        setLoaderProgress(100);
        emitMilestones(100);
        updateBootStatus(100);
        addBootLine("SYS", "All systems nominal — no data harmed.", true);
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
        buildBootChannels();
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
    // Listeners live on the grid container (which persists as its chips rebuild),
    // so this is called once per DOM generation -- first load and each SPA swap.
    function wireEvents() {
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
    }

    // Re-enter the Overview after an SPA swap (Web/JS/nav.js) WITHOUT replaying
    // the boot splash: grab the fresh DOM, reset the selection, wire, and load.
    // A no-op on any page that isn't the Overview (no tier grid to bind).
    function initInPlace() {
        queryElements();
        if (!tierGrid) {
            return;
        }
        state.tier = "basic";
        state.column = null;
        state.group = "";
        numericColumns = [];
        categoricalColumns = [];
        busy = false;
        wireEvents();
        loadColumns();
    }

    window.StatsApp = { initInPlace };

    // First load. Only a genuine Overview (its boot splash markup present) plays
    // the splash; every other page leaves the analysis app dormant until the
    // router swaps the Overview in and calls initInPlace().
    queryElements();
    if (loader && tierGrid) {
        wireEvents();
        boot();
    }
})();
