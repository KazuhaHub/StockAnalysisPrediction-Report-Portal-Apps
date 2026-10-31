import { MessageChannel as NodeMessageChannel } from "node:worker_threads";
import { act, cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import {
  BridgeObjectError,
  createBridgeHost,
  parseBridgeObjectRequest,
  type BridgePresentation,
} from "../src/bridge-v2";
import { AppRoot, useAppObjects } from "../src/root-v2";

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
  installationId: "00000000-0000-4000-8000-000000000001",
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
const summary = {
  id: "00000000-0000-4000-8000-000000000042",
  collection: "note",
  label: "First note",
  mediaType: "application/json",
  sizeBytes: 5,
  revision: 1,
  createdAt: 1,
  updatedAt: 1,
};

test("useAppObjects converts content and keeps stable lifecycles", async () => {
  const w = windows();
  const dispatch = vi.fn(async (request: { action: string }, _signal: AbortSignal) => {
    switch (request.action) {
      case "list":
        return { action: "list" as const, items: [summary] };
      case "get":
        return {
          action: "get" as const,
          object: summary,
          contentBase64: "aGVsbG8=",
        };
      case "delete":
        return { action: "delete" as const, id: summary.id };
      default:
        return {
          action: request.action as "create" | "update",
          object: summary,
        };
    }
  });
  const host = createBridgeHost({
    localWindow: w.host,
    frameWindow: w.child,
    binding,
    presentation,
    capabilities: ["storage.files"],
    onObjectRequest: dispatch,
  });
  disposals.push(() => host.close());
  let observed: ReturnType<typeof useAppObjects> | undefined;
  function ObjectsApp() {
    observed = useAppObjects();
    return null;
  }
  const view = render(
    <AppRoot
      localWindow={w.child}
      parentWindow={w.host}
      parentOrigin="https://portal.example.invalid"
    >
      <ObjectsApp />
    </AppRoot>,
  );
  await waitFor(() => expect(observed?.ready).toBe(true));
  const stableList = observed!.list;
  const content = new TextEncoder().encode("hello");
  expect(
    parseBridgeObjectRequest({
      action: "create",
      requestId: "create-1",
      collection: "note",
      label: "First note",
      mediaType: "application/json",
      contentBase64: "aGVsbG8=",
    }),
  ).not.toBeNull();
  let contentBody = "";
  await act(async () => {
    await expect(
      observed!.create({
        requestId: "create-1",
        collection: "note",
        label: "First note",
        mediaType: "application/json",
        content,
      }),
    ).resolves.toMatchObject({ id: summary.id });
    await expect(observed!.list("note")).resolves.toMatchObject({
      items: [summary],
    });
    const detail = await observed!.get(summary.id);
    contentBody = new TextDecoder().decode(detail.content);
    expect(detail).toMatchObject({ id: summary.id });
    await expect(
      observed!.update(summary.id, {
        expectedRevision: 1,
        label: "First note",
        mediaType: "application/json",
        content,
      }),
    ).resolves.toMatchObject({ revision: 1 });
    await expect(observed!.delete(summary.id, 1)).resolves.toBeUndefined();
  });
  expect(contentBody).toBe("hello");
  expect(dispatch).toHaveBeenCalledTimes(5);
  expect(dispatch.mock.calls[0][0]).toMatchObject({
    action: "create",
    contentBase64: "aGVsbG8=",
  });
  act(() => host.updatePresentation({ ...presentation, locale: "zh-TW" }));
  await waitFor(() => expect(document.documentElement.lang).toBe("zh-TW"));
  expect(observed!.list).toBe(stableList);
  const old = observed!;
  view.unmount();
  await expect(old.list("note")).rejects.toMatchObject({
    code: "not_ready",
    retryable: false,
  });
});

test("useAppObjects is unavailable and maps stable host failures", async () => {
  const w = windows();
  const host = createBridgeHost({
    localWindow: w.host,
    frameWindow: w.child,
    binding,
    presentation,
    capabilities: [],
  });
  disposals.push(() => host.close());
  let observed: ReturnType<typeof useAppObjects> | undefined;
  function ObjectsApp() {
    observed = useAppObjects();
    return null;
  }
  render(
    <AppRoot
      localWindow={w.child}
      parentWindow={w.host}
      parentOrigin="https://portal.example.invalid"
    >
      <ObjectsApp />
    </AppRoot>,
  );
  await waitFor(() => expect(host.state()).toBe("ready"));
  expect(observed).toMatchObject({ available: false, ready: false });
  await expect(observed!.list("note")).rejects.toMatchObject({
    code: "unsupported",
    retryable: false,
  });
});

test("useAppObjects validates content and propagates conflicts", async () => {
  const w = windows();
  const dispatch = vi.fn(async () => {
    throw new BridgeObjectError("conflict");
  });
  const host = createBridgeHost({
    localWindow: w.host,
    frameWindow: w.child,
    binding,
    presentation,
    capabilities: ["storage.files"],
    onObjectRequest: dispatch,
  });
  disposals.push(() => host.close());
  let observed: ReturnType<typeof useAppObjects> | undefined;
  function ObjectsApp() {
    observed = useAppObjects();
    return null;
  }
  render(
    <AppRoot
      localWindow={w.child}
      parentWindow={w.host}
      parentOrigin="https://portal.example.invalid"
    >
      <ObjectsApp />
    </AppRoot>,
  );
  await waitFor(() => expect(observed?.ready).toBe(true));
  await expect(
    observed!.create({
      requestId: "create-1",
      collection: "note",
      label: "First note",
      mediaType: "application/json",
      content: "not bytes" as never,
    }),
  ).rejects.toMatchObject({ code: "invalid_request" });
  await expect(
    observed!.create({
      requestId: "create-1",
      collection: "note",
      label: "First note",
      mediaType: "application/json",
      content: new TextEncoder().encode("hello"),
    }),
  ).rejects.toMatchObject({ code: "conflict", retryable: false });
  expect(dispatch).toHaveBeenCalledOnce();
});
