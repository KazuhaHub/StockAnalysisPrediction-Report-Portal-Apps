import { MessageChannel } from "node:worker_threads";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { AppRoot } from "@portal-app/sdk/root-v2";
import {
  createBridgeHost,
  type BridgePresentation,
  type PageActionSnapshot,
} from "@portal-app/sdk/bridge-v2";
import { Application } from "../src/App";
import bootstrap from "../src/bootstrap.json";

const close: Array<() => void> = [];
afterEach(() => {
  cleanup();
  close.splice(0).forEach((dispose) => dispose());
  vi.unstubAllGlobals();
});

function windows() {
  const listeners = [
    new Set<(event: MessageEvent) => void>(),
    new Set<(event: MessageEvent) => void>(),
  ];
  const peers = [0, 1].map((index) => ({
    addEventListener: (
      _name: string,
      listener: (event: MessageEvent) => void,
    ) => listeners[index].add(listener),
    removeEventListener: (
      _name: string,
      listener: (event: MessageEvent) => void,
    ) => listeners[index].delete(listener),
    postMessage: (
      data: unknown,
      _origin: string,
      ports: MessagePort[] = [],
    ) => {
      const copy = structuredClone({ data, ports }, { transfer: ports });
      close.push(() => copy.ports.forEach((port) => port.close()));
      const event = {
        ...copy,
        source: peers[1 - index],
        origin: index === 1 ? bootstrap.parentOrigin : "null",
      } as unknown as MessageEvent;
      queueMicrotask(() =>
        listeners[index].forEach((listener) => listener(event)),
      );
    },
  }));
  return peers as unknown as [Window, Window];
}

test("renders backend digest state and uses host navigation without a duplicate header", async () => {
  vi.stubGlobal("MessageChannel", MessageChannel);
  const [parent, child] = windows();
  let state: PageActionSnapshot | null = null;
  let presentation: BridgePresentation = {
    locale: "en-US",
    timeZone: "UTC",
    layout: "document",
    theme: {
      dark: true,
      colorPrimary: "#1677ff",
      colorBg: "#141414",
      colorText: "#ffffff",
      colorBorder: "#424242",
      colorBgLayout: "#000000",
      borderRadius: 8,
    },
    navigation: {
      path: "/",
      search: "",
      routes: [
        { id: "home", path: "/", layout: "document" },
        { id: "history", path: "/history", layout: "document" },
      ],
    },
  };
  const backend = vi.fn(async () => ({
    status: 200,
    body: JSON.stringify({
      format: "scheduled-digest.state/1-dev.1",
      scheduleId: "daily",
      lastRun: {
        occurrenceId: "digest:2026-11-03",
        generatedAt: "2026-11-04T07:00:00Z",
        itemCount: 2,
        digest: "a".repeat(64),
        duplicate: false,
      },
      recentRuns: [
        {
          occurrenceId: "digest:2026-11-03",
          generatedAt: "2026-11-04T07:00:00Z",
          itemCount: 2,
          digest: "a".repeat(64),
          duplicate: false,
        },
      ],
    }),
  }));
  const feed = vi.fn(async () => ({
    status: 200,
    contentType: "application/json",
    bodyBase64: btoa("{}"),
  }));
  const host = createBridgeHost({
    localWindow: parent,
    frameWindow: child,
    binding: {
      installationId: "00000000-0000-0000-0000-000000000001",
      generation: "1",
      policyRevision: "1",
      releaseSha256: "b".repeat(64),
    },
    capabilities: ["network.http", "secrets.use"],
    presentation,
    onPageChange: (value) => {
      state = value;
    },
    onBackendRequest: backend,
    onNetworkRequest: feed,
    onNavigate: (path, _replace, search) => {
      presentation = {
        ...presentation,
        navigation: { ...presentation.navigation!, path, search },
      };
      host.updatePresentation(presentation);
    },
  });
  close.push(() => host.close());
  render(
    <AppRoot
      parentOrigin={bootstrap.parentOrigin}
      localWindow={child}
      parentWindow={parent}
    >
      <Application />
    </AppRoot>,
  );
  await waitFor(() => expect(state?.page.title).toBe("Scheduled Digest"));
  expect(screen.queryByRole("heading")).toBeNull();
  expect(await screen.findByText("digest:2026-11-03")).toBeTruthy();
  expect(screen.getByText("2")).toBeTruthy();
  await screen.findByText("Reviewed feed");
  fireEvent.click(
    screen.getByRole("button", { name: "Check configured feed" }),
  );
  await waitFor(() => expect(feed).toHaveBeenCalledTimes(1));
  expect(feed.mock.calls[0][0]).toMatchObject({
    credential: "digest-feed",
    url: "https://digest-feed.example.invalid/v1/summary",
  });
  expect(await screen.findByText("The reviewed feed responded.")).toBeTruthy();
  expect(backend).toHaveBeenCalledWith(
    { method: "GET", path: "/v1/digest", body: "" },
    expect.any(AbortSignal),
  );
  await waitFor(() =>
    expect(
      state?.page.actions.find((action) => action.id === "history")?.disabled,
    ).toBe(false),
  );
  act(() => {
    expect(state!.invoke("history")).toBe(true);
  });
  await waitFor(() => expect(state?.page.title).toBe("Digest history"));
  expect(await screen.findByText("digest:2026-11-03")).toBeTruthy();
  act(() => {
    presentation = { ...presentation, locale: "zh-CN" };
    host.updatePresentation(presentation);
  });
  await waitFor(() => expect(state?.page.title).toBe("摘要历史"));
  expect(screen.getByText("摘要项目")).toBeTruthy();
  expect(screen.queryByRole("heading")).toBeNull();
});
