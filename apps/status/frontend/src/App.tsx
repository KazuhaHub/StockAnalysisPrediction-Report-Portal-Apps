import { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Collapse,
  Descriptions,
  Drawer,
  Empty,
  Flex,
  Form,
  Input,
  Skeleton,
  Space,
  Table,
  Tabs,
  Tag,
  Typography,
} from "antd";
import { ReloadOutlined, SettingOutlined } from "@ant-design/icons";
import { PortalAppProvider, PortalPage, usePortalLocale } from "@portal-app/sdk";
import type { Client, Component, Incident, Page } from "./client";
import {
  Check,
  date,
  Field,
  locales,
  UIContext,
  useResource,
  useUI,
} from "./ui";
import { Management } from "./Management";
import contracts from "./contracts.cjs";

const { compatibleBackend, safeState, percentage, monitorHint } = contracts;
export function StatusApp({ client }: { client: Client }) {
  const { locale } = usePortalLocale(client);
  const [ready, setReady] = useState(false),
    [admin, setAdmin] = useState(false),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [revision, setRevision] = useState(0),
    [notice, setNotice] = useState(""),
    busyRef = useRef(false);
  const dictionary = locales[locale] as Record<string, string>,
    t = (key: string) => dictionary[key] ?? key;
  const connect = useCallback(async () => {
    setReady(false);
    setAdmin(false);
    setError("");
    try {
      const me = await client.request<{
        admin: boolean;
        api_version: number;
        capabilities: string[];
      }>("GET", "/v1/me");
      if (!compatibleBackend(me)) throw { key: "backendUpgradeRequired" };
      setAdmin(me.admin === true);
      setReady(true);
    } catch (e) {
      setError((e as { key?: string }).key ?? "unavailable");
    }
  }, [client]);
  useEffect(() => {
    void connect();
  }, [connect]);
  const run = async (action: () => Promise<unknown>, success = "saved") => {
    if (busyRef.current) return false;
    busyRef.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await action();
      setNotice(success);
      setRevision((old) => old + 1);
      return true;
    } catch (e) {
      setError((e as { key?: string }).key ?? "unavailable");
      return false;
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  };
  useEffect(() => {
    if (error)
      (
        (document.querySelector('[role="dialog"] [data-app-error]') ??
          document.querySelector("[data-app-error]")) as HTMLElement | null
      )?.focus();
  }, [error]);
  return (
    <PortalAppProvider client={client} locale={locale}>
      <UIContext.Provider
        value={{
          client,
          locale,
          t,
          busy,
          run,
          revision,
          admin,
          error: error ? t(error) : "",
        }}
      >
        <StatusSurface
          admin={admin}
          ready={ready}
          error={error}
          notice={notice}
          refresh={() => {
            if (ready) setRevision((value) => value + 1);
            else void connect();
          }}
        />
      </UIContext.Provider>
    </PortalAppProvider>
  );
}
function StatusSurface({
  admin,
  ready,
  error,
  notice,
  refresh,
}: {
  admin: boolean;
  ready: boolean;
  error: string;
  notice: string;
  refresh(): void;
}) {
  const { t, busy } = useUI(), [tab, setTab] = useState("overview");
  return (
    <PortalPage title={t("title")} description={t("subtitle")} className="status-app" busy={busy} actions={
        <Space wrap>
          <Button
            aria-label={t("refresh")}
            icon={<ReloadOutlined />}
            onClick={refresh}
            disabled={busy}
          >
            {t("refresh")}
          </Button>
          {admin && (
            <Button
              aria-label={t("manage")}
              icon={<SettingOutlined />}
              type={tab === "manage" ? "primary" : "default"}
              onClick={() => setTab(tab === "manage" ? "overview" : "manage")}
              disabled={busy}
            >
              {t("manage")}
            </Button>
          )}
        </Space>
      }>
      {error && (
        <div data-app-error tabIndex={-1} className="section-gap">
          <Alert
            role="alert"
            showIcon
            type="error"
            title={t(error)}
            description={!ready ? t("backendNotReady") : undefined}
          />
        </div>
      )}
      {notice && (
        <Typography.Paragraph
          role="status"
          type="secondary"
          className="section-gap"
        >
          {t(notice)}
        </Typography.Paragraph>
      )}
      {!ready ? (
        !error && <Skeleton active className="section-gap" />
      ) : (
        <>
          {tab !== "manage" && (
            <Tabs
              activeKey={tab}
              onChange={setTab}
              items={["overview", "incidents"].map((key) => ({
                key,
                label: t(key),
              }))}
            />
          )}
          {tab === "overview" ? (
            <Overview />
          ) : tab === "incidents" ? (
            <Incidents />
          ) : (
            admin && <Management />
          )}
        </>
      )}
    </PortalPage>
  );
}
const stateColors: Record<string, string> = {
  operational: "success",
  degraded: "warning",
  outage: "error",
  maintenance: "processing",
  paused: "default",
  unknown: "default",
};
export function StateTag({
  value,
  stale,
}: {
  value?: string;
  stale?: boolean;
}) {
  const { t } = useUI(),
    state = safeState(value, stale);
  return <Tag color={stateColors[state]}>{t(state)}</Tag>;
}

