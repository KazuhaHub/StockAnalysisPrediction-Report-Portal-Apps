import {
  cleanup,
  fireEvent,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test, vi } from "vitest";
import { mount, ok, type Handler, type Request } from "./harness";
import { backend } from "./fixtures";
import { formatSlot } from "../src/pages/Admin";
import { createMockBackend } from "../dev/mock-backend.mjs";
import enUS from "../locales/en-US.json";
import zhCN from "../locales/zh-CN.json";
import zhTW from "../locales/zh-TW.json";

vi.mock("../src/components/EChart", () => ({
  EChart: () => <div data-testid="chart" />,
}));

const run = (over: Record<string, unknown> = {}) => ({
  id: "run-1",
  job: "margin",
  source: "schedule",
  status: "succeeded",
  attempt: 1,
  queued_at: "2026-11-17T01:00:00Z",
  started_at: "2026-11-17T01:00:05Z",
  finished_at: "2026-11-17T01:05:00Z",
  exit_code: 0,
  installed: ["margin/2026-11-16"],
  ...over,
});

const jobs = {
  time_zone: "Asia/Shanghai",
  jobs: [
    {
      name: "margin",
      schedule: [
        {
          days: ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
          hour: 9,
          minute: 0,
          fallback: false,
        },
        {
          days: ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
          hour: 9,
          minute: 50,
          fallback: true,
        },
      ],
      next_run: "2026-11-23T01:00:00Z",
      last_run: run(),
    },
    {
      name: "etf",
      schedule: [],
      last_run: run({
        id: "run-2",
        job: "etf",
        status: "failed",
        error: "exit_status",
        source: "manual",
      }),
    },
  ],
};

type Script = {
  runs?: unknown[];
  failJobs?: boolean;
  runNow?: (request: Request) => ReturnType<Handler>;
  log?: (id: string) => ReturnType<Handler>;
};

function adminBackend(script: Script = {}): Handler {
  const reader = backend();
  return (path, params, request) => {
    if (path === "/v1/admin/jobs")
      return script.failJobs
        ? { status: 409, body: { error: "unavailable" } }
        : ok(jobs);
    if (path === "/v1/admin/runs")
      return ok({ runs: script.runs ?? [run(), jobs.jobs[1].last_run] });
    const log = path.match(/^\/v1\/admin\/runs\/([^/]+)\/log$/);
    if (log)
      return script.log
        ? script.log(log[1])
        : ok({ run_id: log[1], log: "line one\nline two", truncated: false });
    if (/^\/v1\/admin\/jobs\/[^/]+\/run$/.test(path))
      return script.runNow
        ? script.runNow(request)
        : {
            status: 202,
            body: { run: run({ status: "queued" }), duplicate: false },
          };
    return reader(path, params, request);
  };
}

const admin = { surface: "admin" as const };

test("the admin page lists jobs with their schedule, next run and last run status", async () => {
  const app = await mount(adminBackend(), admin);
  expect(await screen.findByText(enUS.admin_jobs)).toBeTruthy();
  expect(app.page().page.title).toBe(enUS.admin_title);
  expect(await screen.findByText("Mon–Fri 09:00")).toBeTruthy();
  expect(screen.getByText("Mon–Fri 09:50")).toBeTruthy();
  expect(screen.getAllByText(`(${enUS.admin_fallback})`)).toHaveLength(1);
  expect(screen.getByText(enUS.admin_notScheduled)).toBeTruthy();
  expect(screen.getByText("Times are shown in Asia/Shanghai.")).toBeTruthy();
  const margin = screen
    .getByRole("list", { name: "margin" })
    .closest(".mm-admin-job") as HTMLElement;
  // Status is a word with an icon, not colour alone.
  const tag = within(margin)
    .getByText("Succeeded")
    .closest(".ant-tag") as HTMLElement;
  expect(tag.querySelector("svg")).not.toBeNull();
  const etf = screen
    .getByRole("list", { name: "etf" })
    .closest(".mm-admin-job") as HTMLElement;
  expect(within(etf).getByText("Failed")).toBeTruthy();
  expect(within(etf).getByText("exit_status")).toBeTruthy();
  // The reader's dashboards are not requested on the admin page.
  expect(app.calls.every((c) => c.startsWith("/v1/admin/"))).toBe(true);
});

