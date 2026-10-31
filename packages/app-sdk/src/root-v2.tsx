// Experimental React root with bounded own-backend and reviewed network
// channels. No credential, ambient authority or legacy-protocol fallback is
// granted here.
import {
  Component,
  createContext,
  useContext,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  createBridgeClient,
  type BridgeContext,
  type BridgeFailure,
  type BridgePresentation,
  type BridgeRoute,
  type BridgeNavigationOptions,
  BridgeBackendError,
  BRIDGE_DOCUMENT_MAX_HEIGHT,
  type BridgeBackendRequest,
  type BridgeBackendResponse,
  AppNetworkError,
  encodeNetworkBody,
  decodeNetworkBody,
  type NetworkRequest as WireNetworkRequest,
  type NetworkResponse as WireNetworkResponse,
  BridgeReportError,
  type BridgeReportQuery,
  type BridgeReportRequest,
  type BridgeReportResponse,
  type BridgeReportSummary,
  type BridgeReportDetail,
  BridgeObjectError,
  type BridgeObjectRequest,
  type BridgeObjectResponse,
  type BridgeObjectSummary,
} from "./bridge-v2";
import { parseAppPage, type AppPage, type AppPageAction } from "./page-v2";
import { parseRouteSearch, type RouteQueryValues } from "./route-query-v2";
import { PortalAppProvider, type AppClient } from "./index";
import "./root-v2.css";
export { BridgeReportError } from "./bridge-v2";
export { BridgeObjectError } from "./bridge-v2";

export interface AppPresentation {
  readonly presentation: BridgePresentation;
  readonly context: BridgeContext;
}
const PresentationContext = createContext<AppPresentation | null>(null);
export interface AppBackend {
  readonly available: boolean;
  readonly ready: boolean;
  request(
    value: BridgeBackendRequest,
    signal?: AbortSignal,
  ): Promise<BridgeBackendResponse>;
}
const BackendContext = createContext<AppBackend | null>(null);
export function useAppBackend(): AppBackend {
  const value = useContext(BackendContext);
  if (!value) throw new Error("AppRoot backend unavailable");
  return value;
}
export interface AppNetworkRequest {
  readonly method: string;
  readonly url: string;
  readonly accept?: string;
  readonly contentType?: string;
  readonly body?: Uint8Array;
}
export interface AppNetworkResponse {
  readonly status: number;
  readonly contentType: string;
  readonly body: Uint8Array;
}
export interface AppNetwork {
  readonly available: boolean;
  readonly ready: boolean;
  request(
    value: AppNetworkRequest,
    signal?: AbortSignal,
  ): Promise<AppNetworkResponse>;
}
const NetworkContext = createContext<AppNetwork | null>(null);
export function useAppNetwork(): AppNetwork {
  const value = useContext(NetworkContext);
  if (!value) throw new Error("AppRoot network unavailable");
  return value;
}
export type AppReportQuery = BridgeReportQuery;
export type AppReportSummary = BridgeReportSummary;
export type AppReportDetail = BridgeReportDetail;
export type AppReportList = Extract<
  BridgeReportResponse,
  { readonly kind: "query" }
>;
export type AppReportDetailResult = Extract<
  BridgeReportResponse,
  { readonly kind: "get" }
