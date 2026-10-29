import { MessageChannel as NodeMessageChannel } from "node:worker_threads";
import { useEffect, useState, StrictMode } from "react";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { createBridgeHost, type BridgePresentation } from "../src/bridge-v2";
import {
  AppRoot,
  useAppPresentation,
  useAppBackend,
  useAppDraft,
  useAppNavigation,
} from "../src/root-v2";
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
    addEventListener: (_type: string, fn: (event: MessageEvent) => void) =>
      listeners[index].add(fn),
    removeEventListener: (_type: string, fn: (event: MessageEvent) => void) =>
      listeners[index].delete(fn),
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
        for (const fn of listeners[index]) fn(event);
      });
    },
  }));
  disposals.push(() => {
    for (const port of ports) port.close();
  });
  return {
    host: peers[0] as unknown as Window,
    child: peers[1] as unknown as Window,
    listeners,
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
function App() {
  const { presentation, context } = useAppPresentation();
  const [count, setCount] = useState(0);
  return (
    <button onClick={() => setCount((n) => n + 1)}>
      {presentation.locale}/{presentation.timeZone}/{count}/
      {context.binding.generation}
    </button>
  );
}
test("real bridge host sees committed React locale/theme and live updates preserve state", async () => {
  const w = windows();
  const ready = vi.fn(() => {
    expect(document.documentElement.lang).toBe("zh-CN");
    expect(document.body.style.backgroundColor).toBe("rgb(0, 0, 0)");
    expect(screen.getByRole("button").textContent).toBe(
      "zh-CN/Asia/Shanghai/0/9007199254740993",
    );
  });
  const host = createBridgeHost({
    localWindow: w.host,
    frameWindow: w.child,
    binding,
    presentation,
    capabilities: [],
    onReady: ready,
  });
  disposals.push(() => host.close());
  const view = render(
    <StrictMode>
      <AppRoot
        localWindow={w.child}
        parentWindow={w.host}
        parentOrigin="https://portal.example.invalid"
      >
        <App />
      </AppRoot>
    </StrictMode>,
  );
  await waitFor(() => expect(ready).toHaveBeenCalledTimes(1));
  act(() => screen.getByRole("button").click());
  act(() =>
    host.updatePresentation({
      ...presentation,
      locale: "zh-TW",
      timeZone: "Asia/Taipei",
      layout: "viewport",
    }),
  );
  await waitFor(() =>
    expect(screen.getByRole("button").textContent).toBe(
      "zh-TW/Asia/Taipei/1/9007199254740993",
    ),
  );
  expect(ready).toHaveBeenCalledTimes(1);
  expect(document.documentElement.lang).toBe("zh-TW");
  view.unmount();
  expect(w.listeners[1].size).toBe(0);
});
test("a fresh host challenge clears prior context and remounts app state for the new generation", async () => {
  const w = windows();
  const host = createBridgeHost({
    localWindow: w.host,
    frameWindow: w.child,
    binding,
    presentation,
    capabilities: [],
  });
  disposals.push(() => host.close());
  render(
    <AppRoot
      localWindow={w.child}
      parentWindow={w.host}
      parentOrigin="https://portal.example.invalid"
    >
      <App />
    </AppRoot>,
  );
  await waitFor(() => expect(host.state()).toBe("ready"));
  act(() => screen.getByRole("button").click());
  host.close();
  const replacement = createBridgeHost({
    localWindow: w.host,
    frameWindow: w.child,
    binding: { ...binding, generation: "9007199254740994" },
    presentation: { ...presentation, locale: "en-US" },
    capabilities: [],
  });
  disposals.push(() => replacement.close());
  await waitFor(() => expect(replacement.state()).toBe("ready"));
  expect(screen.getByRole("button").textContent).toBe(
    "en-US/Asia/Shanghai/0/9007199254740994",
  );
});

test("real React backend hook waits for ready and presentation changes do not repeat data reads", async () => {
  const w = windows();
  const dispatch = vi.fn(
    async (request: { method: string; path: string; body: string }) => {
      expect(host.state()).toBe("ready");
      return {
        status: 200,
        body: JSON.stringify({ value: request.method === "POST" ? 2 : 1 }),
      };
    },
  );
  const host = createBridgeHost({
    localWindow: w.host,
    frameWindow: w.child,
    binding,
    presentation,
    capabilities: [],
    onBackendRequest: dispatch,
  });
  disposals.push(() => host.close());
  function BackendApp() {
    const { ready, request } = useAppBackend();
    const { presentation } = useAppPresentation();
    const [value, setValue] = useState(0);
    useEffect(() => {
      if (!ready) return;
      const abort = new AbortController();
      request({ method: "GET", path: "/v1/notes", body: "" }, abort.signal)
        .then((result) => {
          if (!abort.signal.aborted) setValue(JSON.parse(result.body).value);
        })
        .catch(() => {});
      return () => abort.abort();
    }, [ready, request]);
    return (
      <button
        disabled={!ready}
        onClick={() => {
          void request({
            method: "POST",
            path: "/v1/notes",
            body: '{"value":2}',
          }).then((result) => setValue(JSON.parse(result.body).value));
        }}
      >
        {presentation.locale}/{value}
      </button>
    );
  }
  render(
    <StrictMode>
      <AppRoot
        localWindow={w.child}
        parentWindow={w.host}
        parentOrigin="https://portal.example.invalid"
      >
        <BackendApp />
      </AppRoot>
    </StrictMode>,
  );
  await waitFor(() =>
    expect(screen.getByRole("button").textContent).toBe("zh-CN/1"),
  );
  expect(dispatch).toHaveBeenCalledExactlyOnceWith(
    { method: "GET", path: "/v1/notes", body: "" },
    expect.any(AbortSignal),
  );
  act(() => host.updatePresentation({ ...presentation, locale: "zh-TW" }));
  await waitFor(() =>
    expect(screen.getByRole("button").textContent).toBe("zh-TW/1"),
  );
  expect(dispatch).toHaveBeenCalledOnce();
  act(() => screen.getByRole("button").click());
  await waitFor(() =>
    expect(screen.getByRole("button").textContent).toBe("zh-TW/2"),
  );
  expect(dispatch).toHaveBeenCalledTimes(2);
});

test("draft hook aggregates forms, survives presentation changes and retires owners", async () => {
  const w = windows(),
    changes = vi.fn();
  const host = createBridgeHost({
    localWindow: w.host,
    frameWindow: w.child,
    binding,
    presentation,
    capabilities: [],
    onDraftChange: changes,
  });
  disposals.push(() => host.close());
  function Form({ name }: { name: string }) {
    const [dirty, setDirty] = useState(false);
    useAppDraft(dirty);
    return (
      <button onClick={() => setDirty((v) => !v)}>
        {name}/{String(dirty)}
      </button>
    );
  }
  function Forms() {
    const [second, setSecond] = useState(true);
    return (
      <>
        <Form name="first" />
        {second && <Form name="second" />}
        <button onClick={() => setSecond(false)}>Remove second</button>
      </>
    );
  }
  const view = render(
    <StrictMode>
      <AppRoot
        localWindow={w.child}
        parentWindow={w.host}
        parentOrigin="https://portal.example.invalid"
      >
        <Forms />
      </AppRoot>
    </StrictMode>,
  );
  await waitFor(() => expect(host.state()).toBe("ready"));
  await waitFor(() => expect(changes).toHaveBeenLastCalledWith(false));
  act(() => screen.getByRole("button", { name: "first/false" }).click());
  await waitFor(() => expect(changes).toHaveBeenLastCalledWith(true));
  act(() => screen.getByRole("button", { name: "second/false" }).click());
  act(() => screen.getByRole("button", { name: "first/true" }).click());
  act(() => host.updatePresentation({ ...presentation, locale: "zh-TW" }));
  await waitFor(() => expect(document.documentElement.lang).toBe("zh-TW"));
  await new Promise((resolve) => setTimeout(resolve, 150));
  expect(changes).toHaveBeenLastCalledWith(true);
  expect(screen.getByRole("button", { name: "second/true" })).toBeTruthy();
  act(() => screen.getByRole("button", { name: "Remove second" }).click());
  await waitFor(() => expect(changes).toHaveBeenLastCalledWith(false));
  view.unmount();
  const count = changes.mock.calls.length;
  await new Promise((resolve) => setTimeout(resolve, 150));
  expect(changes).toHaveBeenCalledTimes(count);
});

test("navigation hook follows host commits without replacing mounted form state", async () => {
  const w = windows(),
    requests = vi.fn();
  const routed = {
    ...presentation,
    navigation: {
      search: "",
      path: "/",
      routes: [
        { id: "home", path: "/", layout: "document" as const },
        { id: "details", path: "/details", layout: "document" as const },
      ],
    },
  };
  const host = createBridgeHost({
    localWindow: w.host,
    frameWindow: w.child,
    binding,
    presentation: routed,
    capabilities: [],
    onNavigate: requests,
  });
  disposals.push(() => host.close());
  function Routed() {
    const nav = useAppNavigation();
    const [count, setCount] = useState(0);
    return (
      <>
        <button onClick={() => setCount((n) => n + 1)}>Count {count}</button>
        <button onClick={() => nav.navigate("/details")}>{nav.path}</button>
      </>
    );
  }
  render(
    <AppRoot
      localWindow={w.child}
      parentWindow={w.host}
      parentOrigin="https://portal.example.invalid"
    >
      <Routed />
    </AppRoot>,
  );
  await waitFor(() => expect(host.state()).toBe("ready"));
  act(() => screen.getByRole("button", { name: "Count 0" }).click());
  act(() => screen.getByRole("button", { name: "/" }).click());
  await waitFor(() =>
    expect(requests).toHaveBeenCalledExactlyOnceWith("/details", false, ""),
  );
  expect(screen.getByRole("button", { name: "/" })).toBeTruthy();
  act(() =>
    host.updatePresentation({
      ...routed,
      navigation: { ...routed.navigation, path: "/details" },
    }),
  );
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "/details" })).toBeTruthy(),
  );
  expect(screen.getByRole("button", { name: "Count 1" })).toBeTruthy();
});

