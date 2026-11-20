import { MessageChannel } from "node:worker_threads";
import { act, render } from "@testing-library/react";
import { expect, vi } from "vitest";
import { AppRoot } from "@portal-app/sdk/root-v2";
import {
  createBridgeHost,
  type BridgePresentation,
  type PageActionSnapshot,
} from "@portal-app/sdk/bridge-v2";
import { Application } from "../src/App";
import bootstrap from "../src/bootstrap.json";

export const close: Array<() => void> = [];

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

/** A non-2xx application reply. Plain values are 200 replies. */
export class Reply {
  constructor(
    readonly status: number,
    readonly body: unknown = { ok: false },
  ) {}
}

export type Handler = (
  method: string,
  path: string,
  body: unknown,
) => unknown | Promise<unknown>;

const routes = [
  { id: "overview", path: "/", layout: "document" as const },
  { id: "incidents", path: "/incidents", layout: "document" as const },
  { id: "manage", path: "/manage", layout: "document" as const },
];

export function defaults(admin: boolean, path: string): unknown {
  if (path === "/v1/me")
    return {
      admin,
      api_version: 1,
      capabilities: [
        "status.components.v1",
        "status.history.v2",
        "status.export.v1",
        "status.retention.v1",
        "status.postgres-unix.v1",
      ],
    };
  if (path === "/v1/manage/operations")
    return {
      settings: {
        public_enabled: false,
        probes_paused: true,
        outbox_paused: true,
        raw_retention_days: 30,
        history_retention_days: 90,
        portal_url: "",
        portal_networks: [],
      },
      queue_fingerprint: "empty",
      outbox: [],
      publishers: [],
    };
  return { items: [], total: 0 };
}

export function mount(
  options: { admin?: boolean; handler?: Handler; backend?: boolean } = {},
) {
  const admin = options.admin ?? true;
  vi.stubGlobal("MessageChannel", MessageChannel);
  const [parent, child] = windows();
  let state: PageActionSnapshot | null = null;
  let dirty = false;
  let presentation: BridgePresentation = {
    locale: "en-US",
    timeZone: "UTC",
    layout: "document",
    theme: {
      dark: false,
      colorPrimary: "#1677ff",
      colorBg: "#ffffff",
      colorText: "#000000",
      colorBorder: "#d9d9d9",
      colorBgLayout: "#f5f5f5",
      borderRadius: 8,
    },
    navigation: { path: "/", search: "", routes },
  };
  const calls: { method: string; path: string; body: unknown }[] = [];
  const backend = vi.fn(
    async (request: { method: string; path: string; body: string }) => {
      const body = request.body ? JSON.parse(request.body) : undefined;
      calls.push({ method: request.method, path: request.path, body });
      const custom = await options.handler?.(request.method, request.path, body);
      const value =
        custom === undefined ? defaults(admin, request.path) : custom;
      if (value instanceof Reply)
        return { status: value.status, body: JSON.stringify(value.body) };
      return { status: 200, body: JSON.stringify(value) };
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
    capabilities: ["background.run", "notifications.publish", "secrets.use", "tasks.schedule"],
    presentation,
    onPageChange: (value) => {
      state = value;
    },
    onDraftChange: (value) => {
      dirty = value;
    },
    onBackendRequest: options.backend === false ? undefined : backend,
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
  return {
    backend,
    calls,
    page: () => state,
    draftDirty: () => dirty,
    invoke(id: string) {
      act(() => {
        expect(state!.invoke(id)).toBe(true);
      });
    },
    setLocale(locale: BridgePresentation["locale"]) {
      act(() => {
        presentation = { ...presentation, locale };
        host.updatePresentation(presentation);
      });
    },
    actionIds: () => state?.page.actions.map((action) => action.id) ?? [],
  };
}
