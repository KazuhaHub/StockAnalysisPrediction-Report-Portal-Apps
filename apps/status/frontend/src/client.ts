import { useMemo } from "react";
import { requestErrorKey } from "@portal-app/sdk";
import { BridgeBackendError } from "@portal-app/sdk/bridge-v2";
import { useAppBackend, type AppBackend } from "@portal-app/sdk/root-v2";

export type Locale = "en-US" | "zh-CN" | "zh-TW";
export type Method = "GET" | "POST" | "PUT" | "DELETE";

/** A failed request. `key` selects a localized message; nothing else is shown. */
export class RequestError extends Error {
  constructor(
    public key: string,
    public status?: number,
  ) {
    super(key);
  }
}
export interface Client {
  request<T = unknown>(method: Method, path: string, body?: unknown): Promise<T>;
}

const transportKeys: Record<string, string> = {
  busy: "requestBusy",
  // The write may have been applied; the SDK never retries it and neither do we.
  uncertain: "writeUncertain",
};

/**
 * Status's own service API over the platform backend relay. Replies are the
 * service's JSON; every non-2xx reply and every transport failure becomes a
 * RequestError with a fixed key, so no server text reaches the screen.
 */
export function createClient(request: AppBackend["request"]): Client {
  return {
    async request<T>(method: Method, path: string, body?: unknown): Promise<T> {
      let response;
      try {
        response = await request({
          method,
          path,
          body: body === undefined ? "" : JSON.stringify(body),
        });
      } catch (error) {
        const code = error instanceof BridgeBackendError ? error.code : "unavailable";
        throw new RequestError(transportKeys[code] ?? "unavailable");
      }
      if (response.status < 200 || response.status > 299)
        throw new RequestError(requestErrorKey(response.status), response.status);
      try {
        return JSON.parse(response.body) as T;
      } catch {
        throw new RequestError("unavailable", response.status);
      }
    },
  };
}
export function useClient(): Client {
  const backend = useAppBackend();
  return useMemo(() => createClient(backend.request), [backend.request]);
}

export interface Page<T> {
  items: T[];
  total: number;
}
export interface Balance {
  currency: string;
  total?: string;
  cash?: string;
  credit?: string;
  granted?: string;
  topped_up?: string;
}
export interface Monitor {
  id?: string;
  label: string;
  kind: string;
  credential_id?: string;
  enabled: boolean;
  interval_seconds: number;
  timeout_seconds: number;
  revision?: number;
  config: Record<string, unknown>;
  state?: string;
  stale?: boolean;
  outcome?: string;
  reason_code?: string;
  observed_at?: string;
  last_success_at?: string;
  next_check_at?: string;
  measurements?: { latency_ms?: number; balances?: Balance[] };
}
export interface Component {
  id?: string;
  revision: number;
  label: string;
  public_label: string;
  enabled: boolean;
  public_enabled: boolean;
  grants: { principal: string; permission: string }[];
  monitors: Monitor[];
  state?: string;
}
export interface Credential {
  id?: string;
  revision: number;
  kind: string;
  label: string;
}
export interface Incident {
  id: string;
  component_id: string;
  summary: string;
  state: string;
  opened_at: string;
  resolved_at?: string;
  revision: number;
  transitions?: { occurred_at: string; message: string }[];
}
export interface Settings {
  public_enabled: boolean;
  probes_paused: boolean;
  outbox_paused: boolean;
  portal_url: string;
  portal_networks: string[];
  raw_retention_days: number;
  history_retention_days: number;
}
export interface Operations {
  settings: Settings;
  queue_fingerprint: string;
  outbox: {
    id: string;
    component_id: string;
    state: string;
    attempts: number;
    last_error: string;
  }[];
  publishers: {
    component_id: string;
    credential_id: string;
    enabled: boolean;
    revision: number;
  }[];
}
