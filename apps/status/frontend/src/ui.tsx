import {
  createContext,
  useContext,
} from "react";
import { usePortalResource } from "@portal-app/sdk";
import type { Client, Locale } from "./client";
import enUS from "../locales/en-US.json";
import zhCN from "../locales/zh-CN.json";
import zhTW from "../locales/zh-TW.json";

export const locales = { "en-US": enUS, "zh-CN": zhCN, "zh-TW": zhTW };
export interface UI {
  client: Client;
  t(key: string): string;
  locale: Locale;
  busy: boolean;
  admin: boolean;
  error: string;
  revision: number;
  run(action: () => Promise<unknown>, notice?: string): Promise<boolean>;
}
export const UIContext = createContext<UI>(null!);
export const useUI = () => useContext(UIContext);
export { PortalTextField as Field, PortalNumberField as NumberField, PortalChoice as Choice, PortalCheck as Check } from "@portal-app/sdk";
export function useResource<T>(load: () => Promise<T>, initial: T) {
  const { t } = useUI();
  const resource = usePortalResource(load, initial);
  return { data: resource.data, loading: resource.loading, error: resource.errorKey ? t(resource.errorKey) : "" };
}
export const date = (value: string | undefined, locale: string) =>
  value ? new Date(value).toLocaleString(locale) : "—";
