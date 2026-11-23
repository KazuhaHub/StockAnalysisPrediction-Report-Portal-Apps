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
import manifest from "../../app.v2.json";

export type Reply = { status: number; body: unknown };
export type Request = { method: string; path: string; body: string };
export type Handler = (
  path: string,
  params: URLSearchParams,
  request: Request,
) => Reply | Promise<Reply>;

const portalOrigin = "https://portal.example.invalid";
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
    location: {
      href: `${portalOrigin}${index === 1 ? "/app-documents/x/index.html" : "/"}`,
    },
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
        origin: index === 1 ? portalOrigin : "null",
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
  options: {
    path?: string;
    locale?: BridgePresentation["locale"];
    /** Launches the app's admin view: only the admin routes are listed. */
    surface?: "reader" | "admin";
  } = {},
) {
  vi.stubGlobal("MessageChannel", MessageChannel);
  const [parent, child] = windows();
  const admin = options.surface === "admin";
  const routes = (
    admin ? manifest.presentation.admin_routes : manifest.presentation.routes
  ).map((r) => ({
    id: r.id,
    path: r.path,
    layout: "document" as const,
  }));
  const calls: string[] = [];
  const requests: Request[] = [];
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
    navigation: {
      path: options.path ?? (admin ? "/admin" : "/"),
      search: "",
      routes,
    },
  };
  const backend = vi.fn(
    async (request: { method: string; path: string; body: string }) => {
      calls.push(request.path);
      requests.push(request);
      const url = new URL(request.path, "http://backend.invalid");
      const reply = await handler(url.pathname, url.searchParams, request);
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
    surface: options.surface,
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
    <AppRoot localWindow={child} parentWindow={parent}>
      <Application />
    </AppRoot>,
  );
  await waitFor(() => expect(page).not.toBeNull());
  return {
    calls,
    requests,
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
