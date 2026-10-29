// Experimental React root with a bounded own-backend channel. No credential,
// generic network authority or legacy-protocol fallback is granted here.
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
} from "./bridge-v2";
import { parseRouteSearch, type RouteQueryValues } from "./route-query-v2";
import { PortalAppProvider, type AppClient } from "./index";
import "./root-v2.css";

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
interface Pending extends AppPresentation {
  navigate(path: string, options?: BridgeNavigationOptions): boolean;
  setDraftDirty(dirty: boolean): boolean;
  measureDocument(height: number): boolean;
  requestBackend(
    value: BridgeBackendRequest,
    signal?: AbortSignal,
  ): Promise<BridgeBackendResponse>;
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
          request: AppBackend["request"];
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
            requestBackend: backendForSignal.request,
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
  const navigation = useMemo<AppNavigation>(
    () =>
      Object.freeze({
        ready: backendReady && !!pending.presentation.navigation,
        path: pending.presentation.navigation?.path ?? null,
        search: pending.presentation.navigation?.search ?? "",
        query: pending.presentation.navigation
          ? parseRouteSearch(
              pending.presentation.navigation.routes.find(
                (route) => route.path === pending.presentation.navigation!.path,
              )!.query ?? [],
              pending.presentation.navigation.search,
            )!.query
          : Object.freeze({}),
        routes: pending.presentation.navigation?.routes ?? Object.freeze([]),
        navigate: pending.navigate,
      }),
    [backendReady, pending],
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
            <NavigationContext.Provider value={navigation}>
              <DraftContext.Provider value={draft.register}>
                <RenderBoundary key={epoch} onFailure={onFailure}>
                  {children}
                  <Commit pending={pending} />
                </RenderBoundary>
              </DraftContext.Provider>
            </NavigationContext.Provider>
          </BackendContext.Provider>
        </PresentationContext.Provider>
      </PortalAppProvider>
    </div>
  );
}
