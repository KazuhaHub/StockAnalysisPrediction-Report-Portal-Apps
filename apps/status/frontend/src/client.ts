export { PortalClient, BridgeError } from "@portal-app/sdk";
export type {
  AppClient as Client,
  Locale,
  Method,
  PortalTheme,
} from "@portal-app/sdk";

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
export interface Principal {
  principal: string;
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
