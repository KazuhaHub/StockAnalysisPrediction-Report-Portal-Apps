import { useCallback } from "react";
import { useAppBackend } from "@portal-app/sdk/root-v2";

export type ModuleId = "risk" | "margin" | "sentiment" | "etf" | "panorama";

export type ApiResult<T> =
  | { status: "ok"; data: T }
  | { status: "empty" }
  | { status: "error"; code: string };

export type Params = Record<string, string | number | undefined>;

export function queryString(params: Params): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === "") continue;
    search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

/**
 * Typed helpers over the Portal backend relay. A 404 `no_data` (a module
 * with no snapshot yet) is reported as `empty`, everything else that is not a
 * 2xx as `error` with the backend's short code and HTTP status.
 */
export function useApi() {
  const backend = useAppBackend();
  const { request } = backend;
  const send = useCallback(
    async <T>(
      method: "GET" | "POST",
      path: string,
      body: string,
      signal?: AbortSignal,
    ): Promise<ApiResult<T>> => {
      try {
        const response = await request({ method, path, body }, signal);
        let parsed: unknown = null;
        try {
          parsed = JSON.parse(response.body);
        } catch {
          parsed = null;
        }
        if (response.status >= 200 && response.status < 300 && parsed !== null)
          return { status: "ok", data: parsed as T };
        const code =
          parsed && typeof parsed === "object" && "error" in parsed
            ? String((parsed as { error: unknown }).error)
            : "unavailable";
        if (response.status === 404 && code === "no_data")
          return { status: "empty" };
        return { status: "error", code };
      } catch {
        return { status: "error", code: "unavailable" };
      }
    },
    [request],
  );
  const get = useCallback(
    <T>(path: string, params: Params = {}, signal?: AbortSignal) =>
      send<T>("GET", path + queryString(params), "", signal),
    [send],
  );
  const post = useCallback(
    <T>(path: string, body: unknown, signal?: AbortSignal) =>
      send<T>("POST", path, JSON.stringify(body), signal),
    [send],
  );
  return { available: backend.available, ready: backend.ready, get, post };
}

export type DatesResponse = { module: ModuleId; dates: string[] };
export type SummaryResponse<S> = {
  module: ModuleId;
  as_of: string;
  summary: S;
};
export type RowsResponse<R> = {
  module: ModuleId;
  as_of: string;
  page: number;
  size: number;
  total: number;
  items: R[];
};
export type RowDetailResponse<R, D> = {
  module: ModuleId;
  as_of: string;
  row: R;
  detail: D | null;
};

/** Admin-only routes: the backend refuses them unless the host marked the request as the admin view. */
export type RunStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "interrupted";
export type RunSource = "schedule" | "manual" | "bootstrap" | "platform";
export type AdminRun = {
  id: string;
  job: string;
  source: RunSource;
  status: RunStatus | string;
  attempt: number;
  queued_at: string;
  started_at?: string;
  finished_at?: string;
  exit_code: number;
  error?: string;
  installed?: string[];
};
export type AdminSlot = {
  days: string[];
  hour: number;
  minute: number;
  fallback: boolean;
};
export type AdminJob = {
  name: string;
  schedule: AdminSlot[];
  next_run?: string;
  last_run: AdminRun | null;
};
export type AdminJobs = { time_zone: string; jobs: AdminJob[] };
export type AdminRuns = { runs: AdminRun[] };
export type AdminLog = { run_id: string; log: string; truncated: boolean };
export type RunNowResult = { run: AdminRun; duplicate: boolean };
