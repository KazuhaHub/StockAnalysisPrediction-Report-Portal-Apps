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

test("the generated app uses host actions, retains a draft across locale updates and renders no duplicate header", async () => {
  vi.stubGlobal("MessageChannel", MessageChannel);
  const [parent, child] = windows();
  let state: PageActionSnapshot | null = null;
  const dirty = vi.fn();
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
        { id: "editor", path: "/editor", layout: "document" },
      ],
    },
  };
  const host = createBridgeHost({
    localWindow: parent,
    frameWindow: child,
    binding: {
      installationId: "00000000-0000-0000-0000-000000000001",
      generation: "1",
      policyRevision: "1",
      releaseSha256: "a".repeat(64),
    },
    capabilities: [],
    presentation,
    onPageChange: (value) => {
      state = value;
    },
    onDraftChange: dirty,
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
  await waitFor(() => expect(state?.page.title).toBe(APP_NAME_JSON));
  expect(screen.queryByRole("heading")).toBeNull();
  expect(screen.queryByRole("combobox")).toBeNull();
  await waitFor(() =>
    expect(
      state?.page.actions.find((action) => action.id === "editor")?.disabled,
    ).toBe(false),
  );
  act(() => {
    expect(state!.invoke("editor")).toBe(true);
  });
  const field = await screen.findByRole("textbox", { name: "Draft text" });
  await waitFor(() => expect(state?.page.title).toBe("Draft editor"));
  fireEvent.change(field, { target: { value: "A retained draft" } });
  await waitFor(() => expect(dirty).toHaveBeenLastCalledWith(true));
  act(() => {
    expect(state!.invoke("preview")).toBe(true);
  });
  expect(await screen.findByText("A retained draft")).toBeTruthy();
  act(() => {
    presentation = { ...presentation, locale: "zh-CN" };
    host.updatePresentation(presentation);
  });
  await waitFor(() => expect(state?.page.title).toBe("草稿编辑器"));
  expect(
    (screen.getByRole("textbox", { name: "草稿内容" }) as HTMLTextAreaElement)
      .value,
  ).toBe("A retained draft");
  expect(screen.getByRole("status", { name: "预览" }).textContent).toContain(
    "A retained draft",
  );
  expect(dirty).toHaveBeenLastCalledWith(true);
  expect(screen.queryByRole("heading")).toBeNull();
});
