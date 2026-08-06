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
  ColumnsResponse,
  DatasetInfo,
  EngineObject,
  OverviewResponse,
  RecordRunBody,
  RunRecord,
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

async function getJson<T>(path: string): Promise<T> {
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

/** Measure one real API round trip, for the "Link · N ms" chip in the top bar. */
export async function measureLatency(): Promise<number | null> {
  try {
    const base = await resolveApiBase();
    const started = performance.now();
    const res = await fetch(`${base}/api/columns`, { headers: { Accept: "application/json" } });
    if (!res.ok) return null;
    await res.json();
    return Math.round(performance.now() - started);
  } catch {
    return null;
  }
}