test("navigation query is typed only after the host commits canonical search", async () => {
  const w = windows(),
    requests = vi.fn();
  const routed = {
    ...presentation,
    navigation: {
      path: "/",
      search: "",
      routes: [
        {
          id: "home",
          path: "/",
          layout: "document" as const,
          query: [{ name: "page", type: "integer" as const, min: 1, max: 100 }],
        },
      ],
    },
  };
  const host = createBridgeHost({
    localWindow: w.host,
    frameWindow: w.child,
    binding,
    presentation: routed,
    capabilities: [],
    onNavigate: requests,
  });
  disposals.push(() => host.close());
  let observed: ReturnType<typeof useAppNavigation>["query"] | undefined;
  function QueryApp() {
    const nav = useAppNavigation();
    observed = nav.query;
    const [count, setCount] = useState(0);
    return (
      <>
        <span data-testid="query-value">{JSON.stringify(nav.query)}</span>
        <button
          onClick={() => {
            setCount((n) => n + 1);
            nav.navigate("/", { query: { page: 2 } });
          }}
        >
          Query {count}
        </button>
      </>
    );
  }
  render(
    <AppRoot
      localWindow={w.child}
      parentWindow={w.host}
      parentOrigin="https://portal.example.invalid"
    >
      <QueryApp />
    </AppRoot>,
  );
  await waitFor(() => expect(host.state()).toBe("ready"));
  act(() => screen.getByRole("button", { name: "Query 0" }).click());
  await waitFor(() =>
    expect(requests).toHaveBeenCalledExactlyOnceWith("/", false, "?page=2"),
  );
  expect(screen.getByTestId("query-value").textContent).toBe("{}");
  act(() =>
    host.updatePresentation({
      ...routed,
      navigation: { ...routed.navigation, search: "?page=2" },
    }),
  );
  await waitFor(() =>
    expect(screen.getByTestId("query-value").textContent).toBe('{"page":2}'),
  );
  expect(screen.getByRole("button", { name: "Query 1" })).toBeTruthy();
  const committed = observed;
  act(() =>
    host.updatePresentation({
      ...routed,
      locale: "zh-TW",
      navigation: { ...routed.navigation, search: "?page=2" },
    }),
  );
  await waitFor(() => expect(document.documentElement.lang).toBe("zh-TW"));
  expect(observed).toBe(committed);
});
