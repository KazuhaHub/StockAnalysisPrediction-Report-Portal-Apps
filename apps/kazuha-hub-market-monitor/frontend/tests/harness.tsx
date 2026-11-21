import { MessageChannel } from "node:worker_threads";
import { act, cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, vi } from "vitest";
import { AppRoot } from "@portal-app/sdk/root-v2";
import {
  createBridgeHost,
  type BridgePresentation,
  type PageActionSnapshot,
} from "@portal-app/sdk/bridge-v2";
import { Application } from "../src/App";
import bootstrap from "../src/bootstrap.json";
import manifest from "../../app.v2.json";

export type Reply = { status: number; body: unknown };
export type Handler = (
  path: string,
  params: URLSearchParams,
) => Reply | Promise<Reply>;

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
    addEventListener: (_n: string, l: (event: MessageEvent) => void) =>
      listeners[index].add(l),
    removeEventListener: (_n: string, l: (event: MessageEvent) => void) =>
      listeners[index].delete(l),
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
      queueMicrotask(() => listeners[index].forEach((l) => l(event)));
    },
  }));
  return peers as unknown as [Window, Window];
}

/**
 * Mounts the app behind the SDK's bridge host with a scripted backend and
 * returns the recorded backend paths and the latest host page state.
 */
export async function mount(
  handler: Handler,
  options: { path?: string; locale?: BridgePresentation["locale"] } = {},
) {
  vi.stubGlobal("MessageChannel", MessageChannel);
  const [parent, child] = windows();
  const routes = manifest.presentation.routes.map((r) => ({
    id: r.id,
    path: r.path,
    layout: "document" as const,
  }));
  const calls: string[] = [];
  let page: PageActionSnapshot | null = null;
  let presentation: BridgePresentation = {
    locale: options.locale ?? "en-US",
    timeZone: "UTC",
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
    navigation: { path: options.path ?? "/", search: "", routes },
  };
  const backend = vi.fn(
    async (request: { method: string; path: string; body: string }) => {
      calls.push(request.path);
      const url = new URL(request.path, "http://backend.invalid");
      const reply = await handler(url.pathname, url.searchParams);
      return { status: reply.status, body: JSON.stringify(reply.body) };
    },
  );
  const host = createBridgeHost({
    localWindow: parent,
    frameWindow: child,
    binding: {
      installationId: "00000000-0000-0000-0000-000000000001",
      generation: "1",
      policyRevision: "1",
      releaseSha256: "b".repeat(64),
    },
    capabilities: ["background.run"],
    presentation,
    onPageChange: (value) => {
      page = value;
    },
    onBackendRequest: backend,
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
  await waitFor(() => expect(page).not.toBeNull());
  return {
    calls,
    page: () => page!,
    invoke: (id: string) =>
      act(() => {
        page!.invoke(id);
      }),
  };
}

import { expect } from "vitest";

export const ok = (body: unknown): Reply => ({ status: 200, body });
export const noData: Reply = { status: 404, body: { error: "no_data" } };
export const notFound: Reply = { status: 404, body: { error: "not_found" } };