test("the run history shows source, status, attempt, times and error code", async () => {
  await mount(adminBackend(), admin);
  expect(await screen.findByText(enUS.admin_history)).toBeTruthy();
  expect(await screen.findByText(enUS.run_source_schedule)).toBeTruthy();
  expect(screen.getByText(enUS.run_source_manual)).toBeTruthy();
  const history = document.querySelector(".mm-admin-runs") as HTMLElement;
  expect(within(history).getAllByText(/Attempt 1/)).toHaveLength(2);
  expect(within(history).getByText("exit_status")).toBeTruthy();
  expect(within(history).getAllByText(/Queued/).length).toBe(2);
});

test("expanding a run loads its log once and reports a truncated tail", async () => {
  const log = vi.fn((id: string) =>
    ok({ run_id: id, log: "tail of the log", truncated: true }),
  );
  const app = await mount(adminBackend({ log }), admin);
  const history = await waitFor(() => {
    const el = document.querySelector(".mm-admin-runs") as HTMLElement;
    expect(el).not.toBeNull();
    return el;
  });
  expect(log).not.toHaveBeenCalled();
  const headers = within(history).getAllByRole("button");
  fireEvent.click(headers[0]);
  expect(await screen.findByText("tail of the log")).toBeTruthy();
  expect(screen.getByText(enUS.admin_logTruncated)).toBeTruthy();
  expect(log).toHaveBeenCalledWith("run-1");
  expect(app.calls.filter((c) => c.endsWith("/log"))).toEqual([
    "/v1/admin/runs/run-1/log",
  ]);
});

test("a log that cannot be loaded offers a retry", async () => {
  let fail = true;
  await mount(
    adminBackend({
      log: (id) =>
        fail
          ? { status: 409, body: { error: "unavailable" } }
          : ok({ run_id: id, log: "recovered", truncated: false }),
    }),
    admin,
  );
  const history = await waitFor(() => {
    const el = document.querySelector(".mm-admin-runs") as HTMLElement;
    expect(el).not.toBeNull();
    return el;
  });
  fireEvent.click(within(history).getAllByRole("button")[0]);
  expect(await screen.findByText(enUS.admin_logFailed)).toBeTruthy();
  fail = false;
  fireEvent.click(screen.getByRole("button", { name: enUS.retry }));
  expect(await screen.findByText("recovered")).toBeTruthy();
});

test("Run now asks first, focuses Cancel, and posts one stable request id across a retry", async () => {
  let attempts = 0;
  const app = await mount(
    adminBackend({
      runNow: () =>
        ++attempts === 1
          ? { status: 409, body: { error: "queue_full" } }
          : {
              status: 202,
              body: { run: run({ status: "queued" }), duplicate: false },
            },
    }),
    admin,
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "Run now: margin" }),
  );
  const dialog = await screen.findByRole("dialog");
  expect(within(dialog).getByText("Run margin now?")).toBeTruthy();
  expect(app.requests.filter((r) => r.method === "POST")).toHaveLength(0);
  const cancel = within(dialog).getByRole("button", {
    name: enUS.admin_cancel,
  });
  await waitFor(() => expect(document.activeElement).toBe(cancel));
  fireEvent.click(
    within(dialog).getByRole("button", { name: /Run margin now/, busy: false }),
  );
  expect(await within(dialog).findByText(enUS.admin_runQueueFull)).toBeTruthy();
  fireEvent.click(
    within(dialog).getByRole("button", { name: /Run margin now/, busy: false }),
  );
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  const posts = app.requests.filter((r) => r.method === "POST");
  expect(posts).toHaveLength(2);
  expect(posts[0].path).toBe("/v1/admin/jobs/margin/run");
  const first = JSON.parse(posts[0].body);
  expect(Object.keys(first)).toEqual(["request_id"]);
  expect(first.request_id).toMatch(/^[0-9a-f-]{36}$/);
  expect(JSON.parse(posts[1].body)).toEqual(first);
  expect(await screen.findByText("Run of margin queued.")).toBeTruthy();
  // The lists refresh after the run was queued.
  await waitFor(() =>
    expect(
      app.calls.filter((c) => c === "/v1/admin/runs").length,
    ).toBeGreaterThan(1),
  );
});

test("Run now asks next to its button, not in a centred modal", async () => {
  // The admin page is embedded in an iframe as tall as the page: a modal
  // centred in that viewport can sit far below what the Portal page shows.
  await mount(adminBackend(), admin);
  fireEvent.click(
    await screen.findByRole("button", { name: "Run now: margin" }),
  );
  const dialog = await screen.findByRole("dialog");
  expect(dialog.closest(".ant-popover")).not.toBeNull();
  expect(document.querySelector(".ant-modal")).toBeNull();
  // Escape closes even with focus outside the popover, and focus returns
  // to the button that opened it.
  fireEvent.keyDown(document.body, { key: "Escape" });
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(document.activeElement).toBe(
    screen.getByRole("button", { name: "Run now: margin" }),
  );
});

