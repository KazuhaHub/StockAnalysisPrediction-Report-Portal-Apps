// Experimental React presentation root. No data API, credential, navigation or
// legacy-protocol fallback is granted by this component.
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
} from "./bridge-v2";
import { PortalAppProvider, type AppClient } from "./index";
import "./root-v2.css";

export interface AppPresentation {
  readonly presentation: BridgePresentation;
  readonly context: BridgeContext;
}
const PresentationContext = createContext<AppPresentation | null>(null);
export function useAppPresentation(): AppPresentation {
  const value = useContext(PresentationContext);
  if (!value) throw new Error("AppRoot presentation unavailable");
  return value;
}
interface Pending extends AppPresentation {
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
    let closed = false;
    const closeConnection = () => {
      if (connection && !closed) {
        closed = true;
        connection.close();
      }
    };
    const discard = () => {
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
          discard();
          locale.current = presentation.locale;
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
      epoch={epoch}
      onFailure={() => fail.current()}
    >
      {children}
    </PresentationFrame>
  );
}
function PresentationFrame({
  pending,
  epoch,
  onFailure,
  children,
}: {
  pending: Pending;
  epoch: number;
  onFailure(): void;
  children: ReactNode;
}) {
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
  return (
    <div
      className="portal-v2-root"
      data-app-layout={pending.presentation.layout}
    >
      <PortalAppProvider client={client} locale={pending.presentation.locale}>
        <PresentationContext.Provider value={value}>
          <RenderBoundary key={epoch} onFailure={onFailure}>
            {children}
            <Commit pending={pending} />
          </RenderBoundary>
        </PresentationContext.Provider>
      </PortalAppProvider>
    </div>
  );
}
