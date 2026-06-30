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

    const columnSelect = document.getElementById("column");
    const analyzeBtn = document.getElementById("analyze");
    const statusEl = document.getElementById("status");
    const resultsTable = document.getElementById("results");
    const resultsBody = resultsTable.querySelector("tbody");

    // Order to display the stats in (keys returned by /api/stats/{column}).
    const STAT_ROWS = ["mean", "median", "mode", "min", "max", "std", "variance"];

    function setStatus(message, isError = false) {
        statusEl.textContent = message;
        statusEl.classList.toggle("error", isError);
    }

    // Find a backend that answers /api/columns and populate the dropdown.
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

            columnSelect.innerHTML = "";
            for (const name of data.columns) {
                const opt = document.createElement("option");
                opt.value = name;
                opt.textContent = name;
                columnSelect.appendChild(opt);
            }
            analyzeBtn.disabled = false;
            setStatus(`Loaded ${data.columns.length} columns from ${data.dataset}.`);
            return;
        }

        setStatus("Could not reach the backend. Start it with: uvicorn main:app (from the repo root).", true);
    }

    // Fetch stats for the selected column and render them as a table.
    async function analyze() {
        const column = columnSelect.value;
        if (!column) {
            return;
        }

        analyzeBtn.disabled = true;
        resultsTable.hidden = true;
        setStatus(`Analyzing ${column}…`);

        try {
            const res = await fetch(`${apiBase}/api/stats/${encodeURIComponent(column)}`);
            const data = await res.json();

            if (res.ok) {
                resultsBody.innerHTML = "";
                for (const key of STAT_ROWS) {
                    const row = document.createElement("tr");
                    row.innerHTML = `<td class="label">${key}</td><td class="value">${data[key]}</td>`;
                    resultsBody.appendChild(row);
                }
                resultsTable.hidden = false;
                setStatus(`Stats for ${data.column}:`);
            } else {
                const detail = data.detail || `HTTP ${res.status}`;
                setStatus(`Could not analyze ${column}: ${detail}`, true);
            }
        } catch (err) {
            setStatus(`Could not analyze ${column}: ${err.message}`, true);
        } finally {
            analyzeBtn.disabled = false;
        }
    }

    analyzeBtn.addEventListener("click", analyze);
    loadColumns();
})();