test("cancelling Run now sends nothing, and the next dialog gets a new request id", async () => {
  const app = await mount(adminBackend(), admin);
  const open = async () => {
    fireEvent.click(
      await screen.findByRole("button", { name: "Run now: margin" }),
    );
    return screen.findByRole("dialog");
  };
  let dialog = await open();
  fireEvent.click(
    within(dialog).getByRole("button", { name: enUS.admin_cancel }),
  );
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(app.requests.filter((r) => r.method === "POST")).toHaveLength(0);
  dialog = await open();
  fireEvent.click(
    within(dialog).getByRole("button", { name: /Run margin now/, busy: false }),
  );
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  fireEvent.click(
    await screen.findByRole("button", { name: "Run now: margin" }),
  );
  const second = await screen.findByRole("dialog");
  fireEvent.click(
    within(second).getByRole("button", { name: /Run margin now/, busy: false }),
  );
  await waitFor(() =>
    expect(app.requests.filter((r) => r.method === "POST")).toHaveLength(2),
  );
  const ids = app.requests
    .filter((r) => r.method === "POST")
    .map((r) => JSON.parse(r.body).request_id);
  expect(ids[0]).not.toBe(ids[1]);
});

test("loading failures show an error with a retry, and an empty history says so", async () => {
  let fail = true;
  await mount(
    (path, params, request) =>
      fail && path === "/v1/admin/jobs"
        ? { status: 409, body: { error: "unavailable" } }
        : adminBackend({ runs: [] })(path, params, request),
    admin,
  );
  expect(await screen.findByText(enUS.admin_loadFailed)).toBeTruthy();
  expect(await screen.findByText(enUS.admin_noRuns)).toBeTruthy();
  fail = false;
  fireEvent.click(screen.getByRole("button", { name: enUS.retry }));
  expect(await screen.findByText("Mon–Fri 09:00")).toBeTruthy();
});

test("the admin copy exists in every language", async () => {
  const adminKeys = Object.keys(enUS).filter((k) => k.startsWith("admin_"));
  expect(adminKeys.length).toBeGreaterThan(0);
  for (const [name, copy] of [
    ["zh-CN", zhCN],
    ["zh-TW", zhTW],
  ] as const) {
    for (const key of adminKeys) {
      const value = (copy as Record<string, string>)[key];
      expect(value, `${name} ${key}`).toBeTruthy();
    }
  }
  for (const [locale, copy] of [
    ["zh-CN", zhCN],
    ["zh-TW", zhTW],
  ] as const) {
    await mount(adminBackend(), { ...admin, locale });
    expect(await screen.findByText(copy.admin_jobs)).toBeTruthy();
    expect(screen.getAllByText(copy.admin_runNow).length).toBeGreaterThan(0);
    cleanup();
  }
});

test("a job that is already active says so, with no way to retry", async () => {
  const app = await mount(
    adminBackend({
      runNow: () => ({ status: 409, body: { error: "already_active" } }),
    }),
    admin,
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "Run now: margin" }),
  );
  const dialog = await screen.findByRole("dialog");
  fireEvent.click(
    within(dialog).getByRole("button", { name: /Run margin now/, busy: false }),
  );
  expect(
    await within(dialog).findByText(enUS.admin_runAlreadyActive),
  ).toBeTruthy();
  expect(within(dialog).queryByText(enUS.admin_runFailed)).toBeNull();
  const confirm = within(dialog).queryByRole("button", {
    name: /Run margin now/,
  });
  expect(confirm === null || (confirm as HTMLButtonElement).disabled).toBe(
    true,
  );
  expect(app.requests.filter((r) => r.method === "POST")).toHaveLength(1);
});

test("a request id conflict does not offer to try again", async () => {
  await mount(
    adminBackend({
      runNow: () => ({ status: 409, body: { error: "conflict" } }),
    }),
    admin,
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "Run now: margin" }),
  );
  const dialog = await screen.findByRole("dialog");
  fireEvent.click(
    within(dialog).getByRole("button", { name: /Run margin now/, busy: false }),
  );
  expect(await within(dialog).findByText(enUS.admin_runConflict)).toBeTruthy();
  expect(within(dialog).queryByText(enUS.admin_runFailed)).toBeNull();
  const confirm = within(dialog).queryByRole("button", {
    name: /Run margin now/,
  });
  expect(confirm === null || (confirm as HTMLButtonElement).disabled).toBe(
    true,
  );
});

