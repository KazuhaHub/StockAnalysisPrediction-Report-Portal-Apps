import { useAppPresentation } from "@portal-app/sdk/root-v2";
import enUS from "../../locales/en-US.json";
import zhCN from "../../locales/zh-CN.json";
import zhTW from "../../locales/zh-TW.json";

export type Locale = "en-US" | "zh-CN" | "zh-TW";
export type Copy = typeof enUS;

export const locales: Record<Locale, Copy> = {
  "en-US": enUS,
  "zh-CN": zhCN,
  "zh-TW": zhTW,
};

export function useCopy(): { copy: Copy; locale: Locale; timeZone: string } {
  const { presentation } = useAppPresentation();
  return {
    copy: locales[presentation.locale],
    locale: presentation.locale,
    timeZone: presentation.timeZone,
  };
}
