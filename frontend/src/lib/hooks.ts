// Data-loading hooks.
//
// Every route that needs the backend gets it through one of these, so the
// fetch-on-mount pattern -- the live flag that stops a state update after
// unmount, the error string, the loading state -- is written once instead of
// re-derived slightly differently in each route.

import { useCallback, useEffect, useState } from "react";
import {
  analyze,
  ApiError,
  fetchColumns,
  fetchDatasets,
  fetchOverview,
  fetchRuns,
} from "./api";
import type { DatasetInfo, EngineObject } from "../types/engine";

/** Turn any thrown value into a message worth showing a person. */
function messageOf(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return `${err.message}`;
  return fallback;
}

/**
 * Run an async load on mount, discarding the result if the component unmounted
 * first. The `live` flag is the whole reason this is shared: forgetting it is
 * the classic way to get a state update on an unmounted component, and it is
 * easy to forget in exactly one of five routes.
 */
function useAsync<T>(load: () => Promise<T>, deps: unknown[], fallback: string) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let live = true;
    setLoading(true);
    setError(null);
    void load()
      .then((value) => {
        if (live) setData(value);
      })
      .catch((err: unknown) => {
        if (live) setError(messageOf(err, fallback));
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, error, loading };
}

/** Columns + telemetry, for the Overview. */
export function useDataset() {
  const { data, error, loading } = useAsync(
    async () => {
      const [columns, overview] = await Promise.all([fetchColumns(), fetchOverview()]);
      return { columns, overview };
    },
    [],
    "Could not reach the backend. Start it with: uvicorn main:app",
  );
  return {
    columns: data?.columns ?? null,
    overview: data?.overview ?? null,
    error,
    loading,
  };
}

/** Everything the Studio index shows. */
export function useStudioIndex() {
  const { data, error } = useAsync(
    async () => {
      const [columns, overview, datasets, recent] = await Promise.all([
        fetchColumns(),
        fetchOverview(),
        fetchDatasets(),
        fetchRuns(5),
      ]);
      return { columns, overview, datasets, recent };
    },
    [],
    "Could not reach the backend.",
  );
  return {
    columns: data?.columns ?? null,
    overview: data?.overview ?? null,
    datasets: data?.datasets ?? [],
    recent: data?.recent ?? [],
    error,
  };
}

/** The full run log. */
export function useRuns() {
  const { data, error } = useAsync(() => fetchRuns(), [], "Could not read the run log.");
  return { runs: data ?? [], error };
}

/** The dataset inventory on its own, for the Docs page. */
export function useDatasets(): DatasetInfo[] {
  const { data } = useAsync(() => fetchDatasets(), [], "Could not read the dataset list.");
  return data ?? [];
}

export interface AnalysisState {
  result: EngineObject | null;
  elapsedMs: number;
  error: string | null;
  loading: boolean;
}

/**
 * One analysis, re-run whenever the selection changes.
 *
 * Results are cached per (tier, column, group) for the life of the page: the
 * dataset is immutable while the process runs, so a repeat selection is served
 * from memory rather than re-asking a server that would answer from its own
 * lru_cache anyway.
 */
export function useAnalysis(
  tier: string,
  column: string | null,
  group: string,
): AnalysisState & { rerun: () => void } {
  const [cache] = useState(() => new Map<string, { result: EngineObject; elapsedMs: number }>());
  const [state, setState] = useState<AnalysisState>({
    result: null,
    elapsedMs: 0,
    error: null,
    loading: false,
  });
  const [nonce, setNonce] = useState(0);
  const rerun = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    if (!column) return;
    const key = `${tier} ${column} ${group}`;
    const hit = cache.get(key);
    if (hit) {
      setState({ ...hit, error: null, loading: false });
      return;
    }

    let live = true;
    setState((s) => ({ ...s, loading: true, error: null }));
    void analyze(tier, column, group || null)
      .then((outcome) => {
        cache.set(key, outcome);
        if (live) setState({ ...outcome, error: null, loading: false });
      })
      .catch((err: unknown) => {
        if (live) {
          setState({
            result: null,
            elapsedMs: 0,
            error: messageOf(err, "Analysis failed — is the backend running?"),
            loading: false,
          });
        }
      });
    return () => {
      live = false;
    };
  }, [tier, column, group, nonce, cache]);

  return { ...state, rerun };
}
