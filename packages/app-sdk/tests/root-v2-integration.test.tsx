import { MessageChannel as NodeMessageChannel } from "node:worker_threads";
import { useState, StrictMode } from "react";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { createBridgeHost, type BridgePresentation } from "../src/bridge-v2";
import { AppRoot, useAppPresentation } from "../src/root-v2";
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
