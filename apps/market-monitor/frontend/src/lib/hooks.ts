import { useEffect, useMemo, useRef, useState } from "react";
import {
  useApi,
  type DatesResponse,
  type ModuleId,
  type Params,
  type RowDetailResponse,
  type RowsResponse,
  type SummaryResponse,
} from "./api";

export type SnapshotPhase = "loading" | "ready" | "empty" | "error";

export type SnapshotState<S> = {
  /** Outcome of the last settled load; `loading` until the first one. */
  phase: SnapshotPhase;
  /** A request is in flight (initial load, refresh or date change). */
  fetching: boolean;
  dates: string[];
  /** The date picked in the selector (may be ahead of `summaryDate`). */
  date: string | undefined;
  /** The date the held summary belongs to. */
  summaryDate: string | undefined;
  setDate(date: string): void;
  summary: S | null;
  asOf: string | null;
  revision: number;
  reload(): void;
};

type Load<S> = {
  phase: SnapshotPhase;
  dates: string[];
  /** The date resolved against `dates` by the last dates response. */
  date: string | undefined;
  summary: SummaryResponse<S> | null;
  summaryDate: string | undefined;
};

type Request = {
  /** Bumped by Refresh: dates are fetched again, then the summary. */
  revision: number;
  /** The wanted date; `undefined` means the newest one. */
  date: string | undefined;
  /** Whether this request starts with the dates list. */
  withDates: boolean;
};

/**
 * Dates of a module (newest first), the selected date (latest by default) and
 * that date's summary. A module with no snapshot is `empty`.
 *
 * Every Refresh sends one dates request followed by one summary request; a
 * date change sends only the summary request. The previous content stays in
 * place while a request is in flight (`fetching`), and a response that was
 * superseded by a newer request is dropped.
 */
export function useSnapshot<S>(module: ModuleId): SnapshotState<S> {
  const { get, ready } = useApi();
  const [request, setRequest] = useState<Request>({
    revision: 0,
    date: undefined,
    withDates: true,
  });
  const [load, setLoad] = useState<Load<S>>({
    phase: "loading",
    dates: [],
    date: undefined,
    summary: null,
    summaryDate: undefined,
  });
  const [fetching, setFetching] = useState(true);
  const datesRef = useRef<string[]>([]);
  datesRef.current = load.dates;

  useEffect(() => {
    if (!ready) return;
    const abort = new AbortController();
    const live = () => !abort.signal.aborted;
    setFetching(true);
    void (async () => {
      let dates = datesRef.current;
      let date = request.date;
      if (request.withDates) {
        const result = await get<DatesResponse>(
          `/v1/${module}/dates`,
          {},
          abort.signal,
        );
        if (!live()) return;
        if (result.status !== "ok") {
          setLoad({
            phase: result.status === "empty" ? "empty" : "error",
            dates: [],
            date: undefined,
            summary: null,
            summaryDate: undefined,
          });
          setFetching(false);
          return;
        }
        dates = Array.isArray(result.data.dates) ? result.data.dates : [];
        if (!dates.length) {
          setLoad({
            phase: "empty",
            dates: [],
            date: undefined,
            summary: null,
            summaryDate: undefined,
          });
          setFetching(false);
          return;
        }
        if (!date || !dates.includes(date)) date = dates[0];
        const chosen = date;
        setLoad((prev) => ({ ...prev, dates, date: chosen }));
      }
      if (!date) return;
      const result = await get<SummaryResponse<S>>(
        `/v1/${module}/summary`,
        { date },
        abort.signal,
      );
      if (!live()) return;
      if (result.status === "ok")
        setLoad({
          phase: "ready",
          dates,
          date,
          summary: result.data,
          summaryDate: date,
        });
      else
        setLoad({
          phase: result.status,
          dates,
          date,
          summary: null,
          summaryDate: undefined,
        });
      setFetching(false);
    })();
    return () => abort.abort();
  }, [get, ready, module, request]);

  return {
    phase: load.phase,
    fetching,
    dates: load.dates,
    date: request.withDates ? load.date : request.date,
    summaryDate: load.summaryDate,
    setDate: (date) =>
      setRequest((prev) =>
        prev.date === date ? prev : { ...prev, date, withDates: false },
      ),
    summary: load.summary?.summary ?? null,
    asOf: load.summary?.as_of ?? null,
    revision: request.revision,
    reload: () =>
      setRequest((prev) => ({
        revision: prev.revision + 1,
        date: prev.date,
        withDates: true,
      })),
  };
}

