import { MessageChannel as NodeMessageChannel } from "node:worker_threads";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { createBridgeHost, type BridgePresentation } from "../src/bridge-v2";
import { AppRoot, useAppNetworkTargets } from "../src/root-v2";

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

const target = {
  id: "api",
  origin: "https://api.example.com",
  paths: ["/v1/*"],
  methods: ["GET"],
  network: "public",
};

function mount(
  w: ReturnType<typeof windows>,
  capture: (value: ReturnType<typeof useAppNetworkTargets>) => void,
) {
  function TargetsApp() {
    capture(useAppNetworkTargets());
    return null;
  }
  return render(
    <AppRoot
      localWindow={w.child}
      parentWindow={w.host}
      parentOrigin="https://portal.example.invalid"
    >
      <TargetsApp />
    </AppRoot>,
  );
}

test("useAppNetworkTargets returns what the host answered and nothing it did not", async () => {
  const w = windows();
  const ask = vi.fn(async () => ({ state: "applied", policyRevision: "2" }) as const);
  const host = createBridgeHost({
    localWindow: w.host,
    frameWindow: w.child,
    binding,
    presentation,
    capabilities: ["network.http"],
    onNetworkTargetsRequest: ask,
  });
  disposals.push(() => host.close());
  let observed: ReturnType<typeof useAppNetworkTargets> | undefined;
  mount(w, (value) => (observed = value));
  await waitFor(() => expect(host.state()).toBe("ready"));
  expect(observed).toMatchObject({ available: true, ready: true });
  await expect(observed!.request([target])).resolves.toEqual({
    state: "applied",
    policyRevision: "2",
  });
  expect(ask).toHaveBeenCalledOnce();
  await expect(
    observed!.request([{ ...target, bounds: { requestBytes: 1 } } as never]),
  ).rejects.toMatchObject({ code: "invalid_request" });
  expect(ask).toHaveBeenCalledOnce();
});

test("a host that cannot review answers not_permitted, and an app without network.http cannot ask", async () => {
  const w = windows();
  const host = createBridgeHost({
    localWindow: w.host,
    frameWindow: w.child,
    binding,
    presentation,
    capabilities: ["network.http"],
  });
  disposals.push(() => host.close());
  let observed: ReturnType<typeof useAppNetworkTargets> | undefined;
  mount(w, (value) => (observed = value));
  await waitFor(() => expect(host.state()).toBe("ready"));
  await expect(observed!.request([target])).resolves.toEqual({ state: "not_permitted" });

  const other = windows();
  const bare = createBridgeHost({
    localWindow: other.host,
    frameWindow: other.child,
    binding,
    presentation,
    capabilities: [],
  });
  disposals.push(() => bare.close());
  let none: ReturnType<typeof useAppNetworkTargets> | undefined;
  mount(other, (value) => (none = value));
  await waitFor(() => expect(bare.state()).toBe("ready"));
  expect(none).toMatchObject({ available: false, ready: false });
  await expect(none!.request([target])).rejects.toMatchObject({ code: "unsupported" });
});

test("a request made after the document is retired is refused", async () => {
  const w = windows();
  const host = createBridgeHost({
    localWindow: w.host,
    frameWindow: w.child,
    binding,
    presentation,
    capabilities: ["network.http"],
    onNetworkTargetsRequest: async () => ({ state: "declined" }),
  });
  disposals.push(() => host.close());
  let observed: ReturnType<typeof useAppNetworkTargets> | undefined;
  const view = mount(w, (value) => (observed = value));
  await waitFor(() => expect(host.state()).toBe("ready"));
  const old = observed!;
  view.unmount();
  await expect(old.request([target])).rejects.toMatchObject({ code: "not_ready" });
});
