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
  type BridgeObjectRequest,
  type BridgeObjectSummary,
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

test("Notes creates, reopens and translates persisted objects through the SDK", async () => {
  vi.stubGlobal("MessageChannel", MessageChannel);
  const [parent, child] = windows();
  let state: PageActionSnapshot | null = null;
  const dirty = vi.fn();
  let persisted: (BridgeObjectSummary & { contentBase64: string }) | null =
    null;
  const dispatch = vi.fn(async (request: BridgeObjectRequest) => {
    if (request.action === "list") {
      if (!persisted) return { action: "list" as const, items: [] };
      const { contentBase64: _content, ...object } = persisted;
      return { action: "list" as const, items: [object] };
    }
    if (request.action === "get") {
      if (!persisted) throw new Error("missing");
      const { contentBase64, ...object } = persisted;
      return { action: "get" as const, object, contentBase64 };
    }
    if (request.action === "create") {
      persisted = {
        id: "00000000-0000-4000-8000-000000000042",
        collection: request.collection,
        label: request.label,
        mediaType: request.mediaType,
        sizeBytes: atob(request.contentBase64).length,
        revision: 1,
        createdAt: 1,
        updatedAt: 1,
        contentBase64: request.contentBase64,
      };
      const { contentBase64: _content, ...object } = persisted;
      return { action: "create" as const, object };
    }
    if (request.action === "update" && persisted) {
      persisted = {
        ...persisted,
        label: request.label,
        revision: persisted.revision + 1,
        contentBase64: request.contentBase64,
      };
      const { contentBase64: _content, ...object } = persisted;
      return { action: "update" as const, object };
    }
    if (request.action === "delete" && persisted) {
      persisted = null;
      return { action: "delete" as const, id: request.id };
    }
    throw new Error("unexpected request");
  });
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
      installationId: "00000000-0000-4000-8000-000000000001",
      generation: "1",
      policyRevision: "1",
      releaseSha256: "a".repeat(64),
    },
    capabilities: ["storage.files"],
    presentation,
    onObjectRequest: dispatch,
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

  await waitFor(() => expect(state?.page.title).toBe("Notes"));
  expect(screen.queryByRole("heading")).toBeNull();
  expect(screen.queryByRole("combobox")).toBeNull();
  await waitFor(() =>
    expect(
      state?.page.actions.find((action) => action.id === "new")?.disabled,
    ).toBe(false),
  );
  act(() => {
    expect(state!.invoke("new")).toBe(true);
  });
  const field = await screen.findByRole("textbox", { name: "Note" });
  fireEvent.change(field, {
    target: { value: "A retained draft\nSecond line" },
  });
  await waitFor(() => expect(dirty).toHaveBeenLastCalledWith(true));
  act(() => {
    presentation = { ...presentation, locale: "zh-CN" };
    host.updatePresentation(presentation);
  });
  await waitFor(() =>
    expect(screen.getByRole("textbox", { name: "笔记" })).toBeTruthy(),
  );
  expect((field as HTMLTextAreaElement).value).toBe(
    "A retained draft\nSecond line",
  );
  await act(async () => {
    expect(state!.invoke("save")).toBe(true);
    await waitFor(() =>
      expect(dispatch).toHaveBeenCalledWith(
        expect.objectContaining({ action: "create", collection: "note" }),
        expect.any(AbortSignal),
      ),
    );
  });
  await waitFor(() => expect(state?.page.title).toBe("笔记"));
  expect(await screen.findByText("A retained draft")).toBeTruthy();
  expect(persisted).not.toBeNull();
  await waitFor(() => expect(dirty).toHaveBeenLastCalledWith(false));

  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "打开" }));
    await waitFor(() =>
      expect(dispatch).toHaveBeenCalledWith(
        expect.objectContaining({ action: "get" }),
        expect.any(AbortSignal),
      ),
    );
  });
  await waitFor(() =>
    expect(
      (screen.getByRole("textbox", { name: "笔记" }) as HTMLTextAreaElement)
        .value,
    ).toBe("A retained draft\nSecond line"),
  );
});