function Overview() {
  const { client, revision, locale, t } = useUI(),
    [offset, setOffset] = useState(0),
    [search, setSearch] = useState(""),
    [query, setQuery] = useState(""),
    [selected, setSelected] = useState<string | null>(null),
    [tick, setTick] = useState(0);
  const load = useCallback(
    () =>
      client.request<Page<Component>>(
        "GET",
        `/v1/components?limit=50&offset=${offset}&q=${encodeURIComponent(query)}`,
      ),
    [client, revision, offset, query, tick],
  );
  const { data, loading, error } = useResource(load, {
    items: [] as Component[],
    total: 0,
  });
  useEffect(() => {
    const refresh = () => {
      const tag = document.activeElement?.tagName;
      if (
        !document.hidden &&
        !selected &&
        !["INPUT", "TEXTAREA"].includes(tag ?? "")
      )
        setTick((value) => value + 1);
    };
    const timer = setInterval(refresh, 30000);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, [selected]);
  return (
    <>
      <Flex
        justify="space-between"
        align="center"
        gap={12}
        wrap
        className="section-gap"
      >
        <Typography.Text type="secondary">
          {data.total} {t("servicesCount")}
        </Typography.Text>
        <Input.Search
          aria-label={t("componentSearch")}
          placeholder={t("componentSearch")}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          onSearch={(value) => {
            setOffset(0);
            setQuery(value);
          }}
          style={{ width: 300, maxWidth: "100%" }}
          allowClear
        />
      </Flex>
      {error ? (
        <Alert type="error" role="alert" title={error} showIcon />
      ) : loading && !data.items.length ? (
        <Skeleton active />
      ) : !data.items.length ? (
        <Empty description={t("empty")} />
      ) : (
        <div className="status-grid">
          {data.items.map((component) => (
            <article key={component.id}>
              <Card
                title={
                  <Typography.Title level={4} style={{ margin: 0 }}>
                    {component.label}
                  </Typography.Title>
                }
                extra={<StateTag value={component.state} />}
                actions={[
                  <Button
                    type="text"
                    key="history"
                    onClick={() => setSelected(component.id!)}
                  >
                    {t("history")}
                  </Button>,
                ]}
              >
                <Space direction="vertical" style={{ width: "100%" }} size={12}>
                  {(component.monitors ?? []).map((m) => (
                    <div key={m.id}>
                      <Flex justify="space-between" align="center" gap={8} wrap>
                        <Typography.Text>{m.label}</Typography.Text>
                        {(component.monitors ?? []).length > 1 && (
                          <StateTag value={m.state} stale={m.stale} />
                        )}
                      </Flex>
                      <Typography.Text
                        type="secondary"
                        className="observation-time"
                      >
                        {t("observed")}: {date(m.observed_at, locale)}
                      </Typography.Text>
                      {monitorHint(m) && (
                        <Typography.Paragraph
                          type="secondary"
                          style={{ margin: "8px 0 0" }}
                        >
                          {t(monitorHint(m))}
                        </Typography.Paragraph>
                      )}
                      {m.outcome === "unsupported" && (
                        <Tag>{t("unsupported")}</Tag>
                      )}
                    </div>
                  ))}
                </Space>
              </Card>
            </article>
          ))}
        </div>
      )}
      <Pages offset={offset} total={data.total} change={setOffset} />
      {selected && (
        <HistoryDrawer id={selected} close={() => setSelected(null)} />
      )}
    </>
  );
}
function Pages({
  offset,
  total,
  change,
}: {
  offset: number;
  total: number;
  change(offset: number): void;
}) {
  const { t } = useUI();
  if (total <= 50) return null;
  return (
    <Flex
      justify="space-between"
      align="center"
      className="section-gap"
      gap={8}
    >
      <Button
        disabled={offset === 0}
        onClick={() => change(Math.max(0, offset - 50))}
      >
        {t("pagePrevious")}
      </Button>
      <Typography.Text type="secondary">
        {offset + 1}–{Math.min(offset + 50, total)} / {total}
      </Typography.Text>
      <Button
        disabled={offset + 50 >= total}
        onClick={() => change(offset + 50)}
      >
        {t("pageNext")}
      </Button>
    </Flex>
  );
}
interface History {
  monitor_id: string;
  operational_ms: number;
  eligible_ms: number;
  coverage_ms: number;
  unknown_ms: number;
  excluded_ms: number;
}
interface Hour {
  from: string;
  to: string;
  state: string;
}
function HistoryDrawer({ id, close }: { id: string; close(): void }) {
  const { client, revision, t, locale, run, busy } = useUI(),
    [exported, setExported] = useState("");
  const [range] = useState(
    () =>
      `?component_id=${encodeURIComponent(id)}&from=${encodeURIComponent(new Date(Date.now() - 7 * 86400000).toISOString())}&to=${encodeURIComponent(new Date().toISOString())}`,
  );
  const load = useCallback(async () => {
    const detail = await client.request<{ item: Component }>(
      "GET",
      "/v1/components/" + encodeURIComponent(id),
    );
    const [history, hourly] = await Promise.all([
      client.request<Page<History>>("GET", "/v1/history" + range),
      client.request<Page<Hour>>("GET", "/v1/history/hourly" + range),
    ]);
    return {
      component: detail.item,
      history: history.items,
      hourly: hourly.items,
    };
  }, [client, revision, id, range]);
  const { data, loading, error } = useResource(load, null);
  return (
    <Drawer
      open
      title={data?.component.label ?? t("history")}
      width={800}
      onClose={close}
    >
      {error ? (
        <Alert role="alert" type="error" title={error} />
      ) : !data ? (
        <Skeleton active loading={loading} />
      ) : (
        <Space direction="vertical" size={20} style={{ display: "flex" }}>
          <Typography.Title level={4}>{t("history")}</Typography.Title>
          <Typography.Paragraph type="secondary">
            {t("wholeHours")}
          </Typography.Paragraph>
          <div className="history-strip" aria-label={t("history")}>
            {data.hourly.map((hour, index) => (
              <span
                key={index}
                className={"hour " + safeState(hour.state)}
                role="img"
                tabIndex={0}
                title={`${date(hour.from, locale)} – ${date(hour.to, locale)}: ${t(safeState(hour.state))}`}
                aria-label={`${date(hour.from, locale)}: ${t(safeState(hour.state))}`}
              />
            ))}
          </div>
          <Table
            rowKey="monitor_id"
            pagination={false}
            dataSource={data.history}
            scroll={{ x: 500 }}
            columns={[
              {
                title: t("monitor"),
                dataIndex: "monitor_id",
                render: (value) =>
                  (data.component.monitors ?? []).find((m) => m.id === value)
                    ?.label ?? value.slice(0, 8),
              },
              {
                title: t("history"),
                render: (_, row) =>
                  percentage(row.operational_ms, row.eligible_ms) ??
                  t("noCoverage"),
              },
              ...(["coverage", "unknownTime", "excluded"] as const).map(
                (key, index) => ({
                  title: t(key),
                  render: (_: unknown, row: History) =>
                    Math.round(
                      [row.coverage_ms, row.unknown_ms, row.excluded_ms][
                        index
                      ] / 1000,
                    ) +
                    " " +
                    t("seconds"),
                }),
              ),
            ]}
          />
          <Typography.Title level={5}>{t("componentDetail")}</Typography.Title>
          {(data.component.monitors ?? []).map((m) => (
            <Card
              key={m.id}
              size="small"
              title={m.label}
              extra={<StateTag value={m.state} stale={m.stale} />}
            >
              <Descriptions
                size="small"
                column={1}
                items={[
                  {
                    key: "last",
                    label: t("lastSuccess"),
                    children: date(m.last_success_at, locale),
                  },
                  {
                    key: "next",
                    label: t("nextCheck"),
                    children: date(m.next_check_at, locale),
                  },
                  {
                    key: "latency",
                    label: t("latency"),
                    children:
                      m.measurements?.latency_ms == null
                        ? "—"
                        : m.measurements.latency_ms + " ms",
                  },
                ]}
              />
              {m.measurements?.balances && (
                <Collapse
                  items={[
                    {
                      key: "balances",
                      label: t("balances"),
                      children: (
                        <>
                          <Typography.Paragraph type="secondary">
                            {t("accountBalanceHint")}
                          </Typography.Paragraph>
                          <Table
                            rowKey="currency"
                            size="small"
                            pagination={false}
                            scroll={{ x: 500 }}
                            dataSource={m.measurements.balances}
                            columns={[
                              "currency",
                              "total",
                              "cash",
                              "credit",
                              "granted",
                              "topped_up",
                            ].map((key) => ({
                              title: t(key === "topped_up" ? "toppedUp" : key),
                              dataIndex: key,
                              render: (value) => value ?? "—",
                            }))}
                          />
                        </>
                      ),
                    },
                  ]}
                />
              )}
            </Card>
          ))}
          <Button
            disabled={busy}
            onClick={() =>
              run(async () => {
                const result = await client.request<{ item: unknown }>(
                  "GET",
                  "/v1/components/export" + range,
                );
                setExported(JSON.stringify(result.item, null, 2));
              }, "exportReady")
            }
          >
            {t("exportJSON")}
          </Button>
          {exported && (
            <Field
              label={t("exportJSON")}
              multiline
              value={exported}
              onChange={() => {}}
              help={t("exportCopyHint")}
            />
          )}
        </Space>
      )}
    </Drawer>
  );
}
function Incidents() {
  const { client, revision, t, locale } = useUI(),
    [offset, setOffset] = useState(0),
    [selected, setSelected] = useState<string | null>(null);
  const load = useCallback(
    () =>
      client.request<Page<Incident>>(
        "GET",
        `/v1/incidents?limit=50&offset=${offset}`,
      ),
    [client, revision, offset],
  );
  const { data, loading, error } = useResource(load, {
    items: [] as Incident[],
    total: 0,
  });
  return (
    <>
      {error ? (
        <Alert role="alert" title={error} type="error" />
      ) : loading ? (
        <Skeleton active />
      ) : !data.items.length ? (
        <Empty description={t("noIncidents")} />
      ) : (
        <Space direction="vertical" size={12} style={{ display: "flex" }}>
          {data.items.map((item) => (
            <Card
              key={item.id}
              title={item.summary}
              extra={<StateTag value={item.state} />}
            >
              <Typography.Paragraph type="secondary">
                {date(item.opened_at, locale)} →{" "}
                {date(item.resolved_at, locale)}
              </Typography.Paragraph>
              <Button onClick={() => setSelected(item.id)}>
                {t("history")}
              </Button>
            </Card>
          ))}
        </Space>
      )}
      <Pages offset={offset} total={data.total} change={setOffset} />
      {selected && (
        <IncidentDrawer id={selected} close={() => setSelected(null)} />
      )}
    </>
  );
}
function IncidentDrawer({ id, close }: { id: string; close(): void }) {
  const { client, revision, locale, t, run, busy, admin } = useUI(),
    [summary, setSummary] = useState(""),
    [published, setPublished] = useState(false);
  const load = useCallback(
    () =>
      client.request<{ item: Incident; admin?: boolean }>(
        "GET",
        "/v1/incidents/" + encodeURIComponent(id),
      ),
    [client, revision, id],
  );
  const { data, loading, error } = useResource(load, null);
  return (
    <Drawer
      open
      title={data?.item.summary ?? t("incidents")}
      width={680}
      onClose={close}
    >
      {error ? (
        <Alert role="alert" title={error} type="error" />
      ) : !data ? (
        <Skeleton active loading={loading} />
      ) : (
        <>
          {data.item.transitions?.map((tr, i) => (
            <Typography.Paragraph key={i}>
              {date(tr.occurred_at, locale)} · {tr.message}
            </Typography.Paragraph>
          ))}
          {admin && (
            <Collapse
              items={[
                {
                  key: "publication",
                  label: t("publishNarrative"),
                  children: (
                    <Form component="div" layout="vertical">
                      <Field
                        label={t("publicSummary")}
                        value={summary}
                        onChange={setSummary}
                      />
                      <Check checked={published} onChange={setPublished}>
                        {t("publishNarrative")}
                      </Check>
                      <Button
                        type="primary"
                        disabled={busy}
                        onClick={() =>
                          run(() =>
                            client.request(
                              "PUT",
                              "/v1/manage/incidents/publication",
                              {
                                id,
                                revision: data.item.revision,
                                summary,
                                enabled: published,
                              },
                            ),
                          )
                        }
                      >
                        {t("publish")}
                      </Button>
                    </Form>
                  ),
                },
              ]}
            />
          )}
        </>
      )}
    </Drawer>
  );
}
