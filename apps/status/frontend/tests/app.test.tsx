import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { StatusApp } from "../src/App";
import type { Client } from "../src/client";
import { PortalClient } from "@portal-app/sdk";
import { locales } from "../src/ui";

afterEach(cleanup);
function fixture(admin = true) {
  const request = vi.fn(async (_method: string, path: string) => {
    if (path === "/v1/me")
      return {
        admin,
        api_version: 1,
        capabilities: [
          "status.components.v1",
          "status.history.v2",
          "status.export.v1",
          "status.retention.v1",
          "status.postgres-unix.v1",
        ],
      };
    if (path === "/v1/manage/operations")
      return {
        settings: {
          public_enabled: false,
          probes_paused: true,
          outbox_paused: true,
          raw_retention_days: 30,
          history_retention_days: 90,
          portal_url: "",
          portal_networks: [],
        },
        queue_fingerprint: "empty",
        outbox: [],
        publishers: [],
      };
    return { items: [], total: 0 };
  });
  return {
    request,
    client: {
      request,
      directory: vi.fn(async () => ({ items: [] })),
    } as unknown as Client,
  };
}
test("the trusted panel locale arrives after startup and changes without losing the active draft", async () => {
  const parent = {} as Window;
  const bridge = new PortalClient("status", { parent, current: window });
  const f = fixture();
  f.client.getTheme = bridge.getTheme;
  f.client.subscribeTheme = bridge.subscribeTheme;
  try {
    render(<StatusApp client={f.client} />);
    act(() => window.dispatchEvent(new MessageEvent("message", { source: parent, data: { type: "rp:init", locale: "en-US" } })));
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Manage", exact: true }));
    await user.click(await screen.findByRole("button", { name: "New component", exact: true }));
    await user.type(screen.getByLabelText("Internal label", { exact: true }), "Keep locale draft");
    for (const [type, locale] of [["rp:init", "zh-CN"], ["rp:theme", "zh-TW"], ["rp:theme", "en"]]) {
      act(() => window.dispatchEvent(new MessageEvent("message", { source: parent, data: { type, locale } })));
      const supported = locale === "en" ? "en-US" : locale as "zh-CN" | "zh-TW";
      await screen.findByRole("heading", { name: locales[supported].title, exact: true });
      expect(document.documentElement.lang).toBe(supported);
      expect(screen.getByDisplayValue("Keep locale draft")).toBeTruthy();
      expect(screen.getByRole("dialog")).toBeTruthy();
    }
  } finally {
    bridge.dispose();
  }
});
test("the initial overview stays compact and ordinary viewers have no management entry", async () => {
  const f = fixture(false);
  render(<StatusApp client={f.client} />);
  await screen.findByText(/No visible components/);
  expect(screen.queryByRole("combobox")).toBeNull();
  expect(
    screen.queryByRole("button", { name: "Manage", exact: true }),
  ).toBeNull();
  expect(screen.queryByText("Queue review fingerprint")).toBeNull();
});
test("component setup reveals one step at a time and keeps advanced fields folded", async () => {
  const user = userEvent.setup(),
    f = fixture();
  render(<StatusApp client={f.client} />);
  await user.click(
    await screen.findByRole("button", { name: "Manage", exact: true }),
  );
  await user.click(
    await screen.findByRole("button", { name: "New component", exact: true }),
  );
  const drawer = await screen.findByRole("dialog");
  await user.type(
    within(drawer).getByLabelText("Internal label", { exact: true }),
    "A service",
  );
  expect(
    within(drawer).queryByLabelText("Allowed private CIDRs (one per line)"),
  ).toBeNull();
  await user.click(
    within(drawer).getByRole("button", { name: "Next", exact: true }),
  );
  expect(within(drawer).getByLabelText("Target URL")).toBeTruthy();
  expect(within(drawer).queryByLabelText("Interval (seconds)")).toBeNull();
  expect(within(drawer).queryByLabelText("Who can see amounts")).toBeNull();
});
test("failed saves retain the wizard draft and repeated activation cannot duplicate writes", async () => {
  const user = userEvent.setup(),
    f = fixture();
  let writes = 0,
    rejectWrite: (e: Error) => void = () => {};
  const prior = f.request.getMockImplementation()!;
  f.request.mockImplementation(async (method, path, body?: unknown) => {
    if (method === "PUT") {
      writes++;
      return new Promise((_resolve, reject) => {
        rejectWrite = reject;
      });
    }
    return prior(method, path, body);
  });
  render(<StatusApp client={f.client} />);
  await user.click(
    await screen.findByRole("button", { name: "Manage", exact: true }),
  );
  await user.click(
    await screen.findByRole("button", { name: "New component", exact: true }),
  );
  const d = within(await screen.findByRole("dialog"));
  await user.type(
    d.getByLabelText("Internal label", { exact: true }),
    "Keep my draft",
  );
  await user.click(d.getByRole("button", { name: "Next", exact: true }));
  await user.type(d.getByLabelText("Target URL"), "https://example.org/health");
  await user.click(d.getByRole("button", { name: "Next", exact: true }));
  const save = d.getByRole("button", { name: "Save", exact: true });
  fireEvent.click(save);
  fireEvent.click(save);
  await waitFor(() => expect(writes).toBe(1));
  rejectWrite(new Error("Conflict"));
  await screen.findByRole("alert");
  await user.click(d.getByRole("button", { name: "Previous", exact: true }));
  expect((d.getByLabelText("Target URL") as HTMLInputElement).value).toBe(
    "https://example.org/health",
  );
});
test("resuming probes does not resume notification publication implicitly", async () => {
  const user = userEvent.setup(),
    f = fixture();
  render(<StatusApp client={f.client} />);
  await user.click(
    await screen.findByRole("button", { name: "Manage", exact: true }),
  );
  await user.click(
    await screen.findByRole("tab", { name: "Operations", exact: true }),
  );
  await user.click(
    (
      await screen.findAllByRole("button", {
        name: "Review and resume",
        exact: true,
      })
    )[0],
  );
  const d = within(await screen.findByRole("dialog"));
  await user.click(
    d.getByRole("checkbox", { name: "Resume probes", exact: true }),
  );
  await user.click(
    d.getByRole("checkbox", {
      name: "I reviewed the current queue and potential duplicate publication",
      exact: true,
    }),
  );
  await user.click(
    d.getByRole("button", { name: "Resume selected work", exact: true }),
  );
  await waitFor(() =>
    expect(f.request).toHaveBeenCalledWith("POST", "/v1/manage/resume", {
      queue_fingerprint: "empty",
      probes: true,
      outbox: false,
    }),
  );
});