test("the log of a queued or running run is fetched again when the page refreshes", async () => {
  const log = vi.fn((id: string) =>
    ok({ run_id: id, log: `log ${log.mock.calls.length}`, truncated: false }),
  );
  const app = await mount(
    adminBackend({
      runs: [
        run({ id: "run-live", status: "running" }),
        run({ id: "run-done" }),
      ],
      log,
    }),
    admin,
  );
  const history = await waitFor(() => {
    const el = document.querySelector(".mm-admin-runs") as HTMLElement;
    expect(el).not.toBeNull();
    return el;
  });
  const headers = within(history).getAllByRole("button");
  fireEvent.click(headers[0]);
  fireEvent.click(headers[1]);
  await waitFor(() => expect(log).toHaveBeenCalledTimes(2));
  await app.invoke("refresh");
  await waitFor(() => expect(log).toHaveBeenCalledTimes(3));
  expect(log.mock.calls.map((c) => c[0])).toEqual([
    "run-live",
    "run-done",
    "run-live",
  ]);
});

test("slots read as day ranges or lists in the viewer's language", () => {
  const weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"];
  expect(
    formatSlot(
      { days: weekdays, hour: 21, minute: 0, fallback: false },
      "en-US",
    ),
  ).toBe("Mon–Fri 21:00");
  expect(
    formatSlot(
      { days: ["Monday", "Wednesday"], hour: 9, minute: 5, fallback: false },
      "en-US",
    ),
  ).toBe("Mon, Wed 09:05");
  expect(
    formatSlot(
      { days: weekdays, hour: 21, minute: 0, fallback: false },
      "zh-CN",
    ),
  ).toBe("周一–周五 21:00");
});

test("a reader view never asks for runs or admin routes", async () => {
  const app = await mount(backend());
  expect(
    await screen.findByText("Systemic-risk readings · 2026-11-16"),
  ).toBeTruthy();
  expect(document.querySelector(".ant-table")).toBeNull();
  expect(
    app.calls.some((c) => c.includes("/runs") || c.includes("/admin")),
  ).toBe(false);
});

test("with reduced motion requested the history still opens and loads the log", async () => {
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      matches: query.includes("prefers-reduced-motion"),
      addListener() {},
      removeListener() {},
      addEventListener() {},
      removeEventListener() {},
    })),
  );
  await mount(adminBackend(), admin);
  const history = await waitFor(() => {
    const el = document.querySelector(".mm-admin-runs") as HTMLElement;
    expect(el).not.toBeNull();
    return el;
  });
  fireEvent.click(within(history).getAllByRole("button")[0]);
  expect(await screen.findByText("line one", { exact: false })).toBeTruthy();
  // Motion is off: antd adds no motion classes to the opening panel.
  expect(document.querySelector("[class*='ant-motion']")).toBeNull();
});

test("without reduced motion the history panel opens through antd motion", async () => {
  await mount(adminBackend(), admin);
  const history = await waitFor(() => {
    const el = document.querySelector(".mm-admin-runs") as HTMLElement;
    expect(el).not.toBeNull();
    return el;
  });
  fireEvent.click(within(history).getAllByRole("button")[0]);
  await screen.findByText("line one", { exact: false });
  expect(document.querySelector("[class*='ant-motion']")).not.toBeNull();
});

test("the dev mock serves admin routes only to the admin view and runs once per request id", () => {
  const handle = createMockBackend("/nonexistent");
  expect(handle("/v1/admin/jobs").status).toBe(403);
  expect(handle("/v1/admin/jobs", "GET", "", true).status).toBe(200);
  const id = "30000000-0000-4000-8000-000000000001";
  const body = JSON.stringify({ request_id: id });
  const first = handle("/v1/admin/jobs/margin/run", "POST", body, true);
  const again = handle("/v1/admin/jobs/margin/run", "POST", body, true);
  expect(first.status).toBe(202);
  expect(JSON.parse(again.body).duplicate).toBe(true);
  expect(JSON.parse(again.body).run.id).toBe(JSON.parse(first.body).run.id);
  expect(handle("/v1/admin/jobs/margin/run", "POST", "{}", true).status).toBe(
    400,
  );
  expect(handle("/v1/admin/jobs/nope/run", "POST", body, true).status).toBe(
    404,
  );
  expect(handle("/v1/runs", "GET", "", true).status).toBe(404);
});

