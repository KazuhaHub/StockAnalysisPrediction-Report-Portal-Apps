import { MessageChannel as NodeMessageChannel } from "node:worker_threads";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import {
  BridgeReportError,
  createBridgeHost,
  type BridgePresentation,
} from "../src/bridge-v2";
import { AppRoot, useAppReports } from "../src/root-v2";

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
const summary = {
  id: 42,
  runId: "run-42",
  symbol: "600100",
  name: "Example",
  date: "2026-10-30",
  time: "09:30",
  kind: "research",
  subtype: "daily",
  title: "Current report",
  source: "analysis",
  version: "report-version",
};

test("useAppReports exposes current viewer query/get and retires old closures", async () => {
  const w = windows();
  const dispatch = vi.fn(
    async (request: { kind: "query" | "get" }, _signal: AbortSignal) =>
      request.kind === "get"
        ? {
            kind: "get" as const,
            report: { ...summary, bodyMarkdown: "# Current report" },
          }
        : {
            kind: "query" as const,
            count: 1,
            total: 3,
            offset: 0,
            limit: 20,
            items: [summary],
          },
  );
  const host = createBridgeHost({
    localWindow: w.host,
    frameWindow: w.child,
    binding,
    presentation,
    capabilities: ["reports.read"],
    onReportRequest: dispatch,
  });
  disposals.push(() => host.close());
  let observed: ReturnType<typeof useAppReports> | undefined;
  let queryCount = 0;
  let detailBody = "";
  function ReportsApp() {
    const reports = useAppReports();
    observed = reports;
    return (
      <>
        <button
          disabled={!reports.ready}
          onClick={() => {
            void reports
              .query({ q: "current", date: "today", limit: 20 })
              .then((result) => {
                if (result.kind === "query") queryCount = result.total;
              });
          }}
        >
          Query
        </button>
        <button
          disabled={!reports.ready}
          onClick={() => {
            void reports.get(42).then((result) => {
              if (result.kind === "get")
                detailBody = result.report.bodyMarkdown;
            });
          }}
        >
          Detail
        </button>
      </>
    );
  }
  const view = render(
    <AppRoot
      localWindow={w.child}
      parentWindow={w.host}
      parentOrigin="https://portal.example.invalid"
    >
      <ReportsApp />
    </AppRoot>,
  );
  await waitFor(() => expect(host.state()).toBe("ready"));
  expect(observed).toMatchObject({ available: true, ready: true });
  const stableQuery = observed!.query;
  const stableGet = observed!.get;
  await act(async () => {
    screen.getByRole("button", { name: "Query" }).click();
    screen.getByRole("button", { name: "Detail" }).click();
    await waitFor(() => expect(dispatch).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(queryCount).toBe(3));
    await waitFor(() => expect(detailBody).toBe("# Current report"));
  });
  expect(dispatch.mock.calls[0][0]).toEqual({
    kind: "query",
    query: { q: "current", date: "today", limit: 20 },
  });
  expect(dispatch.mock.calls[1][0]).toEqual({ kind: "get", id: 42 });
  act(() => host.updatePresentation({ ...presentation, locale: "zh-TW" }));
  await waitFor(() => expect(document.documentElement.lang).toBe("zh-TW"));
  expect(observed!.query).toBe(stableQuery);
  expect(observed!.get).toBe(stableGet);
  const old = observed!;
  view.unmount();
  await expect(old.query({ limit: 20 })).rejects.toMatchObject({
    code: "not_ready",
    retryable: false,
  });
  await expect(old.get(42)).rejects.toMatchObject({ code: "not_ready" });
  expect(dispatch).toHaveBeenCalledTimes(2);
});

test("useAppReports is unavailable without the exact current grant", async () => {
  const w = windows();
  const host = createBridgeHost({
    localWindow: w.host,
    frameWindow: w.child,
    binding,
    presentation,
    capabilities: [],
  });
  disposals.push(() => host.close());
  let observed: ReturnType<typeof useAppReports> | undefined;
  function ReportsApp() {
    observed = useAppReports();
    return <span>{String(observed.available)}</span>;
  }
  render(
    <AppRoot
      localWindow={w.child}
      parentWindow={w.host}
      parentOrigin="https://portal.example.invalid"
    >
      <ReportsApp />
    </AppRoot>,
  );
  await waitFor(() => expect(host.state()).toBe("ready"));
  expect(observed).toMatchObject({ available: false, ready: false });
  await expect(observed!.query({ limit: 20 })).rejects.toMatchObject({
    code: "unsupported",
    retryable: false,
  });
  await expect(observed!.get(42)).rejects.toMatchObject({
    code: "unsupported",
  });
});

test("useAppReports keeps validation and host failures closed", async () => {
  const w = windows();
  const dispatch = vi.fn(async () => {
    throw new BridgeReportError("uncertain");
  });
  const host = createBridgeHost({
    localWindow: w.host,
    frameWindow: w.child,
    binding,
    presentation,
    capabilities: ["reports.read"],
    onReportRequest: dispatch,
  });
  disposals.push(() => host.close());
  let observed: ReturnType<typeof useAppReports> | undefined;
  function ReportsApp() {
    observed = useAppReports();
    return null;
  }
  render(
    <AppRoot
      localWindow={w.child}
      parentWindow={w.host}
      parentOrigin="https://portal.example.invalid"
    >
      <ReportsApp />
    </AppRoot>,
  );
  await waitFor(() => expect(observed?.ready).toBe(true));
  await expect(observed!.query({ limit: 51 })).rejects.toMatchObject({
    code: "invalid_request",
    retryable: false,
  });
  await expect(observed!.get(0)).rejects.toMatchObject({
    code: "invalid_request",
  });
  expect(dispatch).not.toHaveBeenCalled();
  await expect(observed!.query({ limit: 20 })).rejects.toMatchObject({
    code: "uncertain",
    retryable: false,
  });
  expect(dispatch).toHaveBeenCalledOnce();
});
