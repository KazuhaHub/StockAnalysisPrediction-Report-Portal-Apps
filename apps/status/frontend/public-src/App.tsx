import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Button,
  Card,
  ConfigProvider,
  Drawer,
  Empty,
  Flex,
  Pagination,
  Select,
  Space,
  Tag,
  Typography,
  theme,
} from "antd";
import enUS from "antd/locale/en_US";
import zhCN from "antd/locale/zh_CN";
import zhTW from "antd/locale/zh_TW";
import { localeOf, type Locale } from "@portal-app/sdk";
import en from "../locales/en-US.json";
import cn from "../locales/zh-CN.json";
import tw from "../locales/zh-TW.json";
import contracts from "../src/contracts.cjs";
import "./style.css";

interface Component {
  id: string;
  label: string;
  state: string;
  observed_at?: string;
}
interface Incident {
  id: string;
  summary: string;
  opened_at: string;
}
interface Hour {
  from: string;
  to: string;
  state: string;
}
interface Page<T> {
  items: T[];
  total: number;
  generated_at?: string;
}
const dictionaries = { "en-US": en, "zh-CN": cn, "zh-TW": tw };
async function read<T>(path: string): Promise<T> {
  const response = await fetch("public/v1/" + path, {
    credentials: "omit",
    cache: "no-store",
  });
  if (!response.ok) throw new Error("unavailable");
  return response.json();
}
export function PublicStatus() {
  const [locale, setLocale] = useState<Locale>(() =>
    localeOf(navigator.language),
  );
  const [dark, setDark] = useState(
    () => matchMedia("(prefers-color-scheme: dark)").matches,
  );
  const [components, setComponents] = useState<Page<Component>>({
    items: [],
    total: 0,
  });
  const [incidents, setIncidents] = useState<Page<Incident>>({
    items: [],
    total: 0,
  });
  const [componentPage, setComponentPage] = useState(1),
    [incidentPage, setIncidentPage] = useState(1);
  const [error, setError] = useState(false),
    [loading, setLoading] = useState(true),
    [revision, setRevision] = useState(0);
  const [history, setHistory] = useState<Component | null>(null);
  const t = (key: string) =>
    (dictionaries[locale] as Record<string, string>)[key] ?? key;
  const date = (value?: string) =>
    value ? new Date(value).toLocaleString(locale) : "—";
  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);
  useEffect(() => {
    const media = matchMedia("(prefers-color-scheme: dark)");
    const update = () => setDark(media.matches);
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  useEffect(() => {
    const refresh = () => {
      if (!document.hidden) setRevision((value) => value + 1);
    };
    const timer = setInterval(refresh, 30000);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, []);
  useEffect(() => {
    let active = true;
    setLoading(true);
    void Promise.all([
      read<Page<Component>>(
        `status?limit=50&offset=${(componentPage - 1) * 50}`,
      ),
      read<Page<Incident>>(
        `incidents?limit=50&offset=${(incidentPage - 1) * 50}`,
      ),
    ])
      .then(([status, events]) => {
        if (active) {
          setComponents(status);
          setIncidents(events);
          setError(false);
        }
      })
      .catch(() => {
        if (active) setError(true);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [componentPage, incidentPage, revision]);
  useEffect(() => {
    document.documentElement.style.colorScheme = dark ? "dark" : "light";
    document.body.style.background = dark ? "#141414" : "#f5f5f5";
  }, [dark]);
  return (
    <ConfigProvider
      locale={{ "en-US": enUS, "zh-CN": zhCN, "zh-TW": zhTW }[locale]}
      theme={{
        algorithm: dark ? theme.darkAlgorithm : theme.defaultAlgorithm,
        token: { colorTextSecondary: dark ? "#bfbfbf" : "#595959" },
      }}
    >
      <main>
        <Flex justify="space-between" gap={16} wrap>
          <div>
            <Typography.Title level={1}>{t("title")}</Typography.Title>
            <Typography.Paragraph type="secondary">
              {t("subtitle")}
            </Typography.Paragraph>
          </div>
          <Select
            virtual={false}
            aria-label={t("language")}
            value={locale}
            onChange={setLocale}
            options={Object.entries(dictionaries).map(([value, copy]) => ({
              value,
              label: copy.languageName,
            }))}
          />
        </Flex>
        {error ? (
          <Alert
            role="alert"
            type="error"
            showIcon
            title={t("unavailable")}
            action={
              <Button onClick={() => setRevision((value) => value + 1)}>
                {t("refresh")}
              </Button>
            }
          />
        ) : (
          <>
            <div className="public-grid" aria-busy={loading}>
              {!components.items?.length && <Empty description={t("empty")} />}
              {(components.items ?? []).map((component) => (
                <Card key={component.id}>
                  <Space orientation="vertical">
                    <Typography.Title level={2}>
                      {component.label}
                    </Typography.Title>
                    <Tag>{t(contracts.safeState(component.state))}</Tag>
                    <Typography.Text type="secondary">
                      {t("observed")}: {date(component.observed_at)}
                    </Typography.Text>
                    <Button onClick={() => setHistory(component)}>
                      {t("history")}
                    </Button>
                  </Space>
                </Card>
              ))}
            </div>
            {components.total > 50 && (
              <Pagination
                aria-label={t("components")}
                current={componentPage}
                pageSize={50}
                total={components.total}
                showSizeChanger={false}
                onChange={setComponentPage}
              />
            )}
            <Typography.Title level={2}>{t("incidents")}</Typography.Title>
            {!incidents.items?.length && (
              <Typography.Paragraph type="secondary">
                {t("noIncidents")}
              </Typography.Paragraph>
            )}
            {(incidents.items ?? []).map((incident) => (
              <Card key={incident.id}>
                <Typography.Title level={3}>
                  {incident.summary}
                </Typography.Title>
                <Typography.Text>{date(incident.opened_at)}</Typography.Text>
              </Card>
            ))}
            {incidents.total > 50 && (
              <Pagination
                aria-label={t("incidents")}
                current={incidentPage}
                pageSize={50}
                total={incidents.total}
                showSizeChanger={false}
                onChange={setIncidentPage}
              />
            )}
            <Typography.Paragraph type="secondary">
              {t("pageUpdated")}: {date(components.generated_at)}
            </Typography.Paragraph>
          </>
        )}
        {history && (
          <History
            component={history}
            close={() => setHistory(null)}
            t={t}
            date={date}
          />
        )}
      </main>
    </ConfigProvider>
  );
}
function History({
  component,
  close,
  t,
  date,
}: {
  component: Component;
  close(): void;
  t(key: string): string;
  date(value?: string): string;
}) {
  const [items, setItems] = useState<Hour[]>([]),
    [error, setError] = useState(false),
    [loading, setLoading] = useState(true);
  const load = useCallback(
    () =>
      read<Page<Hour>>(
        "history?component_id=" + encodeURIComponent(component.id),
      ),
    [component.id],
  );
  useEffect(() => {
    let active = true;
    void load()
      .then((data) => {
        if (active) setItems(data.items ?? []);
      })
      .catch(() => {
        if (active) setError(true);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [load]);
  return (
    <Drawer
      open
      title={component.label + " · " + t("history")}
      onClose={close}
      size={560}
      styles={{wrapper: {maxWidth: "100vw"}}}
    >
      {error ? (
        <Alert role="alert" type="error" title={t("unavailable")} />
      ) : (
        <Card loading={loading}>
          <Typography.Paragraph type="secondary">
            {t("wholeHours")}
          </Typography.Paragraph>
          {!items.length && !loading && <Empty description={t("noCoverage")} />}
          <div className="history-strip" aria-label={t("history")}>
            {items.map((item, index) => {
              const label =
                date(item.from) +
                " – " +
                date(item.to) +
                ": " +
                t(contracts.safeState(item.state));
              return (
                <span
                  key={index}
                  className={"hour " + contracts.safeState(item.state)}
                  tabIndex={0}
                  role="img"
                  aria-label={label}
                  title={label}
                />
              );
            })}
          </div>
        </Card>
      )}
    </Drawer>
  );
}