function jobsWith(name: string, last: unknown, typical?: number) {
  return {
    time_zone: "Asia/Shanghai",
    jobs: [
      {
        name,
        schedule: [],
        last_run: last,
        ...(typical ? { typical_seconds: typical } : {}),
      },
    ],
  };
}

function liveBackend(
  jobsBody: () => unknown,
  runs: () => unknown[],
): { handler: Handler; count: () => number } {
  let n = 0;
  const base = adminBackend();
  return {
    count: () => n,
    handler: (path, params, request) => {
      if (path === "/v1/admin/jobs") {
        n++;
        return ok(jobsBody());
      }
      if (path === "/v1/admin/runs") return ok({ runs: runs() });
      return base(path, params, request);
    },
  };
}

const NOW = Date.parse("2026-11-27T02:29:05Z");

test("a counting run shows a progress bar, the count and the time left", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true, now: NOW });
  try {
    const live = run({
      id: "run-md",
      job: "marketdata",
      status: "running",
      started_at: "2026-11-27T01:49:05Z", // 40 minutes before NOW
      finished_at: undefined,
      installed: undefined,
      progress: { done: 1200, total: 4800 },
    });
    const { handler } = liveBackend(
      () => jobsWith("marketdata", live),
      () => [live],
    );
    await mount(handler, admin);
    const bar = await screen.findByRole("progressbar", {
      name: "marketdata progress",
    });
    expect(bar.getAttribute("aria-valuenow")).toBe("25");
    const row = bar.closest(".mm-admin-job") as HTMLElement;
    expect(within(row).getByText("1,200 of 4,800 done")).toBeTruthy();
    expect(within(row).getByText("Running for 40 min")).toBeTruthy();
    // 40 minutes for a quarter: two hours to go.
    expect(within(row).getByText("About 2 h 0 min left")).toBeTruthy();
  } finally {
    vi.useRealTimers();
  }
});

test("a run without counts is measured against its usual duration", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true, now: NOW });
  try {
    const live = run({
      id: "run-s",
      job: "sentiment",
      status: "running",
      started_at: "2026-11-27T02:26:05Z", // 3 minutes
      finished_at: undefined,
    });
    const { handler } = liveBackend(
      () => jobsWith("sentiment", live, 12 * 60),
      () => [live],
    );
    await mount(handler, admin);
    const bar = await screen.findByRole("progressbar", {
      name: "sentiment progress",
    });
    expect(bar.getAttribute("aria-valuenow")).toBe("25");
    const row = bar.closest(".mm-admin-job") as HTMLElement;
    expect(within(row).getByText("Usually takes 12 min")).toBeTruthy();
    expect(within(row).getByText("About 9 min left")).toBeTruthy();
  } finally {
    vi.useRealTimers();
  }
});

test("a run past its usual duration says so instead of a negative estimate", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true, now: NOW });
  try {
    const live = run({
      id: "run-s",
      job: "sentiment",
      status: "running",
      started_at: "2026-11-27T02:09:05Z", // 20 minutes
      finished_at: undefined,
    });
    const { handler } = liveBackend(
      () => jobsWith("sentiment", live, 12 * 60),
      () => [live],
    );
    await mount(handler, admin);
    expect(await screen.findByText(enUS.admin_overTypical)).toBeTruthy();
    expect(screen.queryByText(/left$/)).toBeNull();
  } finally {
    vi.useRealTimers();
  }
});

test("a run waiting for its data source counts down to the retry", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true, now: NOW });
  try {
    const live = run({
      id: "run-md",
      job: "marketdata",
      status: "running",
      started_at: "2026-11-27T01:49:05Z",
      finished_at: undefined,
      progress: {
        done: 800,
        total: 4800,
        waiting_until: "2026-11-27T02:30:05Z",
      },
    });
    const { handler } = liveBackend(
      () => jobsWith("marketdata", live),
      () => [live],
    );
    await mount(handler, admin);
    expect(
      await screen.findByText("Data source unavailable, retrying in 1 min"),
    ).toBeTruthy();
    await vi.advanceTimersByTimeAsync(31_000);
    expect(
      await screen.findByText("Data source unavailable, retrying in 29 s"),
    ).toBeTruthy();
  } finally {
    vi.useRealTimers();
  }
});

