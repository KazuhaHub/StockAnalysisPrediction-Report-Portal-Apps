import { MessageChannel as NodeMessageChannel } from "node:worker_threads";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import {
  BridgeNotificationError,
  createBridgeHost,
  type BridgePresentation,
} from "../src/bridge-v2";
import { AppRoot, useAppNotifications } from "../src/root-v2";

const disposals: (() => void)[] = [];
afterEach(() => {
  cleanup();
  for (const dispose of disposals.splice(0)) dispose();
  vi.unstubAllGlobals();
});
beforeEach(() => {
  vi.stubGlobal("MessageChannel", NodeMessageChannel);
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({
      matches: false,
      addListener() {},
      removeListener() {},
      addEventListener() {},
      removeEventListener() {},
    })),
  );
});

function windows() {
  const listeners = [
    new Set<(event: MessageEvent) => void>(),
    new Set<(event: MessageEvent) => void>(),
  ];
  const ports: MessagePort[] = [];
  const peers = [0, 1].map((index) => ({
    addEventListener: (
      _type: string,
      listener: (event: MessageEvent) => void,
    ) => listeners[index].add(listener),
    removeEventListener: (
      _type: string,
      listener: (event: MessageEvent) => void,
    ) => listeners[index].delete(listener),
    postMessage: (
      data: unknown,
      _origin: string,
      transfer: MessagePort[] = [],
    ) => {
      const cloned = structuredClone({ data, ports: transfer }, { transfer });
      ports.push(...cloned.ports);
      const from = 1 - index;
      const event = {
        ...cloned,
        source: peers[from],
        origin: from === 0 ? "https://portal.example.invalid" : "null",
      } as unknown as MessageEvent;
      queueMicrotask(() => {
        for (const listener of listeners[index]) listener(event);
      });
    },
  }));
  disposals.push(() => {
    for (const port of ports) port.close();
  });
  return {
    host: peers[0] as unknown as Window,
    child: peers[1] as unknown as Window,
  };
}

const binding = {
  installationId: "00000000-0000-0000-0000-000000000001",
  generation: "9007199254740993",
  policyRevision: "1",
  releaseSha256: "a".repeat(64),
};
const presentation: BridgePresentation = {
  locale: "en-US",
  timeZone: "America/Los_Angeles",
  layout: "document",
  theme: {
    dark: false,
    colorPrimary: "#1677ff",
    colorBg: "#ffffff",
    colorText: "#1f1f1f",
    colorBorder: "#d9d9d9",
    colorBgLayout: "#f5f5f5",
    borderRadius: 8,
  },
};
const request = {
  occurrenceId: "digest:2026-11-02",
  title: "Daily digest",
  message: "Three reports are ready.",
  severity: "info" as const,
};

test("useAppNotifications publishes the stable occurrence request", async () => {
  const w = windows();
  const dispatch = vi.fn(
    async (_value: unknown, _signal: AbortSignal) => ({
      id: "00000000-0000-4000-8000-000000000042",
    }),
  );
  const host = createBridgeHost({
    localWindow: w.host,
    frameWindow: w.child,
    binding,
    presentation,
    capabilities: ["notifications.publish"],
    onNotificationRequest: dispatch,
  });
  disposals.push(() => host.close());
  let observed: ReturnType<typeof useAppNotifications> | undefined;
  let published = "";
  function NotificationsApp() {
    const notifications = useAppNotifications();
    observed = notifications;
    return (
      <button
        disabled={!notifications.ready}
        onClick={() => {
          void notifications.publish(request).then((result) => {
            published = result.id;
          });
        }}
      >
        Publish
      </button>
    );
  }
  render(
    <AppRoot
      localWindow={w.child}
      parentWindow={w.host}
      parentOrigin="https://portal.example.invalid"
    >
      <NotificationsApp />
    </AppRoot>,
  );
  await waitFor(() => expect(host.state()).toBe("ready"));
  expect(observed).toMatchObject({ available: true, ready: true });
  screen.getByRole("button", { name: "Publish" }).click();
  await waitFor(() =>
    expect(published).toBe("00000000-0000-4000-8000-000000000042"),
  );
  expect(dispatch).toHaveBeenCalledWith(request, expect.any(AbortSignal));
});

test("useAppNotifications fails closed without the exact grant", async () => {
  const w = windows();
  const dispatch = vi.fn().mockRejectedValue(
    new BridgeNotificationError("conflict"),
  );
  const host = createBridgeHost({
    localWindow: w.host,
    frameWindow: w.child,
    binding,
    presentation,
    capabilities: [],
    onNotificationRequest: dispatch,
  });
  disposals.push(() => host.close());
  let observed: ReturnType<typeof useAppNotifications> | undefined;
  function NotificationsApp() {
    observed = useAppNotifications();
    return <span>{String(observed.available)}</span>;
  }
  render(
    <AppRoot
      localWindow={w.child}
      parentWindow={w.host}
      parentOrigin="https://portal.example.invalid"
    >
      <NotificationsApp />
    </AppRoot>,
  );
  await waitFor(() => expect(host.state()).toBe("ready"));
  expect(observed).toMatchObject({ available: false, ready: false });
  await expect(
    observed!.publish(request, new AbortController().signal),
  ).rejects.toMatchObject({ code: "unsupported", retryable: false });
  expect(dispatch).not.toHaveBeenCalled();
});
