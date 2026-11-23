// DEVELOPMENT ONLY. A stand-in for the market-monitor Go service that answers
// the same read-only /v1 routes from a directory of snapshot files
// (<dir>/<module>/<YYYY-MM-DD>.json). It is never imported by src/ and is not
// part of dist/ or frontend.zip. Paging, sorting and filtering follow
// queryRows and parseRowQuery in ../../service/store.go and api.go.
import { readdirSync, readFileSync, existsSync } from "node:fs";
import { join } from "node:path";

export const MODULES = ["risk", "margin", "sentiment", "etf", "panorama"];
export const MAX_PAGE_SIZE = 200;
export const MAX_RESPONSE = 1 << 20;
const DATE = /^\d{4}-\d{2}-\d{2}$/;
const FIELD = /^[a-z0-9_]{1,64}$/;

/** Mirror of matchesFilter: equality, or equality with one "|"-separated token. */
export function matchesFilter(value, want) {
  if (typeof value !== "string") return false;
  return value === want || value.split("|").includes(want);
}

function compareValues(a, b) {
  if (typeof a === "number" && typeof b === "number")
    return a < b ? -1 : a > b ? 1 : 0;
  const x = String(a);
  const y = String(b);
  return x < y ? -1 : x > y ? 1 : 0;
}

/** Mirror of queryRows: filter, search, sort (missing values last), page. */
export function queryRows(rows, q) {
  let out = rows.filter((row) => {
    if (q.search) {
      const code = typeof row.code === "string" ? row.code : "";
      const name = typeof row.name === "string" ? row.name : "";
      if (!code.startsWith(q.search) && !name.includes(q.search)) return false;
    }
    return Object.entries(q.filters).every(([field, want]) =>
      matchesFilter(row[field], want),
    );
  });
  if (q.sort) {
    const sign = q.desc ? -1 : 1;
    out = out
      .map((row, index) => ({ row, index }))
      .sort((p, r) => {
        const a = p.row[q.sort] ?? null;
        const b = r.row[q.sort] ?? null;
        if (a === null && b === null) return p.index - r.index;
        if (a === null) return 1;
        if (b === null) return -1;
        return sign * compareValues(a, b) || p.index - r.index;
      })
      .map((entry) => entry.row);
  }
  const total = out.length;
  const start = (q.page - 1) * q.size;
  if (start >= total) return { items: [], total };
  return { items: out.slice(start, start + q.size), total };
}

/** Mirror of parseRowQuery. Returns null for a request the service refuses. */
export function parseRowQuery(params) {
  const out = {
    page: 1,
    size: 50,
    sort: "",
    desc: false,
    search: "",
    filters: {},
  };
  for (const key of new Set(params.keys())) {
    const values = params.getAll(key);
    if (values.length !== 1) return null;
    const v = values[0];
    if (key === "date") continue;
    if (key === "page" || key === "size") {
      const n = /^[+-]?\d+$/.test(v) ? Number(v) : NaN;
      if (
        !Number.isInteger(n) ||
        n < 1 ||
        (key === "size" && n > MAX_PAGE_SIZE) ||
        n > 1_000_000
      )
        return null;
      out[key] = n;
    } else if (key === "sort") {
      if (!FIELD.test(v)) return null;
      out.sort = v;
    } else if (key === "order") {
      if (v !== "asc" && v !== "desc") return null;
      out.desc = v === "desc";
    } else if (key === "q") {
      if (new TextEncoder().encode(v).length > 64) return null;
      out.search = v;
    } else if (key.startsWith("f.")) {
      const field = key.slice(2);
      if (
        !FIELD.test(field) ||
        v === "" ||
        new TextEncoder().encode(v).length > 64 ||
        Object.keys(out.filters).length >= 8
      )
        return null;
      out.filters[field] = v;
    } else return null;
  }
  return out;
}

const SAMPLE_RUNS = [
  ["margin", "succeeded", "schedule"],
  ["etf", "succeeded", "schedule"],
  ["panorama", "failed", "manual"],
  ["sentiment", "running", "schedule"],
  ["marketdata", "queued", "platform"],
].map(([job, status, source], i) => ({
  id: `sample-${i}`,
  job,
  source,
  status,
  attempt: 1,
  queued_at: new Date(Date.now() - (i + 1) * 3_600_000).toISOString(),
  started_at:
    status === "queued"
      ? undefined
      : new Date(Date.now() - (i + 1) * 3_500_000).toISOString(),
  finished_at:
    status === "succeeded" || status === "failed"
      ? new Date(Date.now() - i * 3_000_000).toISOString()
      : undefined,
  exit_code: status === "failed" ? 1 : 0,
  error: status === "failed" ? "exit_status" : undefined,
  installed: status === "succeeded" ? [`${job}/2026-11-20`] : undefined,
}));

