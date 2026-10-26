import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { useState } from "react";
import { Empty, theme } from "antd";
import type { BridgePresentation, BridgeClientOptions } from "../src/bridge-v2";
import { AppRoot, useAppPresentation } from "../src/root-v2";

const control = vi.hoisted(() => ({
  options: null as BridgeClientOptions | null,
  close: vi.fn(),
}));
vi.mock("../src/bridge-v2", () => ({
  createBridgeClient: (options: BridgeClientOptions) => {
    control.options = options;
    return { close: control.close };
  },
}));
const presentation = {
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
} as const;
const context = {
  binding: {
    installationId: "00000000-0000-0000-0000-000000000001",
    generation: "9007199254740993",
    policyRevision: "1",
    releaseSha256: "a".repeat(64),
  },
  capabilities: [],
};
beforeEach(() => {
  control.close.mockClear();
  control.options = null;
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
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
function Probe() {
  const { presentation, context } = useAppPresentation();
  return (
    <span>
      {presentation.locale}/{presentation.timeZone}/{context.binding.generation}
    </span>
  );
}
function mount() {
  return render(
    <AppRoot parentOrigin="https://portal.example.invalid">
      <Probe />
    </AppRoot>,
  );
}
async function apply(value: BridgePresentation = presentation) {
  const abort = new AbortController();
  let settled = false;
  let promise: Promise<void>;
  act(() => {
    promise = Promise.resolve(
      control.options!.onPresentation(value, context, abort.signal),
    );
    promise.then(() => {
      settled = true;
    });
    expect(settled).toBe(false);
  });
  await act(async () => {
    await promise!;
  });
  return abort;
}
test("no application content before initialization; settings commit before acknowledgement", async () => {
  const view = mount();
  expect(view.container.textContent).toBe("");
  await apply();
  expect(document.documentElement.lang).toBe("zh-CN");
  expect(document.documentElement.style.colorScheme).toBe("dark");
  expect(document.body.style.backgroundColor).toBe("rgb(0, 0, 0)");
  expect(screen.getByText("zh-CN/Asia/Shanghai/9007199254740993")).toBeTruthy();
  expect(
    view.container.firstElementChild?.getAttribute("data-app-layout"),
  ).toBe("document");
});
test("live locale, timezone and layout updates preserve mounted app state", async () => {
  function App() {
    const [count, setCount] = useState(0);
    const value = useAppPresentation();
    return (
      <button onClick={() => setCount((n) => n + 1)}>
        {value.presentation.locale}/{count}
      </button>
    );
  }
  const view = render(
    <AppRoot parentOrigin="https://portal.example.invalid">
      <App />
    </AppRoot>,
  );
  await apply();
  screen.getByRole("button").click();
  await apply({
    ...presentation,
    locale: "zh-TW",
    timeZone: "Asia/Taipei",
    layout: "viewport",
  });
  expect(screen.getByRole("button").textContent).toBe("zh-TW/1");
  expect(document.documentElement.lang).toBe("zh-TW");
  expect(
    view.container.firstElementChild?.getAttribute("data-app-layout"),
  ).toBe("viewport");
});
test("reset removes stale content and an aborted apply never completes old work", async () => {
  const view = mount();
  await apply();
  act(() => control.options!.onReset?.());
  expect(view.container.textContent).toBe("");
  const abort = new AbortController();
  abort.abort();
  let rejected: Promise<void>;
  act(() => {
    rejected = Promise.resolve(
      control.options!.onPresentation(presentation, context, abort.signal),
    );
  });
  await expect(rejected!).rejects.toThrow();
  expect(view.container.textContent).toBe("");
});
test("failure removes app content, exposes only localized fixed text, and unmount closes bridge", async () => {
  const view = mount();
  await apply();
  act(() => control.options!.onFailure?.("transport_error"));
  expect(screen.queryByText("zh-CN/Asia/Shanghai/9007199254740993")).toBeNull();
  expect(screen.getByRole("alert").textContent).toBe(
    "应用连接已中断，请重新打开。",
  );
  view.unmount();
  expect(control.close).toHaveBeenCalledTimes(1);
});
test("render failure refuses the pending acknowledgement and hides private exception text", async () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  function Broken(): never {
    throw new Error("private detail");
  }
  const view = render(
    <AppRoot parentOrigin="https://portal.example.invalid">
      <Broken />
    </AppRoot>,
  );
  let promise: Promise<void>;
  act(() => {
    promise = Promise.resolve(
      control.options!.onPresentation(
        presentation,
        context,
        new AbortController().signal,
      ),
    );
    promise.catch(() => {});
  });
  await expect(promise!).rejects.toThrow();
  expect(view.container.textContent).not.toContain("private detail");
  expect(screen.getByRole("alert")).toBeTruthy();
  vi.restoreAllMocks();
});

test("Ant locale and tokens follow Portal directly, without a second language selector", async () => {
  function AntProbe() {
    const { token } = theme.useToken();
    return (
      <>
        <Empty />
        <span>{token.colorBgContainer}</span>
      </>
    );
  }
  render(
    <AppRoot parentOrigin="https://portal.example.invalid">
      <AntProbe />
    </AppRoot>,
  );
  await apply();
  expect(
    screen.getByText("暂无数据", { selector: ".ant-empty-description" }),
  ).toBeTruthy();
  expect(screen.getByText("#141414")).toBeTruthy();
  expect(screen.queryByRole("combobox")).toBeNull();
  await apply({
    ...presentation,
    locale: "en-US",
    theme: {
      ...presentation.theme,
      dark: false,
      colorBg: "#ffffff",
      colorBgLayout: "#ffffff",
      colorText: "#000000",
    },
  });
  expect(
    screen.getByText("No data", { selector: ".ant-empty-description" }),
  ).toBeTruthy();
  expect(document.documentElement.style.colorScheme).toBe("light");
  expect(document.body.style.backgroundColor).toBe("rgb(255, 255, 255)");
});

test("a locally failed root cannot be revived by a later presentation callback", async () => {
  const report = vi.fn();
  render(
    <AppRoot parentOrigin="https://portal.example.invalid" onFailure={report}>
      <Probe />
    </AppRoot>,
  );
  await apply();
  act(() => control.options!.onFailure?.("transport_error"));
  let promise: Promise<void>;
  act(() => {
    promise = Promise.resolve(
      control.options!.onPresentation(
        presentation,
        context,
        new AbortController().signal,
      ),
    );
  });
  await expect(promise!).rejects.toThrow();
  act(() => control.options!.onFailure?.("transport_error"));
  expect(report).toHaveBeenCalledTimes(1);
  expect(screen.queryByText("zh-CN/Asia/Shanghai/9007199254740993")).toBeNull();
});

test("abort before React commits rejects pending work and never mounts old content", async () => {
  const view = mount();
  const abort = new AbortController();
  let promise: Promise<void>;
  act(() => {
    promise = Promise.resolve(
      control.options!.onPresentation(presentation, context, abort.signal),
    );
    promise.catch(() => {});
    abort.abort();
  });
  await expect(promise!).rejects.toThrow();
  expect(view.container.textContent).toBe("");
});