>;
export interface AppReports {
  readonly available: boolean;
  readonly ready: boolean;
  query(query?: AppReportQuery, signal?: AbortSignal): Promise<AppReportList>;
  get(id: number, signal?: AbortSignal): Promise<AppReportDetailResult>;
}
const ReportsContext = createContext<AppReports | null>(null);
export function useAppReports(): AppReports {
  const value = useContext(ReportsContext);
  if (!value) throw new Error("AppRoot reports unavailable");
  return value;
}
export type AppObjectSummary = BridgeObjectSummary;
export interface AppObject extends AppObjectSummary {
  readonly content: Uint8Array;
}
export interface AppObjectList {
  readonly items: readonly AppObjectSummary[];
  readonly nextCursor?: string;
}
export interface AppObjectCreate {
  readonly requestId: string;
  readonly collection: string;
  readonly label: string;
  readonly mediaType: string;
  readonly content: Uint8Array;
}
export interface AppObjectUpdate {
  readonly expectedRevision: number;
  readonly label: string;
  readonly mediaType: string;
  readonly content: Uint8Array;
}
export interface AppObjects {
  readonly available: boolean;
  readonly ready: boolean;
  list(
    collection: string,
    cursor?: string,
    limit?: number,
    signal?: AbortSignal,
  ): Promise<AppObjectList>;
  get(id: string, signal?: AbortSignal): Promise<AppObject>;
  create(value: AppObjectCreate, signal?: AbortSignal): Promise<AppObjectSummary>;
  update(
    id: string,
    value: AppObjectUpdate,
    signal?: AbortSignal,
  ): Promise<AppObjectSummary>;
  delete(
    id: string,
    expectedRevision: number,
    signal?: AbortSignal,
  ): Promise<void>;
}
const ObjectsContext = createContext<AppObjects | null>(null);
export function useAppObjects(): AppObjects {
  const value = useContext(ObjectsContext);
  if (!value) throw new Error("AppRoot objects unavailable");
  return value;
}
export function useAppPresentation(): AppPresentation {
  const value = useContext(PresentationContext);
  if (!value) throw new Error("AppRoot presentation unavailable");
  return value;
}
export interface AppNavigation {
  readonly ready: boolean;
  readonly path: string | null;
  readonly search: string;
  readonly query: RouteQueryValues;
  readonly routes: readonly BridgeRoute[];
  navigate(path: string, options?: BridgeNavigationOptions): boolean;
}
const NavigationContext = createContext<AppNavigation | null>(null);
export function useAppNavigation(): AppNavigation {
  const value = useContext(NavigationContext);
  if (!value) throw new Error("AppRoot navigation unavailable");
  return value;
}
type DraftRegistry = (owner: symbol, dirty: boolean | undefined) => void;
const DraftContext = createContext<DraftRegistry | null>(null);
// Each mounted form owns one bit. No draft contents leave the app document.
export function useAppDraft(dirty: boolean): void {
  const register = useContext(DraftContext);
  const owner = useRef(Symbol("draft"));
  if (!register) throw new Error("AppRoot draft registry unavailable");
  useLayoutEffect(() => {
    if (typeof dirty !== "boolean")
      throw new Error("Draft state must be boolean");
    register(owner.current, dirty);
    return () => register(owner.current, undefined);
  }, [register, dirty]);
}
export interface AppPageOptions {
  readonly title?: string;
  readonly description?: string;
  readonly actions?: readonly (Pick<AppPageAction, "id" | "label"> &
    Partial<Pick<AppPageAction, "variant" | "disabled" | "loading">> & {
      onAction(signal: AbortSignal): void | Promise<void>;
    })[];
}
type PageRegistry = (owner: symbol, value: AppPageOptions | undefined) => void;
const PageContext = createContext<PageRegistry | null>(null);
export function useAppPage(value: AppPageOptions): void {
  const register = useContext(PageContext),
    owner = useRef(Symbol("page"));
  if (!register) throw new Error("AppRoot page registry unavailable");
  useLayoutEffect(() => {
    register(owner.current, value);
  });
  useLayoutEffect(() => () => register(owner.current, undefined), [register]);
}
interface Pending extends AppPresentation {
  describePage(
    scope: string,
    page: AppPage | null,
    handler?: (id: string, signal: AbortSignal) => void | Promise<void>,
  ): boolean;
  navigate(path: string, options?: BridgeNavigationOptions): boolean;
  setDraftDirty(dirty: boolean): boolean;
  measureDocument(height: number): boolean;
  requestBackend(
    value: BridgeBackendRequest,
    signal?: AbortSignal,
  ): Promise<BridgeBackendResponse>;
  requestNetwork(
    value: WireNetworkRequest,
    signal?: AbortSignal,
  ): Promise<WireNetworkResponse>;
  requestReports(
    value: BridgeReportRequest,
    signal?: AbortSignal,
  ): Promise<BridgeReportResponse>;
  requestObjects(
    value: BridgeObjectRequest,
    signal?: AbortSignal,
  ): Promise<BridgeObjectResponse>;
  resolve(): void;
  reject(): void;
  signal: AbortSignal;
  dispose(): void;
}
class RenderBoundary extends Component<
  { children: ReactNode; onFailure(): void },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch() {
    this.props.onFailure();
  }
  render() {
    return this.state.failed ? null : this.props.children;
  }
}
// This marker lives inside the error boundary, after the app subtree. A failed
// render cannot acknowledge an uncommitted presentation or expose exception text.
function Commit({ pending }: { pending: Pending }) {
  useLayoutEffect(() => {
    if (pending.signal.aborted) return;
    document.documentElement.lang = pending.presentation.locale;
    document.documentElement.style.colorScheme = pending.presentation.theme.dark
      ? "dark"
      : "light";
    document.body.style.background = pending.presentation.theme.colorBgLayout;
    document.body.style.color = pending.presentation.theme.colorText;
    pending.resolve();
  }, [pending]);
  return null;
}
const failureText = {
  "en-US": "App connection interrupted. Please reopen the app.",
  "zh-CN": "应用连接已中断，请重新打开。",
  "zh-TW": "應用程式連線已中斷，請重新開啟。",
};
export interface AppRootProps {
  parentOrigin: string;
  localWindow?: Window;
  parentWindow?: Window;
  children: ReactNode;
  onFailure?: (code: BridgeFailure) => void;
}
// parentOrigin must come from trusted immutable bootstrap configuration. The
// caller must mount this once per sandbox document, never infer origin from an
// arbitrary message/referrer. The host must keep its loading cover until ready.
export function AppRoot({
  parentOrigin,
  localWindow = window,
  parentWindow = window.parent,
  children,
  onFailure,
}: AppRootProps) {
  const [pending, setPending] = useState<Pending | null>(null);
  const [failed, setFailed] = useState(false);
  const [backendReady, setBackendReady] = useState(false);
  const [epoch, setEpoch] = useState(0);
  const current = useRef<Pending | null>(null);
  const locale = useRef<BridgePresentation["locale"]>("en-US");
  const report = useRef(onFailure);
  report.current = onFailure;
  const fail = useRef<() => void>(() => {});
  useLayoutEffect(() => {
    let active = true;
    let stopped = false;
    let connection: ReturnType<typeof createBridgeClient> | undefined;
    let backendForSignal:
      | {
          signal: AbortSignal;
          page: Pending["describePage"];
          request: AppBackend["request"];
          requestNetwork: (
            value: WireNetworkRequest,
            signal?: AbortSignal,
          ) => Promise<WireNetworkResponse>;
          requestReports: (
            value: BridgeReportRequest,
            signal?: AbortSignal,
          ) => Promise<BridgeReportResponse>;
          requestObjects: (
            value: BridgeObjectRequest,
            signal?: AbortSignal,
          ) => Promise<BridgeObjectResponse>;
          draft(dirty: boolean): boolean;
          navigate(path: string, options?: BridgeNavigationOptions): boolean;
        }
      | undefined;
    let closed = false;
    const closeConnection = () => {
      if (connection && !closed) {
        closed = true;
        connection.close();
      }
    };
    const discard = (resetBackend = true) => {
      if (resetBackend) setBackendReady(false);
      current.current?.reject();
      current.current?.dispose();
      current.current = null;
      setPending(null);
    };
    const failure = (code: BridgeFailure) => {
      if (!active || stopped) return;
      stopped = true;
      discard();
      // Let a pending apply rejection report its bounded protocol failure first.
      // Render errors after ready still close the local presentation channel.
      queueMicrotask(() => {
        if (active) closeConnection();
      });
      setFailed(true);
      try {
        report.current?.(code);
      } catch {
        /* A user observer cannot retain a failed app subtree. */
      }
    };
    fail.current = () => failure("presentation_failed");
    setFailed(false);
    discard();
    setEpoch((value) => value + 1);
    connection = createBridgeClient({
      localWindow,
      parentWindow,
      parentOrigin,
      onPresentation: (presentation, context, signal) =>
        new Promise<void>((resolve, reject) => {
          if (!active || stopped || signal.aborted) {
            reject(new Error("Presentation cancelled"));
            return;
          }
          discard(false);
          locale.current = presentation.locale;
          if (backendForSignal?.signal !== signal) {
            backendForSignal = {
              signal,
              page: (scope, page, handler) =>
                !!(
                  active &&
                  !stopped &&
                  !signal.aborted &&
                  connection?.describePage(scope, page, handler)
                ),
              navigate: (path, options) =>
                !!(
                  active &&
                  !stopped &&
                  !signal.aborted &&
                  connection?.navigate(path, options)
                ),
              draft: (dirty) =>
                !!(
                  active &&
                  !stopped &&
                  !signal.aborted &&
                  connection?.setDraftDirty(dirty)
                ),
              request: (value, requestSignal) => {
                if (!active || stopped || !connection || signal.aborted)
                  return Promise.reject(new BridgeBackendError("not_ready"));
                return connection.requestBackend(
                  value,
                  requestSignal
                    ? AbortSignal.any([signal, requestSignal])
                    : signal,
                );
              },
              requestNetwork: (value, requestSignal) => {
                if (!active || stopped || !connection || signal.aborted)
                  return Promise.reject(new AppNetworkError("not_ready"));
                return connection.requestNetwork(
                  value,
                  requestSignal
                    ? AbortSignal.any([signal, requestSignal])
                    : signal,
                );
              },
              requestReports: (value, requestSignal) => {
                if (!active || stopped || !connection || signal.aborted)
                  return Promise.reject(new BridgeReportError("not_ready"));
                return connection.requestReports(
                  value,
                  requestSignal
                    ? AbortSignal.any([signal, requestSignal])
                    : signal,
                );
              },
              requestObjects: (value, requestSignal) => {
                if (!active || stopped || !connection || signal.aborted)
                  return Promise.reject(new BridgeObjectError("not_ready"));
                return connection.requestObjects(
                  value,
                  requestSignal
                    ? AbortSignal.any([signal, requestSignal])
                    : signal,
                );
              },
            };
          }
          let settled = false;
          const abort = () => {
            if (!settled) {
              settled = true;
              reject(new Error("Presentation cancelled"));
            }
            if (active && current.current === next) {
              current.current = null;
              setPending(null);
            }
          };
          const next: Pending = {
            presentation,
            context,
            signal,
            measureDocument: (height) =>
              !!(
                active &&
                !stopped &&
                !signal.aborted &&
                connection?.reportDocumentHeight(height)
              ),
            describePage: backendForSignal.page,
            requestBackend: backendForSignal.request,
            requestNetwork: backendForSignal.requestNetwork,
            requestReports: backendForSignal.requestReports,
            requestObjects: backendForSignal.requestObjects,
            setDraftDirty: backendForSignal.draft,
            navigate: backendForSignal.navigate,
            resolve: () => {
              if (settled || signal.aborted) return;
              settled = true;
              resolve();
            },
            reject: () => {
              if (!settled) {
                settled = true;
                reject(new Error("Presentation cancelled"));
              }
            },
            dispose: () => signal.removeEventListener("abort", abort),
          };
          signal.addEventListener("abort", abort, { once: true });
          current.current = next;
          setPending(next);
        }),
      onReset: () => {
        if (active) {
          discard();
          setFailed(false);
          setEpoch((value) => value + 1);
        }
      },
      onFailure: failure,
      onReady: () => {
        if (active && !stopped) setBackendReady(true);
      },
    });
    return () => {
      active = false;
      closeConnection();
      current.current?.reject();
      current.current?.dispose();
      current.current = null;
    };
  }, [parentOrigin, localWindow, parentWindow]);
  if (failed) return <div role="alert">{failureText[locale.current]}</div>;
  if (!pending) return null;
  return (
    <PresentationFrame
      pending={pending}
      backendReady={backendReady}
      epoch={epoch}
      onFailure={() => fail.current()}
    >
      {children}
    </PresentationFrame>
  );
}
function PresentationFrame({
  pending,
  backendReady,
  epoch,
  onFailure,
  children,
}: {
  pending: Pending;
  backendReady: boolean;
  epoch: number;
  onFailure(): void;
  children: ReactNode;
}) {
  const pagePath = pending.presentation.navigation?.path,
    pageSearch = pending.presentation.navigation?.search;
  const pageRegistry = useMemo(() => {
    const lifetime = { active: true };
    let lastOwner: symbol | undefined;
    let currentOwner: symbol | undefined,
      scope = "";
    let handlers = new Map<
      string,
      (signal: AbortSignal) => void | Promise<void>
    >();
    const register: PageRegistry = (owner, value) => {
      if (pending.signal.aborted) return;
      if (value === undefined) {
        if (currentOwner !== owner) return;
        currentOwner = undefined;
        handlers.clear();
        const removedScope = scope;
        queueMicrotask(() => {
          if (
            lifetime.active &&
            currentOwner === undefined &&
            scope === removedScope &&
            !pending.signal.aborted
          )
            pending.describePage(removedScope, null);
        });
        return;
      }
      if (currentOwner !== undefined && currentOwner !== owner)
        throw new Error("Only one page descriptor may be mounted");
      if (
        !value ||
        typeof value !== "object" ||
        Array.isArray(value) ||
        Object.keys(value).some(
          (key) => !["title", "description", "actions"].includes(key),
        )
      )
        throw new Error("Invalid page descriptor");
      const nextHandlers = new Map<
        string,
        (signal: AbortSignal) => void | Promise<void>
      >();
      const page = parseAppPage({
        title: value.title ?? "",
        description: value.description ?? "",
        actions: (value.actions ?? []).map((action) => {
          if (
            !action ||
            typeof action !== "object" ||
            Object.keys(action).some(
              (key) =>
                ![
                  "id",
                  "label",
                  "variant",
                  "disabled",
                  "loading",
                  "onAction",
                ].includes(key),
            ) ||
            typeof action.onAction !== "function"
          )
            throw new Error("Invalid page action");
          nextHandlers.set(action.id, action.onAction);
          return {
            id: action.id,
            label: action.label,
            variant: action.variant ?? "default",
            disabled: action.disabled ?? false,
            loading: action.loading ?? false,
          };
        }),
      });
      if (!page) throw new Error("Invalid page descriptor");
      if (lastOwner !== owner) {
        lastOwner = owner;
        const bytes = crypto.getRandomValues(new Uint8Array(16));
        scope = Array.from(bytes, (byte) =>
          byte.toString(16).padStart(2, "0"),
        ).join("");
      }
      currentOwner = owner;
      handlers = nextHandlers;
      pending.describePage(scope, page, (id, signal) => {
        const handler = handlers.get(id);
        if (
          currentOwner !== owner ||
          !handler ||
          pending.signal.aborted ||
          signal.aborted
        )
          throw new Error("Page action unavailable");
        return handler(signal);
      });
    };
    return { register, lifetime };
  }, [pending.signal, pending.describePage, pagePath, pageSearch]);
  useLayoutEffect(() => {
    pageRegistry.lifetime.active = true;
    return () => {
      pageRegistry.lifetime.active = false;
    };
  }, [pageRegistry]);
  const element = useRef<HTMLDivElement>(null);
  const draft = useMemo(() => {
    const owners = new Map<symbol, boolean>();
    const state = {
      ready: false,
      emit: () => {
        if (state.ready && !pending.signal.aborted)
          pending.setDraftDirty([...owners.values()].some(Boolean));
      },
      register: (owner: symbol, dirty: boolean | undefined) => {
        if (dirty === undefined) owners.delete(owner);
        else owners.set(owner, dirty);
        state.emit();
      },
    };
    return state;
  }, [pending.signal, pending.setDraftDirty]);
  useLayoutEffect(() => {
    draft.ready = backendReady;
    draft.emit();
    return () => {
      draft.ready = false;
    };
  }, [draft, backendReady]);
  useLayoutEffect(() => {
    const root = element.current;
    if (!root || !backendReady || pending.presentation.layout !== "document")
      return;
    let active = true,
      scheduled: ReturnType<typeof setTimeout> | undefined;
    const schedule = () => {
      if (!active || pending.signal.aborted || scheduled !== undefined) return;
      scheduled = setTimeout(() => {
        scheduled = undefined;
        if (!active || pending.signal.aborted) return;
        const height = Math.ceil(root.getBoundingClientRect().height);
        if (
          !Number.isFinite(height) ||
          height < 0 ||
          height > BRIDGE_DOCUMENT_MAX_HEIGHT
        ) {
          onFailure();
          return;
        }
        pending.measureDocument(height);
      }, 16);
    };
    const observer =
      typeof ResizeObserver === "undefined"
        ? null
        : new ResizeObserver(schedule);
    const fallback = observer ? null : new MutationObserver(schedule);
    observer?.observe(root);
    fallback?.observe(root, {
      childList: true,
      subtree: true,
      attributes: true,
      characterData: true,
    });
    window.addEventListener("resize", schedule);
    schedule();
    return () => {
      active = false;
      clearTimeout(scheduled);
      observer?.disconnect();
      fallback?.disconnect();
      window.removeEventListener("resize", schedule);
    };
  }, [pending, backendReady, onFailure]);
  // Reuse the existing Ant/token foundation without constructing the legacy
  // bridge. This adapter has no request transport and is never exposed to apps.
  const client = useMemo<AppClient>(
    () => ({
      getTheme: () => pending.presentation.theme,
      request: async () => {
        throw new Error("No request transport");
      },
      directory: async () => {
        throw new Error("No directory transport");
      },
    }),
    [pending.presentation.theme],
  );
  const value = useMemo(
    () =>
      Object.freeze({
        presentation: pending.presentation,
        context: pending.context,
      }),
    [pending.presentation, pending.context],
  );
  const backend = useMemo<AppBackend>(
    () =>
      Object.freeze({
        available: pending.context.backendAvailable,
        ready: backendReady && pending.context.backendAvailable,
        request: pending.requestBackend,
      }),
    [pending, backendReady],
  );
  const networkAvailable =
    pending.context.capabilities.includes("network.http");
  const network = useMemo<AppNetwork>(
    () => {
      return Object.freeze({
        available: networkAvailable,
        ready: backendReady && networkAvailable,
        request: async (
          value: AppNetworkRequest,
          signal?: AbortSignal,
        ) => {
          if (!networkAvailable) throw new AppNetworkError("unsupported");
          if (!backendReady || pending.signal.aborted)
            throw new AppNetworkError("not_ready");
          if (value.body !== undefined && !(value.body instanceof Uint8Array))
            throw new AppNetworkError("invalid_request");
          const body = value.body ?? new Uint8Array();
          const response = await pending.requestNetwork(
            {
              method: value.method,
              url: value.url,
              accept: value.accept ?? "application/json",
              contentType:
                value.contentType ??
                (body.byteLength > 0 ? "application/octet-stream" : ""),
              bodyBase64: encodeNetworkBody(body),
            },
            signal,
          );
          return Object.freeze({
            status: response.status,
            contentType: response.contentType,
            body: decodeNetworkBody(response.bodyBase64),
          });
        },
      });
    },
    [networkAvailable, backendReady, pending.requestNetwork, pending.signal],
  );
  const reportsAvailable =
    pending.context.capabilities.includes("reports.read");
  const reports = useMemo<AppReports>(
    () =>
      Object.freeze({
        available: reportsAvailable,
        ready: backendReady && reportsAvailable,
        query: (
          query: AppReportQuery = {},
          signal?: AbortSignal,
        ): Promise<AppReportList> => {
          if (!reportsAvailable)
            return Promise.reject(new BridgeReportError("unsupported"));
          if (!backendReady || pending.signal.aborted)
            return Promise.reject(new BridgeReportError("not_ready"));
          return pending.requestReports(
            { kind: "query", query },
            signal,
          ) as Promise<AppReportList>;
        },
        get: (
          id: number,
          signal?: AbortSignal,
        ): Promise<AppReportDetailResult> => {
          if (!reportsAvailable)
            return Promise.reject(new BridgeReportError("unsupported"));
          if (!backendReady || pending.signal.aborted)
            return Promise.reject(new BridgeReportError("not_ready"));
          return pending.requestReports(
            { kind: "get", id },
            signal,
          ) as Promise<AppReportDetailResult>;
        },
      }),
    [reportsAvailable, backendReady, pending.requestReports, pending.signal],
  );
  const objectsAvailable =
    pending.context.capabilities.includes("storage.files");
  const objects = useMemo<AppObjects>(
    () =>
      Object.freeze({
        available: objectsAvailable,
        ready: backendReady && objectsAvailable,
        list: (
          collection: string,
          cursor?: string,
          limit?: number,
          signal?: AbortSignal,
        ): Promise<AppObjectList> => {
          if (!objectsAvailable)
            return Promise.reject(new BridgeObjectError("unsupported"));
          if (!backendReady || pending.signal.aborted)
            return Promise.reject(new BridgeObjectError("not_ready"));
          return pending
            .requestObjects(
              {
                action: "list",
                collection,
                ...(cursor === undefined ? {} : { cursor }),
                ...(limit === undefined ? {} : { limit }),
              },
              signal,
            )
            .then((result) =>
              result.action === "list"
                ? {
                    items: result.items,
                    ...(result.nextCursor === undefined
                      ? {}
                      : { nextCursor: result.nextCursor }),
                  }
                : Promise.reject(new BridgeObjectError("uncertain")),
            );
        },
        get: (id: string, signal?: AbortSignal): Promise<AppObject> => {
          if (!objectsAvailable)
            return Promise.reject(new BridgeObjectError("unsupported"));
          if (!backendReady || pending.signal.aborted)
            return Promise.reject(new BridgeObjectError("not_ready"));
          return pending
            .requestObjects({ action: "get", id }, signal)
            .then((result) => {
              if (result.action !== "get")
                return Promise.reject(new BridgeObjectError("uncertain"));
              try {
                return {
                  ...result.object,
                  content: decodeNetworkBody(result.contentBase64),
                };
              } catch {
                return Promise.reject(new BridgeObjectError("uncertain"));
              }
            });
        },
        create: (
          value: AppObjectCreate,
          signal?: AbortSignal,
        ): Promise<AppObjectSummary> => {
          if (!objectsAvailable)
            return Promise.reject(new BridgeObjectError("unsupported"));
          if (!backendReady || pending.signal.aborted)
            return Promise.reject(new BridgeObjectError("not_ready"));
          if (
            !(value.content instanceof Uint8Array) &&
            Object.prototype.toString.call(value.content) !==
              "[object Uint8Array]"
          )
            return Promise.reject(new BridgeObjectError("invalid_request"));
          let contentBase64: string;
          try {
            contentBase64 = encodeNetworkBody(
              value.content instanceof Uint8Array
                ? value.content
                : new Uint8Array(value.content),
            );
          } catch {
            return Promise.reject(new BridgeObjectError("invalid_request"));
          }
          return pending
            .requestObjects(
              {
                action: "create",
                requestId: value.requestId,
                collection: value.collection,
                label: value.label,
                mediaType: value.mediaType,
                contentBase64,
              },
              signal,
            )
            .then((result) =>
              result.action === "create"
                ? result.object
                : Promise.reject(new BridgeObjectError("uncertain")),
            );
        },
        update: (
          id: string,
          value: AppObjectUpdate,
          signal?: AbortSignal,
        ): Promise<AppObjectSummary> => {
          if (!objectsAvailable)
            return Promise.reject(new BridgeObjectError("unsupported"));
          if (!backendReady || pending.signal.aborted)
            return Promise.reject(new BridgeObjectError("not_ready"));
          if (
            !(value.content instanceof Uint8Array) &&
            Object.prototype.toString.call(value.content) !==
              "[object Uint8Array]"
          )
            return Promise.reject(new BridgeObjectError("invalid_request"));
          let contentBase64: string;
          try {
            contentBase64 = encodeNetworkBody(
              value.content instanceof Uint8Array
                ? value.content
                : new Uint8Array(value.content),
            );
          } catch {
            return Promise.reject(new BridgeObjectError("invalid_request"));
          }
          return pending
            .requestObjects(
              {
                action: "update",
                id,
                expectedRevision: value.expectedRevision,
                label: value.label,
                mediaType: value.mediaType,
                contentBase64,
              },
              signal,
            )
            .then((result) =>
              result.action === "update"
                ? result.object
                : Promise.reject(new BridgeObjectError("uncertain")),
            );
        },
        delete: (
          id: string,
          expectedRevision: number,
          signal?: AbortSignal,
        ): Promise<void> => {
          if (!objectsAvailable)
            return Promise.reject(new BridgeObjectError("unsupported"));
          if (!backendReady || pending.signal.aborted)
            return Promise.reject(new BridgeObjectError("not_ready"));
          return pending
            .requestObjects(
              { action: "delete", id, expectedRevision },
              signal,
            )
            .then((result) =>
              result.action === "delete"
                ? undefined
                : Promise.reject(new BridgeObjectError("uncertain")),
            );
        },
      }),
    [objectsAvailable, backendReady, pending.requestObjects, pending.signal],
  );
  // Cache query values by signed definition/search and document lifetime, so
  // appearance updates do not look like a filter change to data-loading effects.
  const querySource = JSON.stringify([
    pending.presentation.navigation?.routes.find(
      (route) => route.path === pending.presentation.navigation?.path,
    )?.query ?? [],
    pending.presentation.navigation?.search ?? "",
  ]);
  const query = useMemo<RouteQueryValues>(() => {
    if (pending.signal.aborted) return Object.freeze({});
    const [rules, search] = JSON.parse(querySource) as [
      Parameters<typeof parseRouteSearch>[0],
      string,
    ];
    return parseRouteSearch(rules, search)!.query;
  }, [querySource, pending.signal]);
  const navigation = useMemo<AppNavigation>(
    () =>
      Object.freeze({
        ready: backendReady && !!pending.presentation.navigation,
        path: pending.presentation.navigation?.path ?? null,
        search: pending.presentation.navigation?.search ?? "",
        query,
        routes: pending.presentation.navigation?.routes ?? Object.freeze([]),
        navigate: pending.navigate,
      }),
    [backendReady, pending, query],
  );
  return (
    <div
      ref={element}
      className="portal-v2-root"
      data-app-layout={pending.presentation.layout}
    >
      <PortalAppProvider client={client} locale={pending.presentation.locale}>
        <PresentationContext.Provider value={value}>
          <BackendContext.Provider value={backend}>
            <NetworkContext.Provider value={network}>
              <ReportsContext.Provider value={reports}>
                <ObjectsContext.Provider value={objects}>
                  <NavigationContext.Provider value={navigation}>
                    <DraftContext.Provider value={draft.register}>
                      <PageContext.Provider value={pageRegistry.register}>
                        <RenderBoundary key={epoch} onFailure={onFailure}>
                          {children}
                          <Commit pending={pending} />
                        </RenderBoundary>
                      </PageContext.Provider>
                    </DraftContext.Provider>
                  </NavigationContext.Provider>
                </ObjectsContext.Provider>
              </ReportsContext.Provider>
            </NetworkContext.Provider>
          </BackendContext.Provider>
        </PresentationContext.Provider>
      </PortalAppProvider>
    </div>
  );
}