const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"];
const DAY_AFTER = ["Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const slot = (days, hour, minute = 0, fallback = false) => ({
  days,
  hour,
  minute,
  fallback,
});
// The job timetable of service/scheduler.go DefaultSlots, in Beijing time.
const SAMPLE_JOBS = {
  etf: [slot(DAY_AFTER, 8)],
  margin: [slot(WEEKDAYS, 9), slot(WEEKDAYS, 9, 50, true)],
  marketdata: [slot(WEEKDAYS, 21), slot(WEEKDAYS, 23, 30, true)],
  panorama: [slot(DAY_AFTER, 0, 50)],
  sentiment: [slot(DAY_AFTER, 0, 40)],
};

const DAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

/** Next main-slot occurrence in Asia/Shanghai (UTC+8, no DST); fallback slots are skipped like the service. */
const nextRun = (slots, now = Date.now()) => {
  const offset = 8 * 3_600_000;
  let best = null;
  for (const s of slots) {
    if (s.fallback) continue;
    for (let day = 0; day < 8; day++) {
      const local = new Date(now + offset);
      local.setUTCHours(s.hour, s.minute, 0, 0);
      local.setUTCDate(local.getUTCDate() + day);
      const at = local.getTime() - offset;
      if (at > now && s.days.includes(DAY_NAMES[local.getUTCDay()])) {
        if (best === null || at < best) best = at;
        break;
      }
    }
  }
  return best === null ? null : new Date(best).toISOString();
};

