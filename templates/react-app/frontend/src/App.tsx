import { PortalAppProvider, PortalClient, PortalPage, PortalState, usePortalLocale, type Locale } from "@portal-app/sdk";
import enUS from "../locales/en-US.json";
import zhCN from "../locales/zh-CN.json";
import zhTW from "../locales/zh-TW.json";
import "./style.css";

const client = new PortalClient("APP_ID");
export function Application() {
  const { locale } = usePortalLocale(client);
  return <PortalAppProvider client={client} locale={locale}><Content locale={locale} /></PortalAppProvider>;
}
function Content({ locale }: { locale: Locale }) {
  const copy = { "en-US": enUS, "zh-CN": zhCN, "zh-TW": zhTW }[locale];
  return <PortalPage title={copy.title}><PortalState kind="empty" title={copy.empty} /></PortalPage>;
}
