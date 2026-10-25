import { Component as ReactComponent, useEffect, useLayoutEffect, useId, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import { Alert, Button, ConfigProvider, Empty, Form, Input, InputNumber, Select, Skeleton, Typography, Checkbox, theme, type ThemeConfig } from "antd";
import "./foundation.css";
import enUS from "antd/locale/en_US";
import zhCN from "antd/locale/zh_CN";
import zhTW from "antd/locale/zh_TW";

export type Locale = "en-US" | "zh-CN" | "zh-TW";
export type Method = "GET" | "POST" | "PUT" | "DELETE";
export interface PortalTheme {
  dark: boolean;
  colorPrimary: string;
  colorBg: string;
  colorText: string;
  colorBorder: string;
  colorBgLayout: string;
  borderRadius: number;
  locale?: Locale;
}
const initialTheme: PortalTheme = Object.freeze({
  dark: false,
  colorPrimary: "#1677ff",
  colorBg: "#ffffff",
  colorText: "#000000e0",
  colorBorder: "#f0f0f0",
  colorBgLayout: "#f5f5f5",
  borderRadius: 8,
});
export const localeOf = (value: string): Locale =>
  /^zh-(TW|HK|Hant)/i.test(value)
    ? "zh-TW"
    : /^zh/i.test(value)
      ? "zh-CN"
      : "en-US";
export class BridgeError extends Error {
  constructor(
    public key: string,
    public status?: number,
  ) {
    super(key);
  }
}
export const requestErrorKey = (status?: number) =>
  ({
    400: "invalidConfiguration",
    401: "accessDenied",
    403: "accessDenied",
    404: "itemUnavailable",
    409: "configurationConflict",
    422: "invalidConfiguration",
    429: "requestBusy",
  })[status as 400] || "unavailable";

export function bridgeRequest(
  appId: string,
  method: Method,
  path: string,
  body?: unknown,
) {
  if (
    !/^[a-z][a-z0-9-]{0,63}$/.test(appId) ||
    !["GET", "POST", "PUT", "DELETE"].includes(method) ||
    !path.startsWith("/v1/") ||
    path.length > 2048 ||
    /[\s#\\]/.test(path) ||
    (method === "GET" && body !== undefined)
  )
    throw new BridgeError("invalidConfiguration");
  let decoded = path;
  try {
    for (let i = 0; i < 3; i++) decoded = decodeURIComponent(decoded);
  } catch {
    throw new BridgeError("invalidConfiguration");
  }
  if (decoded.includes("..") || decoded.includes("//"))
    throw new BridgeError("invalidConfiguration");
  return {
    method: "POST",
    path: `/api/v1/extensions/${appId}/request`,
    body: { method, path, ...(body === undefined ? {} : { body }) },
  };
}

function colorLuminance(color: string) {
  const channels = [1, 3, 5].map(
    (index) => parseInt(color.slice(index, index + 2), 16) / 255,
  );
  const linear = channels.map((channel) =>
    channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4,
  );
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
}
export function primaryColors(value: string) {
  const background = /^#[0-9a-f]{6}$/i.test(value) ? value : "#1762c4";
  const luminance = colorLuminance(background);
  const foreground =
    (luminance + 0.05) / 0.05 >= 1.05 / (luminance + 0.05)
      ? "#000000"
      : "#ffffff";
  return { background, foreground };
}
export function primaryButtonPalette(
  base: string,
  hover: string,
  active: string,
) {
  const colors = primaryColors(base);
  const adjust = (value: string) => {
    let color = primaryColors(value).background;
    const target = colors.foreground === "#ffffff" ? 0 : 255;
    for (let step = 0; step < 256; step++) {
      const luminance = colorLuminance(color);
      const contrast =
        colors.foreground === "#ffffff"
          ? 1.05 / (luminance + 0.05)
          : (luminance + 0.05) / 0.05;
      if (contrast >= 4.5) return color;
      color =
        "#" +
        [1, 3, 5]
          .map((index) => {
            const channel = parseInt(color.slice(index, index + 2), 16);
            const next =
              target === 0
                ? Math.max(0, channel - Math.max(1, Math.round(channel * 0.04)))
                : Math.min(
                    255,
                    channel + Math.max(1, Math.round((255 - channel) * 0.04)),
                  );
            return next.toString(16).padStart(2, "0");
          })
          .join("");
    }
    return color;
  };
  return { ...colors, hover: adjust(hover), active: adjust(active) };
}

export interface AppClient {
  request<T = unknown>(
    method: Method,
    path: string,
    body?: unknown,
  ): Promise<T>;
  directory<T = unknown>(kind: "ou" | "user", offset: number): Promise<T>;
  getTheme?(): PortalTheme;
  subscribeTheme?(callback: () => void): () => void;
}
type Pending = {
  resolve(value: unknown): void;
  reject(error: Error): void;
  timer: ReturnType<typeof setTimeout>;
};
export class PortalClient implements AppClient {
  private current: Window;
  private parent: Window;
  private initialized = false;
  private disposed = false;
  private sequence = 0;
  private pending = new Map<string, Pending>();
  private listeners = new Set<() => void>();
  private readyListeners = new Set<() => void>();
  private readyCancellations = new Set<() => void>();
  private snapshot = initialTheme;
  constructor(
    private appId: string,
    options?: { parent?: Window; current?: Window },
  ) {
    bridgeRequest(appId, "GET", "/v1/me");
    this.current = options?.current ?? window;
    this.parent = options?.parent ?? this.current.parent;
    this.current.addEventListener("message", this.onMessage);
    this.current.addEventListener("pagehide", this.onPageHide);
  }
  private onPageHide = (event: PageTransitionEvent) => {
    if (!event.persisted) this.dispose();
  };
  getTheme = () => this.snapshot;
  subscribeTheme = (callback: () => void) => {
    this.listeners.add(callback);
    return () => {
      this.listeners.delete(callback);
    };
  };
  private onMessage = (event: MessageEvent) => {
    if (
      this.disposed ||
      event.source !== this.parent ||
      !event.data ||
      typeof event.data !== "object"
    )
      return;
    const data = event.data;
    if (data.type === "rp:init" || data.type === "rp:theme") {
      const next: PortalTheme = { ...this.snapshot };
      if (data.theme && typeof data.theme === "object") {
        next.dark = data.theme.dark === true;
        for (const key of [
          "colorPrimary",
          "colorBg",
          "colorText",
          "colorBorder",
          "colorBgLayout",
        ] as const) {
          const value = data.theme[key];
          if (
            typeof value === "string" &&
            value.length <= 96 &&
            !/[;{}<>]/.test(value)
          )
            next[key] = value;
        }
        if (Number.isFinite(data.theme.borderRadius))
          next.borderRadius = Math.min(
            24,
            Math.max(0, data.theme.borderRadius),
          );
      }
      if (typeof data.locale === "string") next.locale = localeOf(data.locale);
      this.snapshot = Object.freeze(next);
      this.listeners.forEach((callback) => callback());
      if (!this.initialized && data.type === "rp:init") {
        this.initialized = true;
        this.readyListeners.forEach((callback) => callback());
        this.readyListeners.clear();
      }
      return;
    }
    if (data.type !== "rp:api:result" || typeof data.reqId !== "string") return;
    const pending = this.pending.get(data.reqId);
    if (!pending) return;
    this.pending.delete(data.reqId);
    clearTimeout(pending.timer);
    if (data.ok === true) pending.resolve(data.data);
    else
      pending.reject(
        new BridgeError(requestErrorKey(data.status), data.status),
      );
  };
  private ready() {
    if (this.parent === this.current)
      return Promise.reject(new BridgeError("privateOnly"));
    if (this.disposed) return Promise.reject(new BridgeError("unavailable"));
    if (this.initialized) return Promise.resolve();
    return new Promise<void>((resolve, reject) => {
      const complete = () => {
        clearTimeout(timer);
        this.readyCancellations.delete(cancel);
        resolve();
      };
      const cancel = () => {
        clearTimeout(timer);
        this.readyListeners.delete(complete);
        reject(new BridgeError("unavailable"));
      };
      const timer = setTimeout(() => {
        this.readyListeners.delete(complete);
        this.readyCancellations.delete(cancel);
        reject(new BridgeError("unavailable"));
      }, 25000);
      this.readyListeners.add(complete);
      this.readyCancellations.add(cancel);
    });
  }
  async machine<T>(method: "GET", path: string): Promise<T> {
    if (
      !path.startsWith("/api/v1/") ||
      path.length > 2048 ||
      /[\s#\\]/.test(path)
    )
      throw new BridgeError("invalidConfiguration");
    let decoded = path;
    try {
      for (let i = 0; i < 3; i++) decoded = decodeURIComponent(decoded);
    } catch {
      throw new BridgeError("invalidConfiguration");
    }
    if (
      decoded.includes("..") ||
      decoded.includes("//") ||
      /[\s#\\]/.test(decoded)
    )
      throw new BridgeError("invalidConfiguration");
    return this.host<T>({ method, path });
  }
  async request<T>(method: Method, path: string, body?: unknown): Promise<T> {
    return this.host<T>(bridgeRequest(this.appId, method, path, body));
  }
  async directory<T>(kind: "ou" | "user", offset: number): Promise<T> {
    if (
      !["ou", "user"].includes(kind) ||
      !Number.isSafeInteger(offset) ||
      offset < 0
    )
      throw new BridgeError("invalidConfiguration");
    return this.host<T>({
      method: "GET",
      path: `/api/v1/extensions/${this.appId}/principals?kind=${kind}&offset=${offset}`,
    });
  }
  private async host<T>(request: object): Promise<T> {
    await this.ready();
    if (this.disposed || this.pending.size >= 16)
      throw new BridgeError("requestBusy");
    return new Promise<T>((resolve, reject) => {
      const reqId = `${this.appId}-${++this.sequence}`;
      const timer = setTimeout(() => {
        this.pending.delete(reqId);
        reject(new BridgeError("unavailable"));
      }, 25000);
      this.pending.set(reqId, {
        resolve: (value) => resolve(value as T),
        reject,
        timer,
      });
      this.parent.postMessage({ type: "rp:api", reqId, ...request }, "*");
    });
  }
  dispose() {
    this.disposed = true;
    this.current.removeEventListener("message", this.onMessage);
    this.current.removeEventListener("pagehide", this.onPageHide);
    for (const p of this.pending.values()) {
      clearTimeout(p.timer);
      p.reject(new BridgeError("unavailable"));
    }
    this.pending.clear();
    this.listeners.clear();
    this.readyListeners.clear();
    for (const cancel of this.readyCancellations) cancel();
    this.readyCancellations.clear();
  }
}
const noSubscribe = () => () => {};
const defaultSnapshot = () => initialTheme;
export function usePortalTheme(client: AppClient) {
  return useSyncExternalStore(
    client.subscribeTheme ?? noSubscribe,
    client.getTheme ?? defaultSnapshot,
  );
}
export type LocaleSelection = Locale | "panel";
export function usePortalLocale(client: AppClient) {
  const snapshot = usePortalTheme(client);
  const [selection, setSelection] = useState<LocaleSelection>("panel");
  const fallback = localeOf(typeof navigator === "undefined" ? "en-US" : navigator.language);
  const locale = selection === "panel" ? snapshot.locale ?? fallback : selection;
  return { locale, selection, setSelection };
}
const languageCopy = {
  "en-US": { language: "Language", panel: "Follow panel", renderError: "This application could not be displayed.", retry: "Try again" },
  "zh-CN": { language: "语言", panel: "跟随面板", renderError: "应用暂时无法显示。", retry: "重试" },
  "zh-TW": { language: "語言", panel: "跟隨面板", renderError: "應用暫時無法顯示。", retry: "重試" },
};
export class PortalErrorBoundary extends ReactComponent<{ locale: Locale; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    const copy = languageCopy[this.props.locale];
    return this.state.failed ? <PortalState kind="error" title={copy.renderError} retryLabel={copy.retry}
      onRetry={() => this.setState({ failed: false })} /> : this.props.children;
  }
}
export function PortalLocaleSelect({ locale, selection, onChange }: {
  locale: Locale; selection: LocaleSelection; onChange(value: LocaleSelection): void;
}) {
  const copy = languageCopy[locale];
  return <Select virtual={false} aria-label={copy.language} value={selection} onChange={onChange}
    style={{ minWidth: 140 }} options={[
      { value: "panel", label: copy.panel },
      { value: "en-US", label: "English" },
      { value: "zh-CN", label: "简体中文" },
      { value: "zh-TW", label: "繁體中文" },
    ]} />;
}
export function PortalPage({ title, description, actions, children, className = "", busy = false }: {
  title: string; description?: ReactNode; actions?: ReactNode; children: ReactNode;
  className?: string; busy?: boolean;
}) {
  const id = useId();
  return <main className={`portal-app-page ${className}`} aria-labelledby={id} aria-busy={busy}>
    <header className="portal-app-page-header">
      <div><Typography.Title id={id} level={3} style={{ margin: 0 }}>{title}</Typography.Title>
        {description && <Typography.Text type="secondary">{description}</Typography.Text>}</div>
      {actions && <div className="portal-app-page-actions">{actions}</div>}
    </header>
    {children}
  </main>;
}
export function PortalState({ kind, title, description, onRetry, retryLabel }: {
  kind: "loading" | "empty" | "error" | "forbidden" | "incompatible";
  title: string; description?: ReactNode; onRetry?(): void; retryLabel?: string;
}) {
  if (kind === "loading") return <div role="status" aria-label={title} aria-busy="true"><Skeleton active title paragraph={{ rows: 3 }} /></div>;
  if (kind === "empty") return <Empty description={<><strong>{title}</strong>{description && <div>{description}</div>}</>} />;
  return <Alert role="alert" type={kind === "incompatible" ? "warning" : "error"} showIcon title={title}
    description={description} action={onRetry && retryLabel ? <Button onClick={onRetry}>{retryLabel}</Button> : undefined} />;
}
export function usePortalResource<T>(load: () => Promise<T>, initialData: T) {
  const initial = useRef(initialData);
  const [data, setData] = useState(initialData), [loading, setLoading] = useState(true), [errorKey, setErrorKey] = useState("");
  useEffect(() => {
    let current = true;
    setLoading(true); setErrorKey("");
    Promise.resolve().then(load).then(value => { if (current) setData(value); }).catch(error => {
      if (current) {
        setData(initial.current);
        const key = error && typeof error === "object" && "key" in error ? error.key : undefined;
        setErrorKey(typeof key === "string" ? key : "unavailable");
      }
    }).finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [load]);
  return { data, loading, errorKey };
}

export function PortalTextField({ label, value, onChange, secret = false, multiline = false, help }: {
  label: string; value?: string; onChange(value: string): void; secret?: boolean; multiline?: boolean; help?: ReactNode;
}) {
  const id = useId(), props = { id, value: value ?? "", autoComplete: secret ? "new-password" : "off",
    onChange: (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => onChange(event.target.value) };
  return <Form.Item label={label} htmlFor={id} extra={help}>
    {secret ? <Input.Password {...props} visibilityToggle={false} /> : multiline ? <Input.TextArea {...props} autoSize={{ minRows: 2, maxRows: 6 }} /> : <Input {...props} />}
  </Form.Item>;
}
export function PortalNumberField({ label, value, onChange, min, max }: {
  label: string; value: number; onChange(value: number): void; min: number; max: number;
}) {
  const id = useId();
  return <Form.Item label={label} htmlFor={id}><InputNumber id={id} value={value} min={min} max={max} precision={0}
    onChange={value => onChange(value ?? min)} style={{ width: "100%" }} /></Form.Item>;
}
export function PortalChoice({ label, value, options, onChange, multiple = false, disabled = false, help }: {
  label: string; value: string | string[]; options: { value: string; label: string }[];
  onChange(value: string | string[]): void; multiple?: boolean; disabled?: boolean; help?: ReactNode;
}) {
  const id = useId();
  return <Form.Item label={label} htmlFor={id} extra={help}><Select virtual={false} id={id} aria-label={label} value={value}
    options={options} onChange={onChange} mode={multiple ? "multiple" : undefined} disabled={disabled}
    showSearch={{ optionFilterProp: "label" }} style={{ width: "100%" }} /></Form.Item>;
}
export function PortalCheck({ children, checked, onChange }: {
  children: ReactNode; checked: boolean; onChange(value: boolean): void;
}) {
  return <Form.Item><Checkbox checked={checked} onChange={event => onChange(event.target.checked)}>{children}</Checkbox></Form.Item>;
}
export function PortalAppProvider({
  client,
  locale,
  children,
}: {
  client: AppClient;
  locale: Locale;
  children: ReactNode;
}) {
  const snapshot = usePortalTheme(client);
  useLayoutEffect(() => {
    document.documentElement.lang = locale;
    // Keep the initial iframe surface transparent until the host supplies its theme.
    // A guessed light background would override a dark embedding surface on refresh.
    if (snapshot === initialTheme) return;
    document.documentElement.style.colorScheme = snapshot.dark
      ? "dark"
      : "light";
    document.body.style.background = snapshot.colorBgLayout;
    document.body.style.color = snapshot.colorText;
  }, [snapshot, locale]);
  const algorithm = snapshot.dark
    ? theme.darkAlgorithm
    : theme.defaultAlgorithm;
  const derived = theme.getDesignToken({
    algorithm,
    token: { colorPrimary: snapshot.colorPrimary },
  });
  const primary = primaryButtonPalette(
    snapshot.colorPrimary,
    derived.colorPrimaryHover,
    derived.colorPrimaryActive,
  );
  const config: ThemeConfig = {
    algorithm,
    components: {
      Button: {
        primaryColor: primary.foreground,
        colorPrimaryHover: primary.hover,
        colorPrimaryActive: primary.active,
      },
      Tabs: { itemSelectedColor: snapshot.dark ? "#91caff" : "#0958d9" },
      Steps: { colorTextDescription: snapshot.dark ? "#bfbfbf" : "#595959" },
      Tag: {
        colorInfo: snapshot.dark ? "#91caff" : "#0958d9",
        colorSuccess: snapshot.dark ? "#b7eb8f" : "#237804",
        colorError: snapshot.dark ? "#ffa39e" : "#a8071a",
        colorWarning: snapshot.dark ? "#ffe58f" : "#874d00",
      },
    },
    token: {
      colorPrimary: snapshot.colorPrimary,
      colorBgContainer: snapshot.colorBg,
      colorBgLayout: snapshot.colorBgLayout,
      colorText: snapshot.colorText,
      colorBorderSecondary: snapshot.colorBorder,
      borderRadius: snapshot.borderRadius,
      fontSize: 14,
      colorTextSecondary: snapshot.dark ? "#bfbfbf" : "#595959",
      colorTextDescription: snapshot.dark ? "#bfbfbf" : "#595959",
      colorTextPlaceholder: snapshot.dark ? "#a6a6a6" : "#737373",
      colorPrimaryText: snapshot.dark ? "#91caff" : "#0958d9",
      colorPrimaryTextHover: snapshot.dark ? "#bae0ff" : "#003eb3",
      colorLink: snapshot.dark ? "#91caff" : "#0958d9",
      colorTextLightSolid: primary.foreground,
    },
  };
  return (
    <ConfigProvider
      locale={{ "en-US": enUS, "zh-CN": zhCN, "zh-TW": zhTW }[locale]}
      theme={config}
      getPopupContainer={() => document.body}
    >
      <PortalErrorBoundary locale={locale}>{children}</PortalErrorBoundary>
    </ConfigProvider>
  );
}
