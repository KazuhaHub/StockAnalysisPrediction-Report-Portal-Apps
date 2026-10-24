import { useEffect, useState } from "react";
import { Empty, Typography, theme } from "antd";
import {
  PortalAppProvider,
  PortalClient,
  localeOf,
  usePortalTheme,
  type Locale,
} from "@portal-app/sdk";
import enUS from "../locales/en-US.json";
import zhCN from "../locales/zh-CN.json";
import zhTW from "../locales/zh-TW.json";
import "./style.css";

const client = new PortalClient("APP_ID");
export function Application() {
  useEffect(() => () => client.dispose(), []);
  const host = usePortalTheme(client);
  const [locale, setLocale] = useState<Locale>(
    () => host.locale ?? localeOf(navigator.language),
  );
  useEffect(() => {
    if (host.locale) setLocale(host.locale);
  }, [host.locale]);
  return (
    <PortalAppProvider client={client} locale={locale}>
      <Content locale={locale} />
    </PortalAppProvider>
  );
}
function Content({ locale }: { locale: Locale }) {
  const { token } = theme.useToken(),
    copy = { "en-US": enUS, "zh-CN": zhCN, "zh-TW": zhTW }[locale];
  useEffect(() => {
    document.body.style.background = token.colorBgLayout;
    document.documentElement.lang = locale;
  }, [token.colorBgLayout, locale]);
  return (
    <main>
      <Typography.Title level={3}>{copy.title}</Typography.Title>
      <Empty description={copy.empty} />
    </main>
  );
}