export function createMockBackend(dir) {
  const cache = new Map();
  // Manual runs started through POST, newest first; one per request_id.
  const manual = new Map();
  const dates = (module) => {
    const folder = join(dir, module);
    if (!existsSync(folder)) return [];
    return readdirSync(folder)
      .map((name) => name.replace(/\.json$/, ""))
      .filter((name) => DATE.test(name))
      .sort()
      .reverse();
  };
  const load = (module, date) => {
    const list = dates(module);
    const wanted = date || list[0];
    if (!wanted || !list.includes(wanted)) return null;
    const key = `${module}/${wanted}`;
    if (!cache.has(key)) {
      const doc = JSON.parse(
        readFileSync(join(dir, module, `${wanted}.json`), "utf8"),
      );
      const rows = Array.isArray(doc.rows) ? doc.rows : [];
      cache.set(key, {
        doc,
        rows,
        index: new Map(rows.map((row, i) => [row.code, i])),
      });
    }
    return cache.get(key);
  };
  const reply = (status, value) => {
    const body = JSON.stringify(value);
    if (body.length > MAX_RESPONSE)
      return {
        status: 422,
        body: JSON.stringify({ error: "response_too_large" }),
      };
    return { status, body };
  };
  const fail = (status, error) => reply(status, { error });

  const allRuns = () => {
    const file = join(dir, "..", "runs", "index.json");
    const indexed = existsSync(file)
      ? JSON.parse(readFileSync(file, "utf8")).runs.map((run) => ({
          source: "platform",
          exit_code: 0,
          ...run,
        }))
      : SAMPLE_RUNS;
    return [...manual.values()].reverse().concat(indexed);
  };

  /** Admin routes: like the Go service, refused unless the view is the admin one. */
  const admin = (parts, method, body, isAdmin) => {
    if (!isAdmin) return fail(403, "forbidden");
    if (method === "GET" && parts[1] === "jobs" && parts.length === 2) {
      const runs = allRuns();
      return reply(200, {
        time_zone: "Asia/Shanghai",
        jobs: Object.entries(SAMPLE_JOBS).map(([name, schedule]) => ({
          name,
          schedule,
          next_run: nextRun(schedule),
          last_run: runs.find((run) => run.job === name) ?? null,
        })),
      });
    }
    if (method === "GET" && parts[1] === "runs" && parts.length === 2)
      return reply(200, { runs: allRuns() });
    if (
      method === "GET" &&
      parts[1] === "runs" &&
      parts.length === 4 &&
      parts[3] === "log"
    ) {
      const run = allRuns().find((r) => r.id === parts[2]);
      if (!run) return fail(404, "not_found");
      return reply(200, {
        run_id: run.id,
        log: `[market-monitor] attempt ${run.attempt} of ${run.job} started\n(sample log)\n`,
        truncated: false,
      });
    }
    if (
      method === "POST" &&
      parts[1] === "jobs" &&
      parts.length === 4 &&
      parts[3] === "run"
    ) {
      let id;
      try {
        const parsed = JSON.parse(body);
        id = Object.keys(parsed).join() === "request_id" ? parsed.request_id : "";
      } catch {
        id = "";
      }
      if (!/^[0-9a-f-]{36}$/i.test(id)) return fail(400, "bad_request");
      if (!SAMPLE_JOBS[parts[2]]) return fail(404, "not_found");
      const duplicate = manual.has(id);
      if (!duplicate)
        manual.set(id, {
          id: `manual-${manual.size}`,
          job: parts[2],
          source: "manual",
          status: "queued",
          attempt: 1,
          queued_at: new Date().toISOString(),
          exit_code: 0,
        });
      return reply(202, { run: manual.get(id), duplicate });
    }
    return fail(404, "not_found");
  };

  return function handle(target, method = "GET", body = "", isAdmin = false) {
    const url = new URL(target, "http://mock.invalid");
    const parts = url.pathname.replace(/^\/v1\//, "").split("/");
    if (!url.pathname.startsWith("/v1/")) return fail(404, "not_found");
    if (parts[0] === "admin") return admin(parts, method, body, isAdmin);
    if (method !== "GET") return fail(404, "not_found");
    if (parts.length < 2 || !MODULES.includes(parts[0]))
      return fail(404, "not_found");
    const module = parts[0];
    const date = url.searchParams.get("date") ?? "";
    if (date !== "" && !DATE.test(date)) return fail(400, "bad_request");
    if (parts.length === 2 && parts[1] === "dates" && url.search === "")
      return reply(200, { module, dates: dates(module) });
    if (
      parts.length === 2 &&
      parts[1] === "summary" &&
      [...url.searchParams.keys()].every((k) => k === "date")
    ) {
      const snap = load(module, date);
      return snap
        ? reply(200, {
            module,
            as_of: snap.doc.as_of,
            summary: snap.doc.summary,
          })
        : fail(404, "no_data");
    }
    if (parts.length === 2 && parts[1] === "rows") {
      const q = parseRowQuery(url.searchParams);
      if (!q) return fail(400, "bad_request");
      const snap = load(module, date);
      if (!snap) return fail(404, "no_data");
      const { items, total } = queryRows(snap.rows, q);
      return reply(200, {
        module,
        as_of: snap.doc.as_of,
        page: q.page,
        size: q.size,
        total,
        items,
      });
    }
    if (
      parts.length === 3 &&
      parts[1] === "rows" &&
      parts[2] !== "" &&
      [...url.searchParams.keys()].every((k) => k === "date")
    ) {
      const snap = load(module, date);
      if (!snap) return fail(404, "no_data");
      const code = decodeURIComponent(parts[2]);
      const i = snap.index.get(code);
      if (i === undefined) return fail(404, "not_found");
      return reply(200, {
        module,
        as_of: snap.doc.as_of,
        row: snap.rows[i],
        detail: snap.doc.details?.[code] ?? null,
      });
    }
    return fail(400, "bad_request");
  };
}

/** Vite plugin: serves the mock under /__mock and redirects / to the host page. */
export function mockBackendPlugin(dir) {
  const handle = createMockBackend(dir);
  return {
    name: "market-monitor-dev-mock",
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        if (req.url === "/") {
          res.statusCode = 302;
          res.setHeader("Location", "/dev/host.html");
          res.end();
          return;
        }
        if (!req.url?.startsWith("/__mock/")) return next();
        // Only the stand-in host (same origin) calls the mock. The dev server's
        // CORS setting lets the sandboxed frame (Origin: null) load modules,
        // so refuse cross-site or null-origin reads of the snapshot data.
        if (
          req.headers.origin ||
          (req.headers["sec-fetch-site"] ?? "same-origin") !== "same-origin"
        ) {
          res.statusCode = 403;
          res.end();
          return;
        }
        const chunks = [];
        req.on("data", (chunk) => chunks.push(chunk));
        req.on("end", () => {
          const result = handle(
            req.url.slice("/__mock".length),
            req.method,
            Buffer.concat(chunks).toString("utf8"),
            req.headers["x-mock-surface"] === "admin",
          );
          res.statusCode = result.status;
          res.setHeader("Content-Type", "application/json");
          res.end(result.body);
        });
      });
    },
  };
}
