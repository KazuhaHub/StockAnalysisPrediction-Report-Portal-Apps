import { MessageChannel as NodeMessageChannel } from "node:worker_threads";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import {
  BridgePrincipalError,
  createBridgeHost,
  type BridgePresentation,
} from "../src/bridge-v2";
import { AppRoot, useAppPrincipals } from "../src/root-v2";

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
const userP = "user:" + "a".repeat(64);
const ouP = "ou:" + "b".repeat(64);

function mount(host: Window, child: Window, ui: () => React.ReactNode) {
  return render(
    <AppRoot
      localWindow={child}
      parentWindow={host}
      parentOrigin="https://portal.example.invalid"
    >
      {ui()}
    </AppRoot>,
  );
}

test("useAppPrincipals searches with a cursor and resolves labels", async () => {
  const w = windows();
  const dispatch = vi.fn(async (value: { action: string; after?: string }) =>
    value.action === "search"
      ? value.after === ""
        ? {
            action: "search" as const,
            items: [{ principal: ouP, label: "Research", parent: null }],
            next: "abc",
          }
        : { action: "search" as const, items: [], next: "" }
      : {
          action: "resolve" as const,
          items: [{ principal: userP, label: "Ada" }],
          unknown: [ouP],
        },
  );
  const host = createBridgeHost({
    localWindow: w.host,
    frameWindow: w.child,
    binding,
    presentation,
    capabilities: ["principals.read"],
    onPrincipalRequest: dispatch,
  });
  disposals.push(() => host.close());
  let observed: ReturnType<typeof useAppPrincipals> | undefined;
  function PrincipalsApp() {
    observed = useAppPrincipals();
    return <span>directory</span>;
  }
  mount(w.host, w.child, () => <PrincipalsApp />);
  await waitFor(() => expect(host.state()).toBe("ready"));
  expect(observed).toMatchObject({ available: true, ready: true });
  const first = await observed!.search({ kind: "ou", query: "res" });
  expect(first).toEqual({
    items: [{ principal: ouP, label: "Research", parent: null }],
    next: "abc",
  });
  expect(dispatch).toHaveBeenLastCalledWith(
    { action: "search", kind: "ou", query: "res", after: "", limit: 50 },
    expect.any(AbortSignal),
  );
  const second = await observed!.search({ kind: "ou", query: "res", after: first.next!, limit: 10 });
  expect(second).toEqual({ items: [], next: null });
  expect(dispatch).toHaveBeenLastCalledWith(
    { action: "search", kind: "ou", query: "res", after: "abc", limit: 10 },
    expect.any(AbortSignal),
  );
  await expect(observed!.resolve([userP, ouP])).resolves.toEqual({
    items: [{ principal: userP, label: "Ada" }],
    unknown: [ouP],
  });
  expect(dispatch).toHaveBeenLastCalledWith(
    { action: "resolve", principals: [userP, ouP] },
    expect.any(AbortSignal),
  );
});

test("useAppPrincipals fails closed without the exact grant", async () => {
  const w = windows();
  const dispatch = vi.fn().mockRejectedValue(new BridgePrincipalError("not_permitted"));
  const host = createBridgeHost({
    localWindow: w.host,
    frameWindow: w.child,
    binding,
    presentation,
    capabilities: [],
    onPrincipalRequest: dispatch,
  });
  disposals.push(() => host.close());
  let observed: ReturnType<typeof useAppPrincipals> | undefined;
  function PrincipalsApp() {
    observed = useAppPrincipals();
    return <span>{String(observed.available)}</span>;
  }
  mount(w.host, w.child, () => <PrincipalsApp />);
  await waitFor(() => expect(host.state()).toBe("ready"));
  expect(observed).toMatchObject({ available: false, ready: false });
  await expect(observed!.search({ kind: "user" })).rejects.toMatchObject({
    code: "unsupported",
    retryable: false,
  });
  await expect(observed!.resolve([userP])).rejects.toMatchObject({ code: "unsupported" });
  expect(dispatch).not.toHaveBeenCalled();
});

test("useAppPrincipals surfaces the stable administrator refusal", async () => {
  const w = windows();
  const host = createBridgeHost({
    localWindow: w.host,
    frameWindow: w.child,
    binding,
    presentation,
    capabilities: ["principals.read"],
    onPrincipalRequest: vi.fn().mockRejectedValue(new BridgePrincipalError("not_permitted")),
  });
  disposals.push(() => host.close());
  let observed: ReturnType<typeof useAppPrincipals> | undefined;
  function PrincipalsApp() {
    observed = useAppPrincipals();
    return <span>x</span>;
  }
  mount(w.host, w.child, () => <PrincipalsApp />);
  await waitFor(() => expect(host.state()).toBe("ready"));
  await expect(observed!.search({ kind: "user" })).rejects.toMatchObject({
    code: "not_permitted",
    retryable: false,
  });
  await expect(observed!.search({ kind: "group" as never })).rejects.toMatchObject({
    code: "invalid_request",
  });
});
