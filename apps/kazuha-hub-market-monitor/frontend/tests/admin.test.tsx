import {
  cleanup,
  fireEvent,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
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