export type RowQuery = {
  page: number;
  size: number;
  sort?: string;
  order?: "asc" | "desc";
  q?: string;
  filters: Record<string, string | undefined>;
};

export function rowParams(date: string, query: RowQuery): Params {
  const params: Params = { date, page: query.page, size: query.size };
  if (query.sort) {
    params.sort = query.sort;
    params.order = query.order ?? "desc";
  }
  if (query.q) params.q = query.q;
  for (const [field, value] of Object.entries(query.filters))
    if (value) params[`f.${field}`] = value;
  return params;
}

/** One server-side page of rows; refetches when the query or date changes. */
export function usePagedRows<R>(
  module: ModuleId,
  date: string | undefined,
  query: RowQuery,
  revision = 0,
) {
  const { get, ready } = useApi();
  const [state, setState] = useState<{
    items: R[];
    total: number;
    loading: boolean;
    error: string | null;
  }>({ items: [], total: 0, loading: true, error: null });
  const key = useMemo(
    () => (date ? JSON.stringify(rowParams(date, query)) : ""),
    [date, query],
  );
  useEffect(() => {
    if (!ready || !key || !date) return;
    const abort = new AbortController();
    setState((prev) => ({ ...prev, loading: true, error: null }));
    get<RowsResponse<R>>(
      `/v1/${module}/rows`,
      JSON.parse(key) as Params,
      abort.signal,
    ).then((result) => {
      if (abort.signal.aborted) return;
      if (result.status === "ok")
        setState({
          items: Array.isArray(result.data.items) ? result.data.items : [],
          total: Number.isFinite(result.data.total) ? result.data.total : 0,
          loading: false,
          error: null,
        });
      else
        setState({
          items: [],
          total: 0,
          loading: false,
          error: result.status === "empty" ? "no_data" : result.code,
        });
    });
    return () => abort.abort();
  }, [get, ready, module, key, date, revision]);
  return state;
}

/** One row and its optional detail, loaded when `code` is set. */
export function useRowDetail<R, D>(
  module: ModuleId,
  code: string | null,
  date: string | undefined,
) {
  const { get } = useApi();
  const [state, setState] = useState<{
    row: R | null;
    detail: D | null;
    loading: boolean;
    error: string | null;
  }>({ row: null, detail: null, loading: false, error: null });
  useEffect(() => {
    if (!code) {
      setState({ row: null, detail: null, loading: false, error: null });
      return;
    }
    const abort = new AbortController();
    setState({ row: null, detail: null, loading: true, error: null });
    get<RowDetailResponse<R, D>>(
      `/v1/${module}/rows/${encodeURIComponent(code)}`,
      { date },
      abort.signal,
    ).then((result) => {
      if (abort.signal.aborted) return;
      if (result.status === "ok")
        setState({
          row: result.data.row ?? null,
          detail: result.data.detail ?? null,
          loading: false,
          error: null,
        });
      else
        setState({
          row: null,
          detail: null,
          loading: false,
          error: result.status === "error" ? result.code : "no_data",
        });
    });
    return () => abort.abort();
  }, [get, module, code, date]);
  return state;
}

/** Largest page the backend serves (`maxPageSize` in service/api.go). */
export const MAX_PAGE_SIZE = 200;

/**
 * The distinct values of a text field over a module's rows for one date, read
 * with at most two page requests of the largest size. Loaded once per date and
 * module; a Refresh does not repeat it. Rows past the second page are not
 * covered, so callers union this with any list the summary already carries.
 */
export function useRowValues(
  module: ModuleId,
  date: string | undefined,
  field: string,
): string[] {
  const { get, ready } = useApi();
  const [values, setValues] = useState<string[]>([]);
  useEffect(() => {
    if (!ready || !date) return;
    const abort = new AbortController();
    void (async () => {
      const seen = new Set<string>();
      for (let page = 1; page <= 2; page++) {
        const result = await get<RowsResponse<Record<string, unknown>>>(
          `/v1/${module}/rows`,
          { date, page, size: MAX_PAGE_SIZE },
          abort.signal,
        );
        if (abort.signal.aborted) return;
        if (result.status !== "ok") break;
        const items = Array.isArray(result.data.items) ? result.data.items : [];
        for (const item of items) {
          const value = item[field];
          if (typeof value === "string" && value) seen.add(value);
        }
        if (page * MAX_PAGE_SIZE >= result.data.total) break;
      }
      setValues([...seen]);
    })();
    return () => abort.abort();
  }, [get, ready, module, date, field]);
  return values;
}