test("a failed run shows its reason in words and the log line behind it", async () => {
  const failed = run({
    id: "run-oom",
    job: "sentiment",
    status: "failed",
    exit_code: 1,
    error: "exit_status",
    installed: undefined,
    reason: "out_of_memory",
    reason_detail: "面板重建失败：sentiment_build.py 被信号 9 终止",
  });
  const { handler } = liveBackend(
    () => jobsWith("sentiment", failed),
    () => [failed],
  );
  await mount(handler, admin);
  const row = (await screen.findByRole("list", { name: "sentiment" })).closest(
    ".mm-admin-job",
  ) as HTMLElement;
  expect(within(row).getByText(enUS.reason_out_of_memory)).toBeTruthy();
  expect(
    within(row).getByText("面板重建失败：sentiment_build.py 被信号 9 终止"),
  ).toBeTruthy();
  expect(within(row).queryByText("exit_status")).toBeNull();
  const history = document.querySelector(".mm-admin-runs") as HTMLElement;
  expect(within(history).getByText(enUS.reason_out_of_memory)).toBeTruthy();
});

test("the page refreshes itself while a run is active and stops once none is", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true, now: NOW });
  try {
    let status = "running";
    const current = () =>
      run({
        id: "run-s",
        job: "sentiment",
        status,
        started_at: "2026-11-27T02:26:05Z",
        finished_at: status === "running" ? undefined : "2026-11-27T02:30:00Z",
      });
    const live = liveBackend(
      () => jobsWith("sentiment", current(), 600),
      () => [current()],
    );
    await mount(live.handler, admin);
    await screen.findByRole("progressbar", { name: "sentiment progress" });
    const first = live.count();
    status = "succeeded";
    await vi.advanceTimersByTimeAsync(15_000);
    await waitFor(() => expect(live.count()).toBe(first + 1));
    await waitFor(() => expect(screen.queryByRole("progressbar")).toBeNull());
    await vi.advanceTimersByTimeAsync(45_000);
    expect(live.count()).toBe(first + 1);
  } finally {
    vi.useRealTimers();
  }
});

test("every failure reason has words in every language", () => {
  const reasons = [
    "timeout",
    "interrupted",
    "out_of_memory",
    "store_incomplete",
    "quality_gate",
    "source_unavailable",
    "output_missing",
    "not_refreshed",
    "environment",
    "output_invalid",
    "service_error",
    "unknown",
  ];
  for (const copy of [enUS, zhCN, zhTW] as Record<string, string>[])
    for (const r of reasons) expect(copy[`reason_${r}`], r).toBeTruthy();
});

test("the running status icon spins, except with reduced motion", async () => {
  const live = run({ status: "running", finished_at: undefined });
  const { handler } = liveBackend(
    () => jobsWith("margin", live),
    () => [live],
  );
  await mount(handler, admin);
  const tags = await screen.findAllByText("Running");
  for (const tag of tags)
    expect(
      (tag.closest(".ant-tag") as HTMLElement).querySelector("svg.mm-spin"),
    ).not.toBeNull();
  const css = readFileSync(
    resolve(import.meta.dirname, "../src/style.css"),
    "utf8",
  );
  expect(css).toMatch(/\.mm-spin\s*\{[^}]*animation:[^}]*mm-spin/);
  expect(css).toMatch(
    /@media \(prefers-reduced-motion: reduce\)\s*\{[^@]*\.mm-spin\s*\{\s*animation:\s*none/,
  );
});

test("one failed refresh keeps the page and its live refresh going", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true, now: NOW });
  try {
    let n = 0;
    const live = run({
      id: "run-s",
      job: "sentiment",
      status: "running",
      started_at: "2026-11-27T02:26:05Z",
      finished_at: undefined,
    });
    const base = adminBackend();
    const handler: Handler = (path, params, request) => {
      if (path === "/v1/admin/jobs")
        return ++n === 2
          ? { status: 409, body: { error: "unavailable" } }
          : ok(jobsWith("sentiment", live, 600));
      if (path === "/v1/admin/runs") return ok({ runs: [live] });
      return base(path, params, request);
    };
    await mount(handler, admin);
    await screen.findByRole("progressbar", { name: "sentiment progress" });
    await vi.advanceTimersByTimeAsync(15_000);
    await waitFor(() => expect(n).toBe(2));
    expect(screen.queryByText(enUS.admin_loadFailed)).toBeNull();
    expect(
      screen.getByRole("progressbar", { name: "sentiment progress" }),
    ).toBeTruthy();
    await vi.advanceTimersByTimeAsync(15_000);
    await waitFor(() => expect(n).toBe(3));
  } finally {
    vi.useRealTimers();
  }
});
