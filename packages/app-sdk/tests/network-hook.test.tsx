import { MessageChannel as NodeMessageChannel } from "node:worker_threads";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { createBridgeHost, type BridgePresentation } from "../src/bridge-v2";
import { AppRoot, useAppNetwork } from "../src/root-v2";

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
    addEventListener: (_type: string, listener: (event: MessageEvent) => void) =>
      listeners[index].add(listener),
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
  locale: "zh-CN",
  timeZone: "Asia/Shanghai",
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
};

test("useAppNetwork converts binary bodies and retires old requests with the presentation", async () => {
  const w = windows();
  const dispatch = vi.fn(async () => ({
    status: 401,
    contentType: "application/octet-stream",
    bodyBase64: "/wCA",
  }));
  const host = createBridgeHost({
    localWindow: w.host,
    frameWindow: w.child,
    binding,
    presentation,
    capabilities: ["network.http", "secrets.use"],
    onNetworkRequest: dispatch,
  });
  disposals.push(() => host.close());
  let observed: ReturnType<typeof useAppNetwork> | undefined;
  let resolvedBody: Uint8Array | undefined;
  function NetworkApp() {
    const network = useAppNetwork();
    observed = network;
    return (
      <button
        disabled={!network.ready}
        onClick={() => {
          void network.request({
            method: "POST",
            url: "https://api.example.com/v1/check",
            accept: "application/octet-stream",
            contentType: "application/octet-stream",
            body: new Uint8Array([0, 255, 128]),
          }).then((result) => {
            resolvedBody = result.body;
          });
        }}
      >
        Send
      </button>
    );
  }
  const view = render(
    <AppRoot
      localWindow={w.child}
      parentWindow={w.host}
      parentOrigin="https://portal.example.invalid"
    >
      <NetworkApp />
    </AppRoot>,
  );
  await waitFor(() => expect(host.state()).toBe("ready"));
  expect(observed).toMatchObject({
    available: true,
    credentialAvailable: true,
    ready: true,
  });
  const stableRequest = observed!.request;
  await act(async () => {
    screen.getByRole("button").click();
    await waitFor(() => expect(dispatch).toHaveBeenCalledOnce());
    await waitFor(() =>
      expect(Array.from(resolvedBody ?? [])).toEqual([255, 0, 128]),
    );
  });
  expect(dispatch.mock.calls[0][0]).toEqual({
    method: "POST",
    url: "https://api.example.com/v1/check",
    accept: "application/octet-stream",
    contentType: "application/octet-stream",
    bodyBase64: "AP+A",
  });
  act(() =>
    host.updatePresentation({ ...presentation, locale: "zh-TW" }),
  );
  await waitFor(() => expect(document.documentElement.lang).toBe("zh-TW"));
  expect(observed!.request).toBe(stableRequest);
  const old = observed!;
  view.unmount();
  await expect(
    old.request({
      method: "GET",
      url: "https://api.example.com/v1/check",
    }),
  ).rejects.toMatchObject({ code: "not_ready", retryable: false });
  expect(dispatch).toHaveBeenCalledOnce();
});

test("useAppNetwork exposes only a stable credential binding name", async () => {
  const w = windows();
  const dispatch = vi.fn(async () => ({
    status: 200,
    contentType: "application/json",
    bodyBase64: "e30=",
  }));
  const host = createBridgeHost({
    localWindow: w.host,
    frameWindow: w.child,
    binding,
    presentation,
    capabilities: ["network.http", "secrets.use"],
    onNetworkRequest: dispatch,
  });
  disposals.push(() => host.close());
  let observed: ReturnType<typeof useAppNetwork> | undefined;
  function NetworkApp() {
    observed = useAppNetwork();
    return null;
  }
  render(
    <AppRoot
      localWindow={w.child}
      parentWindow={w.host}
      parentOrigin="https://portal.example.invalid"
    >
      <NetworkApp />
    </AppRoot>,
  );
  await waitFor(() => expect(host.state()).toBe("ready"));
  await act(async () => {
    await observed!.request({
      method: "GET",
      url: "https://api.example.com/v1/check",
      credential: "upstream-api",
    });
  });
  expect(dispatch.mock.calls[0][0]).toMatchObject({
    credential: "upstream-api",
  });
  expect(JSON.stringify(dispatch.mock.calls[0][0])).not.toContain(
    "disposable-secret-value",
  );
});

test("useAppNetwork is unavailable without the exact host grant", async () => {
  const w = windows();
  const host = createBridgeHost({
    localWindow: w.host,
    frameWindow: w.child,
    binding,
    presentation,
    capabilities: [],
  });
  disposals.push(() => host.close());
  let observed: ReturnType<typeof useAppNetwork> | undefined;
  function NetworkApp() {
    observed = useAppNetwork();
    return <span>{String(observed.available)}</span>;
  }
  render(
    <AppRoot
      localWindow={w.child}
      parentWindow={w.host}
      parentOrigin="https://portal.example.invalid"
    >
      <NetworkApp />
    </AppRoot>,
  );
  await waitFor(() => expect(host.state()).toBe("ready"));
  expect(observed).toMatchObject({ available: false, ready: false });
  await expect(
    observed!.request({
      method: "GET",
      url: "https://api.example.com/v1/check",
    }),
  ).rejects.toMatchObject({ code: "unsupported", retryable: false });
});
