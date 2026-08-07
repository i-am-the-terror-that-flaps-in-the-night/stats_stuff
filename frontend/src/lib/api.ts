// The API client.
//
// This page can be served three ways, and the API lives somewhere different in
// each:
//   * by the backend itself (uvicorn)        -> API is on the SAME origin
//   * by a separate static server (Live Server, `vite preview`) -> API elsewhere
//   * opened straight off disk (file://)     -> API elsewhere
//
// Rather than guess, we probe: try the same origin first, then the usual local
// backend ports. The first origin that answers /api/columns wins and is reused
// for every later call. A 404 here means "served, but not by the API" -- exactly
// the static-preview case. This is the same strategy the old Web/JS/script.js
// used; it is kept because the Live Server preview workflow depends on it.

import type {
  BoxResponse,
  ColumnsResponse,
  CorrelationResponse,
  DatasetInfo,
  EngineObject,
  HistogramResponse,
  OverviewResponse,
  RecordRunBody,
  RunRecord,
  ScatterResponse,
} from "../types/engine";

const API_CANDIDATES = ["", "http://127.0.0.1:8000", "http://localhost:8000"] as const;

let apiBase: string | null = null;
let discovery: Promise<string> | null = null;

/** Thrown for a reached-but-unhappy backend, carrying the HTTP status. */
export class ApiError extends Error {
  readonly status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/** Find the origin serving the API, probing each candidate once. Cached. */
export function resolveApiBase(): Promise<string> {
  if (apiBase !== null) return Promise.resolve(apiBase);
  discovery ??= (async () => {
    for (const base of API_CANDIDATES) {
      try {
        const res = await fetch(`${base}/api/columns`, { headers: { Accept: "application/json" } });
        if (res.ok) {
          apiBase = base;
          return base;
        }
      } catch {
        // Unreachable candidate (wrong port, CORS, offline) -- try the next.
      }
    }
    throw new Error("No backend found. Start it with: uvicorn main:app");
  })();
  return discovery;
}

/**
 * The API origin if one has already been found, else null.
 * Used to point the Studio/Docs links at a backend when this page is served
 * statically -- those routes only exist where the API does.
 */
export function knownApiBase(): string | null {
  return apiBase;
}

/**
 * In-memory response cache, keyed by path.
 *
 * The layer above the HTTP cache. Every GET here is a pure function of its URL
 * for the life of the deploy — the server says so with a long max-age and an
 * ETag — so once this tab has an answer there is no reason to ask again, not
 * even to revalidate. Clicking back and forth between two columns on the
 * Figures page is then free: no fetch, no 304, no parse.
 *
 * PROMISES are stored, not results. Two components mounting at once (the
 * Figures page fires four requests on load, and the Studio pages ask for the
 * column list from two places) would otherwise both miss an empty cache and
 * send duplicate requests; caching the in-flight promise means the second
 * caller waits on the first one's response.
 *
 * A failed request is evicted, so an error is retried rather than remembered.
 * Nothing else is ever evicted: the whole key space is a few hundred kilobytes
 * of JSON, and a page load discards it anyway.
 */
const responseCache = new Map<string, Promise<unknown>>();

/** Drop everything memoized. Exposed for tests and for a manual refresh. */
export function clearApiCache(): void {
  responseCache.clear();
}

async function getJson<T>(path: string): Promise<T> {
  const cached = responseCache.get(path);
  if (cached) return cached as Promise<T>;

  const pending = requestJson<T>(path).catch((err: unknown) => {
    responseCache.delete(path);
    throw err;
  });
  responseCache.set(path, pending);
  return pending;
}

async function requestJson<T>(path: string): Promise<T> {
  const base = await resolveApiBase();
  const res = await fetch(`${base}${path}`, { headers: { Accept: "application/json" } });
  if (!res.ok) {
    // FastAPI puts the useful message in `detail`; fall back to the status line.
    let detail = `HTTP ${res.status}`;
    try {
      const body = (await res.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      // Non-JSON error body -- the status is all we have.
    }
    throw new ApiError(detail, res.status);
  }
  return (await res.json()) as T;
}

export function fetchColumns(): Promise<ColumnsResponse> {
  return getJson<ColumnsResponse>("/api/columns");
}

export function fetchOverview(): Promise<OverviewResponse> {
  return getJson<OverviewResponse>("/api/overview");
}

export function fetchDatasets(): Promise<DatasetInfo[]> {
  return getJson<DatasetInfo[]>("/api/datasets");
}

export function fetchRuns(limit?: number): Promise<RunRecord[]> {
  const query = limit === undefined ? "" : `?limit=${limit}`;
  return getJson<RunRecord[]>(`/api/runs${query}`);
}

// ---- Figures --------------------------------------------------------------
// Chart-ready aggregates. Each is a pure function of the (immutable) dataset,
// so the server memoizes them and marks them cacheable; the browser mostly
// answers a repeat view out of its own HTTP cache without a round trip.

const enc = encodeURIComponent;

export function fetchHistogram(column: string): Promise<HistogramResponse> {
  return getJson<HistogramResponse>(`/api/figures/histogram/${enc(column)}`);
}

export function fetchBox(column: string, group: string | null): Promise<BoxResponse> {
  const query = group ? `?group=${enc(group)}` : "";
  return getJson<BoxResponse>(`/api/figures/box/${enc(column)}${query}`);
}

export function fetchScatter(x: string, y: string): Promise<ScatterResponse> {
  return getJson<ScatterResponse>(`/api/figures/scatter/${enc(x)}/${enc(y)}`);
}

export function fetchCorrelation(): Promise<CorrelationResponse> {
  return getJson<CorrelationResponse>("/api/figures/correlation");
}

/** One analysis, with the round-trip time the UI reports. */
export interface AnalyzeOutcome {
  result: EngineObject;
  elapsedMs: number;
}

export async function analyze(
  tier: string,
  column: string,
  group: string | null,
): Promise<AnalyzeOutcome> {
  const query = group ? `?group=${encodeURIComponent(group)}` : "";
  const path = `/api/analyze/${encodeURIComponent(tier)}/${encodeURIComponent(column)}${query}`;
  const started = performance.now();
  const result = await getJson<EngineObject>(path);
  return { result, elapsedMs: Math.round(performance.now() - started) };
}

/** Save a run to the Studio log. */
export async function recordRun(body: RecordRunBody): Promise<RunRecord> {
  const base = await resolveApiBase();
  const res = await fetch(`${base}/api/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new ApiError(`Could not save run (HTTP ${res.status})`, res.status);
  return (await res.json()) as RunRecord;
}

/**
 * Measure one real API round trip, for the "Link · N ms" chip in the top bar.
 *
 * `cache: "no-store"` is required, not incidental. /api/columns is now sent with
 * an hour of max-age, so a normal fetch would be answered out of the browser's
 * own cache without touching the network, and the chip would report 0 ms and a
 * live link on a service that was down. The chip claims to measure the link, so
 * it has to actually use it.
 */
export async function measureLatency(): Promise<number | null> {
  try {
    const base = await resolveApiBase();
    const started = performance.now();
    const res = await fetch(`${base}/api/columns`, {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    if (!res.ok) return null;
    await res.json();
    return Math.round(performance.now() - started);
  } catch {
    return null;
  }
}