test("credential save errors stay inside the dialog and retain the secret draft", async () => {
  const f = fixture(),
    user = userEvent.setup();
  const original = f.request.getMockImplementation()!;
  f.request.mockImplementation(async (method, path) => {
    if (method === "PUT") throw { key: "configurationConflict" };
    return original(method, path);
  });
  render(<StatusApp client={f.client} />);
  await user.click(
    await screen.findByRole("button", { name: "Manage", exact: true }),
  );
  await user.click(
    screen.getByRole("tab", { name: "Credentials", exact: true }),
  );
  await user.click(
    screen.getByRole("button", { name: "New credential", exact: true }),
  );
  const dialog = screen.getByRole("dialog");
  await user.type(
    within(dialog).getByLabelText("Internal label", { exact: true }),
    "Fixture account",
  );
  await user.type(
    within(dialog).getByLabelText("API key / heartbeat signing secret", {
      exact: true,
    }),
    "fixture-only-value",
  );
  await user.click(
    within(dialog).getByRole("button", { name: "Save", exact: true }),
  );
  expect(await within(dialog).findByRole("alert")).toBeTruthy();
  expect(
    (
      within(dialog).getByLabelText("API key / heartbeat signing secret", {
        exact: true,
      }) as HTMLInputElement
    ).value,
  ).toBe("fixture-only-value");
});

test("the save action keeps its accessible name while the directory is loading", async () => {
  const f = fixture(),
    user = userEvent.setup();
  let finish!: (value: { items: [] }) => void;
  const response = new Promise<{ items: [] }>((resolve) => {
    finish = resolve;
  });
  f.client.directory = vi.fn(() => response) as Client["directory"];
  render(<StatusApp client={f.client} />);
  await user.click(
    await screen.findByRole("button", { name: "Manage", exact: true }),
  );
  await user.click(
    screen.getByRole("button", { name: "New component", exact: true }),
  );
  await user.type(
    screen.getByLabelText("Internal label", { exact: true }),
    "Fixture",
  );
  await user.click(screen.getByRole("button", { name: "Next", exact: true }));
  await user.type(
    screen.getByLabelText("Target URL", { exact: true }),
    "https://fixture.invalid/health",
  );
  await user.click(screen.getByRole("button", { name: "Next", exact: true }));
  await user.click(
    screen.getByRole("button", {
      name: "Load users and organizational units",
      exact: true,
    }),
  );
  expect(
    (
      screen.getByRole("button", {
        name: "Save",
        exact: true,
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  finish({ items: [] });
  await waitFor(() =>
    expect(
      (
        screen.getByRole("button", {
          name: "Save",
          exact: true,
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(false),
  );
});
