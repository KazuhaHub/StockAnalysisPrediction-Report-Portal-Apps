import {
  act,
  cleanup,
  fireEvent,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { BridgeBackendError } from "@portal-app/sdk/bridge-v2";
import { createClient } from "../src/client";
import { locales } from "../src/ui";
import { close, mount, Reply } from "./host";

afterEach(() => {
  cleanup();
  close.splice(0).forEach((dispose) => dispose());
  vi.unstubAllGlobals();
});

async function enabled(app: ReturnType<typeof mount>, id: string) {
  await waitFor(() => {
    expect(app.page()?.ready).toBe(true);
    const action = app.page()?.page.actions.find((item) => item.id === id);
    expect(action).toBeTruthy();
    expect(action!.disabled).toBe(false);
  });
}

async function openManagement(app: ReturnType<typeof mount>) {
  await enabled(app, "manage");
  app.invoke("manage");
  await screen.findByRole("tab", { name: "Components", exact: true });
}

test("the host owns the title and language and the app draws no second header", async () => {
  const app = mount();
  await waitFor(() => expect(app.page()?.page.title).toBe(locales["en-US"].title));
  expect(app.page()?.page.description).toBe(locales["en-US"].subtitle);
  await screen.findByText(/No visible components/);
  expect(screen.queryByRole("heading", { level: 3 })).toBeNull();
  expect(screen.queryByRole("combobox", { name: /language/i })).toBeNull();
  app.setLocale("zh-TW");
  await waitFor(() => expect(app.page()?.page.title).toBe(locales["zh-TW"].title));
  expect(document.documentElement.lang).toBe("zh-TW");
});

test("the host locale changes without losing the active draft", async () => {
  const app = mount();
  const user = userEvent.setup();
  await openManagement(app);
  await user.click(await screen.findByRole("button", { name: "New component", exact: true }));
  await user.type(screen.getByLabelText("Internal label", { exact: true }), "Keep locale draft");
  for (const locale of ["zh-CN", "zh-TW", "en-US"] as const) {
    app.setLocale(locale);
    await waitFor(() => expect(app.page()?.page.title).toBe(locales[locale].title));
    expect(document.documentElement.lang).toBe(locale);
    expect(screen.getByDisplayValue("Keep locale draft")).toBeTruthy();
    expect(screen.getByRole("dialog")).toBeTruthy();
  }
});

test("an unsaved component draft raises the host's unsaved-change guard", async () => {
  const app = mount();
  const user = userEvent.setup();
  await openManagement(app);
  await user.click(await screen.findByRole("button", { name: "New component", exact: true }));
  expect(app.draftDirty()).toBe(false);
  await user.type(screen.getByLabelText("Internal label", { exact: true }), "Dirty");
  await waitFor(() => expect(app.draftDirty()).toBe(true));
});

test("the initial overview stays compact and ordinary viewers have no management entry", async () => {
  const app = mount({ admin: false });
  await screen.findByText(/No visible components/);
  expect(app.actionIds()).toEqual(["refresh"]);
  expect(screen.queryByText("Queue review fingerprint")).toBeNull();
});

test("a viewer who opens the management route directly sees no configuration", async () => {
  const app = mount({ admin: false });
  await screen.findByText(/No visible components/);
  await waitFor(() => expect(app.page()?.ready).toBe(true));
  // Navigation is signed by the host, but the app still refuses to render it.
  expect(app.calls.some((call) => call.path.startsWith("/v1/manage/"))).toBe(false);
});

test("administrators move between overview, incidents and management through host routes", async () => {
  const app = mount();
  await screen.findByText(/No visible components/);
  await enabled(app, "manage");
  expect(app.actionIds()).toEqual(["refresh", "manage"]);
  await userEvent.setup().click(screen.getByRole("tab", { name: "Incidents", exact: true }));
  await waitFor(() => expect(app.calls.some((call) => call.path.startsWith("/v1/incidents"))).toBe(true));
  // The host drops a navigation that races its own presentation update.
  await waitFor(() => {
    if (!screen.queryByRole("tab", { name: "Credentials", exact: true }))
      act(() => {
        app.page()?.invoke("manage");
      });
    expect(screen.getByRole("tab", { name: "Credentials", exact: true })).toBeTruthy();
  });
  expect(app.actionIds()).toEqual(["refresh", "overview"]);
  await waitFor(() => {
    if (screen.queryByRole("tab", { name: "Credentials", exact: true }))
      act(() => {
        app.page()?.invoke("overview");
      });
    expect(screen.queryByRole("tab", { name: "Credentials", exact: true })).toBeNull();
  });
  await screen.findByText(/No visible components|No incidents/);
});

test("refresh reads the current components again", async () => {
  const app = mount();
  await screen.findByText(/No visible components/);
  await enabled(app, "refresh");
  const before = app.calls.filter((call) => call.path.startsWith("/v1/components?")).length;
  app.invoke("refresh");
  await waitFor(() =>
    expect(app.calls.filter((call) => call.path.startsWith("/v1/components?")).length).toBe(before + 1),
  );
});

test("an unavailable backend is never shown as an empty healthy status", async () => {
  const app = mount({ backend: false });
  await screen.findByText(locales["en-US"].backendUnavailable);
  expect(screen.queryByText(/No visible components/)).toBeNull();
  expect(app.backend).not.toHaveBeenCalled();
});

test("an incompatible backend shows no status data", async () => {
  mount({
    handler: (_method, path) =>
      path === "/v1/me" ? { admin: true, api_version: 2, capabilities: [] } : undefined,
  });
  await screen.findByText(locales["en-US"].backendUpgradeRequired);
  expect(screen.queryByText(/No visible components/)).toBeNull();
});

test("monitors without a network path explain it instead of showing a failure", async () => {
  mount({
    handler: (_method, path) =>
      path.startsWith("/v1/components?")
        ? {
            total: 1,
            items: [
              {
                id: "c1",
                label: "Reports API",
                revision: 1,
                state: "unknown",
                enabled: true,
                public_label: "",
                public_enabled: false,
                grants: [],
                monitors: [
                  {
                    id: "m1",
                    label: "Health",
                    kind: "http",
                    enabled: true,
                    interval_seconds: 60,
                    timeout_seconds: 5,
                    config: {},
                    state: "unknown",
                    outcome: "unknown",
                    reason_code: "egress_unavailable",
                    observed_at: "2026-11-17T10:00:00Z",
                  },
                ],
              },
            ],
          }
        : undefined,
  });
  await screen.findByText("Reports API");
  expect(await screen.findByText(locales["en-US"].egressHint)).toBeTruthy();
  expect(screen.queryByText(locales["en-US"].operational)).toBeNull();
});

test("component setup reveals one step at a time and keeps advanced fields folded", async () => {
  const user = userEvent.setup();
  const app = mount();
  await openManagement(app);
  await user.click(await screen.findByRole("button", { name: "New component", exact: true }));
  const drawer = await screen.findByRole("dialog");
  await user.type(within(drawer).getByLabelText("Internal label", { exact: true }), "A service");
  expect(within(drawer).queryByLabelText("Allowed private CIDRs (one per line)")).toBeNull();
  await user.click(within(drawer).getByRole("button", { name: "Next", exact: true }));
  expect(within(drawer).getByLabelText("Target URL")).toBeTruthy();
  expect(within(drawer).queryByLabelText("Interval (seconds)")).toBeNull();
  expect(within(drawer).queryByLabelText("Who can see amounts")).toBeNull();
});

test("without a platform principal directory the visibility step offers no lookup", async () => {
  const user = userEvent.setup();
  const app = mount();
  await openManagement(app);
  await user.click(await screen.findByRole("button", { name: "New component", exact: true }));
  const d = within(await screen.findByRole("dialog"));
  await user.type(d.getByLabelText("Internal label", { exact: true }), "Fixture");
  await user.click(d.getByRole("button", { name: "Next", exact: true }));
  await user.type(d.getByLabelText("Target URL", { exact: true }), "https://fixture.invalid/health");
  await user.click(d.getByRole("button", { name: "Next", exact: true }));
  expect(d.getByText(locales["en-US"].directoryUnavailable)).toBeTruthy();
  expect(d.queryByRole("button", { name: /Load users/ })).toBeNull();
  expect((d.getByRole("button", { name: "Save", exact: true }) as HTMLButtonElement).disabled).toBe(false);
});

test("the grant hint no longer tells administrators to pick Portal users or OUs", () => {
  expect(locales["en-US"].grantHint).not.toMatch(/select/i);
  expect(locales["zh-CN"].grantHint).not.toContain("选择");
  expect(locales["zh-TW"].grantHint).not.toContain("選擇");
});

test("public page options and the heartbeat kind are not offered for creation in this build", async () => {
  const user = userEvent.setup();
  const app = mount();
  await openManagement(app);
  await user.click(await screen.findByRole("button", { name: "New component", exact: true }));
  const d = within(await screen.findByRole("dialog"));
  await user.type(d.getByLabelText("Internal label", { exact: true }), "Fixture");
  await user.click(d.getByRole("button", { name: "Next", exact: true }));
  await user.click(d.getByLabelText("Check type", { exact: true }));
  const options = (await screen.findAllByRole("option")).map((option) => option.textContent);
  expect(options).toContain(locales["en-US"].dify);
  expect(options).not.toContain(locales["en-US"].heartbeat);
  await user.click(await screen.findByRole("option", { name: locales["en-US"].http }));
  await user.type(d.getByLabelText("Target URL", { exact: true }), "https://fixture.invalid/health");
  await user.click(d.getByRole("button", { name: "Next", exact: true }));
  expect(d.queryByText(locales["en-US"].publicOptions)).toBeNull();
  expect(d.queryByText(locales["en-US"].publicComponent)).toBeNull();
});

test("settings and credential creation offer no public page switch or heartbeat kind", async () => {
  const user = userEvent.setup();
  const app = mount();
  await openManagement(app);
  await user.click(screen.getByRole("tab", { name: "Credentials", exact: true }));
  await user.click(screen.getByRole("button", { name: "New credential", exact: true }));
  const dialog = within(screen.getByRole("dialog"));
  await user.click(dialog.getByLabelText("Check type", { exact: true }));
  const options = (await screen.findAllByRole("option")).map((option) => option.textContent);
  expect(options).toContain(locales["en-US"].deepseek);
  expect(options).not.toContain(locales["en-US"].heartbeat);
});

test("an existing heartbeat monitor stays visible, read-only, with an explanation", async () => {
  const user = userEvent.setup();
  const writes: unknown[] = [];
  const app = mount({
    handler: (method, path, body) => {
      if (method === "PUT") writes.push(body);
      return path === "/v1/manage/components"
        ? {
            total: 1,
            items: [
              {
                id: "c1",
                label: "Nightly backup",
                revision: 1,
                enabled: true,
                public_label: "",
                public_enabled: false,
                grants: [],
                monitors: [
                  {
                    id: "m1",
                    label: "Backup beat",
                    kind: "heartbeat",
                    enabled: true,
                    interval_seconds: 3600,
                    timeout_seconds: 5,
                    revision: 1,
                    config: { version: 1 },
                  },
                ],
              },
            ],
          }
        : undefined;
    },
  });
  await openManagement(app);
  await user.click(await screen.findByRole("button", { name: "Edit", exact: true }));
  const d = within(await screen.findByRole("dialog"));
  await user.click(d.getByRole("button", { name: "Next", exact: true }));
  expect(d.getByText(locales["en-US"].heartbeatUnavailable)).toBeTruthy();
  expect(d.getByText("Backup beat")).toBeTruthy();
  expect(d.queryByLabelText("Target URL")).toBeNull();
  expect(d.queryByLabelText("Check type", { exact: true })).toBeNull();
  expect(d.queryByRole("button", { name: "Check now" })).toBeNull();
});

test("failed saves retain the wizard draft and repeated activation cannot duplicate writes", async () => {
  const user = userEvent.setup();
  let writes = 0;
  let rejectWrite: (reply: Reply) => void = () => {};
  const app = mount({
    handler: (method) => {
      if (method !== "PUT") return undefined;
      writes++;
      return new Promise((resolve) => {
        rejectWrite = resolve;
      });
    },
  });
  await openManagement(app);
  await user.click(await screen.findByRole("button", { name: "New component", exact: true }));
  const d = within(await screen.findByRole("dialog"));
  await user.type(d.getByLabelText("Internal label", { exact: true }), "Keep my draft");
  await user.click(d.getByRole("button", { name: "Next", exact: true }));
  await user.type(d.getByLabelText("Target URL"), "https://example.org/health");
  await user.click(d.getByRole("button", { name: "Next", exact: true }));
  const save = d.getByRole("button", { name: "Save", exact: true });
  fireEvent.click(save);
  fireEvent.click(save);
  await waitFor(() => expect(writes).toBe(1));
  rejectWrite(new Reply(409));
  await d.findByText(locales["en-US"].configurationConflict);
  await user.click(d.getByRole("button", { name: "Previous", exact: true }));
  expect((d.getByLabelText("Target URL") as HTMLInputElement).value).toBe("https://example.org/health");
});

test("resuming probes does not resume notification publication implicitly", async () => {
  const user = userEvent.setup();
  const app = mount();
  await openManagement(app);
  await user.click(await screen.findByRole("tab", { name: "Operations", exact: true }));
  await user.click((await screen.findAllByRole("button", { name: "Review and resume", exact: true }))[0]);
  const d = within(await screen.findByRole("dialog"));
  await user.click(d.getByRole("checkbox", { name: "Resume probes", exact: true }));
  await user.click(
    d.getByRole("checkbox", {
      name: "I reviewed the current queue and potential duplicate publication",
      exact: true,
    }),
  );
  await user.click(d.getByRole("button", { name: "Resume selected work", exact: true }));
  await waitFor(() =>
    expect(app.calls).toContainEqual({
      method: "POST",
      path: "/v1/manage/resume",
      body: { queue_fingerprint: "empty", probes: true, outbox: false },
    }),
  );
});

test("credential save errors stay inside the dialog and retain the secret draft", async () => {
  const user = userEvent.setup();
  const app = mount({ handler: (method) => (method === "PUT" ? new Reply(409) : undefined) });
  await openManagement(app);
  await user.click(screen.getByRole("tab", { name: "Credentials", exact: true }));
  await user.click(screen.getByRole("button", { name: "New credential", exact: true }));
  const dialog = screen.getByRole("dialog");
  await user.type(within(dialog).getByLabelText("Internal label", { exact: true }), "Fixture account");
  await user.type(
    within(dialog).getByLabelText("API key / heartbeat signing secret", { exact: true }),
    "fixture-only-value",
  );
  await user.click(within(dialog).getByRole("button", { name: "Save", exact: true }));
  expect(await within(dialog).findByRole("alert")).toBeTruthy();
  expect(
    (within(dialog).getByLabelText("API key / heartbeat signing secret", { exact: true }) as HTMLInputElement).value,
  ).toBe("fixture-only-value");
});

test("backend replies and transport failures map to safe error keys without retrying", async () => {
  const send = (reply: () => Promise<{ status: number; body: string }>) => ({
    client: createClient(vi.fn(reply)),
  });
  const failure = async (promise: Promise<unknown>) =>
    promise.then(
      () => null,
      (error: { key: string; status?: number }) => error,
    );
  expect(
    await send(async () => ({ status: 200, body: '{"ok":true}' })).client.request("GET", "/v1/me"),
  ).toEqual({ ok: true });
  expect(
    (await failure(send(async () => ({ status: 403, body: "{}" })).client.request("GET", "/v1/me")))?.key,
  ).toBe("accessDenied");
  expect(
    (await failure(send(async () => ({ status: 409, body: "{}" })).client.request("PUT", "/v1/manage/components", {})))?.key,
  ).toBe("configurationConflict");
  expect(
    (await failure(send(async () => ({ status: 429, body: "{}" })).client.request("GET", "/v1/me")))?.key,
  ).toBe("requestBusy");
  expect(
    (await failure(send(async () => ({ status: 200, body: "not json" })).client.request("GET", "/v1/me")))?.key,
  ).toBe("unavailable");
  for (const [code, key] of [
    ["uncertain", "writeUncertain"],
    ["busy", "requestBusy"],
    ["unavailable", "unavailable"],
    ["not_ready", "unavailable"],
  ] as const) {
    const request = vi.fn(async () => {
      throw new BridgeBackendError(code);
    });
    expect((await failure(createClient(request).request("PUT", "/v1/manage/settings", {})))?.key).toBe(key);
    expect(request).toHaveBeenCalledTimes(1);
  }
});

test("an uncertain write keeps the draft and tells the administrator not to assume it was saved", async () => {
  const user = userEvent.setup();
  const app = mount({
    handler: (method) => {
      if (method === "PUT") throw new Error("lost");
      return undefined;
    },
  });
  await openManagement(app);
  await user.click(screen.getByRole("tab", { name: "Credentials", exact: true }));
  await user.click(screen.getByRole("button", { name: "New credential", exact: true }));
  const dialog = screen.getByRole("dialog");
  await user.type(within(dialog).getByLabelText("Internal label", { exact: true }), "Fixture account");
  await user.type(
    within(dialog).getByLabelText("API key / heartbeat signing secret", { exact: true }),
    "fixture-only-value",
  );
  await user.click(within(dialog).getByRole("button", { name: "Save", exact: true }));
  expect(await within(dialog).findByRole("alert")).toBeTruthy();
  expect((within(dialog).getByLabelText("Internal label", { exact: true }) as HTMLInputElement).value).toBe("Fixture account");
});

test("every locale carries the same keys", () => {
  const keys = Object.keys(locales["en-US"]).sort();
  expect(Object.keys(locales["zh-CN"]).sort()).toEqual(keys);
  expect(Object.keys(locales["zh-TW"]).sort()).toEqual(keys);
  void act;
});
