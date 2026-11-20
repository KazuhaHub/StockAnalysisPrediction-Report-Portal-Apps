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
 * Typed GET helper over the Portal backend relay. A 404 `no_data` (a module
 * with no snapshot yet) is reported as `empty`, everything else that is not a
 * 200 as `error` with the backend's short code.
 */
export function useApi() {
  const backend = useAppBackend();
  const { request } = backend;
  const get = useCallback(
    async <T>(
      path: string,
      params: Params = {},
      signal?: AbortSignal,
    ): Promise<ApiResult<T>> => {
      try {
        const response = await request(
          { method: "GET", path: path + queryString(params), body: "" },
          signal,
        );
        let body: unknown = null;
        try {
          body = JSON.parse(response.body);
        } catch {
          body = null;
        }
        if (response.status === 200 && body !== null)
          return { status: "ok", data: body as T };
        const code =
          body && typeof body === "object" && "error" in body
            ? String((body as { error: unknown }).error)
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
  return { available: backend.available, ready: backend.ready, get };
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
export type RunView = {
  id: string;
  job: string;
  status: string;
  attempt: number;
  queued_at: string;
  started_at?: string;
  finished_at?: string;
  error?: string;
  installed?: string[];
};
