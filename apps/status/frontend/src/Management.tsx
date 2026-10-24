import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Collapse,
  Empty,
  Flex,
  Form,
  Modal,
  Space,
  Table,
  Tabs,
  Tag,
  Typography,
} from "antd";
import { PlusOutlined, SettingOutlined } from "@ant-design/icons";
import type {
  Component,
  Credential,
  Operations,
  Page,
  Settings,
} from "./client";
import { ComponentEditor, freshMonitor } from "./ComponentEditor";
import { Check, Choice, Field, NumberField, useResource, useUI } from "./ui";

export function Management() {
  const { client, t, busy } = useUI(),
    [tab, setTab] = useState("components"),
    [listingRevision, setListingRevision] = useState(0),
    [editing, setEditing] = useState<Component | null>(null),
    [credential, setCredential] = useState<Credential | null>(null);
  const load = useCallback(async () => {
    const [components, credentials] = await Promise.all([
      client.request<Page<Component>>("GET", "/v1/manage/components"),
      client.request<Page<Credential>>("GET", "/v1/manage/credentials"),
    ]);
    return { components: components.items, credentials: credentials.items };
  }, [client, listingRevision]);
  const { data, loading, error } = useResource(load, {
    components: [] as Component[],
    credentials: [] as Credential[],
  });
  const fresh = (): Component => ({
    revision: 0,
    label: "",
    public_label: "",
    enabled: false,
    public_enabled: false,
    grants: [],
    monitors: [freshMonitor()],
  });
  return (
    <>
      <Tabs
        activeKey={tab}
        onChange={setTab}
        items={["components", "credentials", "operations"].map((key) => ({
          key,
          label: t(key),
        }))}
      />
      {error && <Alert type="error" role="alert" title={error} showIcon />}
      {tab === "components" && (
        <>
          <Flex
            justify="space-between"
            align="center"
            wrap
            gap={12}
            className="section-gap"
          >
            <Typography.Text type="secondary">
              {t("componentsHint")}
            </Typography.Text>
            <Button
              aria-label={t("newComponent")}
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => setEditing(fresh())}
            >
              {t("newComponent")}
            </Button>
          </Flex>
          <Table
            rowKey="id"
            loading={loading}
            pagination={false}
            dataSource={data.components}
            scroll={{ x: 560 }}
            columns={[
              {
                title: t("component"),
                dataIndex: "label",
                render: (label, value) => (
                  <Space direction="vertical" size={0}>
                    <Typography.Text strong>{label}</Typography.Text>
                    <Typography.Text type="secondary">
                      {(value.monitors ?? []).length} {t("checksCount")}
                    </Typography.Text>
                  </Space>
                ),
              },
              {
                title: t("state"),
                render: (_, value) => (
                  <Tag color={value.enabled ? "processing" : "default"}>
                    {t(value.enabled ? "enabled" : "paused")}
                  </Tag>
                ),
              },
              {
                title: t("visibilityStep"),
                render: (_, value) => (
                  <Tag>
                    {t(
                      (value.grants ?? []).some((g) => g.permission === "read")
                        ? "customAudience"
                        : "adminOnly",
                    )}
                  </Tag>
                ),
              },
              {
                title: t("manage"),
                render: (_, value) => (
                  <Button type="link" onClick={() => setEditing(value)}>
                    {t("edit")}
                  </Button>
                ),
              },
            ]}
          />
        </>
      )}
      {tab === "credentials" && (
        <>
          <Flex
            justify="space-between"
            align="center"
            wrap
            gap={12}
            className="section-gap"
          >
            <Typography.Text type="secondary">
              {t("secretHint")}
            </Typography.Text>
            <Button
              aria-label={t("newCredential")}
              type="primary"
              icon={<PlusOutlined />}
              onClick={() =>
                setCredential({ label: "", kind: "deepseek", revision: 0 })
              }
            >
              {t("newCredential")}
            </Button>
          </Flex>
          <Table
            rowKey="id"
            loading={loading}
            pagination={false}
            dataSource={data.credentials}
            columns={[
              { title: t("name"), dataIndex: "label" },
              {
                title: t("kind"),
                dataIndex: "kind",
                render: (kind) => t(kind),
              },
              {
                title: t("manage"),
                render: (_, value) => (
                  <Button type="link" onClick={() => setCredential(value)}>
                    {t("edit")}
                  </Button>
                ),
              },
            ]}
          />
        </>
      )}
      {tab === "operations" && (
        <OperationsView
          components={data.components}
          credentials={data.credentials}
        />
      )}
      {editing && (
        <ComponentEditor
          value={editing}
          credentials={data.credentials}
          close={() => {
            if (!busy) {
              setEditing(null);
              setListingRevision((value) => value + 1);
            }
          }}
        />
      )}
      {credential && (
        <CredentialEditor
          value={credential}
          close={() => {
            if (!busy) {
              setCredential(null);
              setListingRevision((value) => value + 1);
            }
          }}
        />
      )}
    </>
  );
}

function CredentialEditor({
  value,
  close,
}: {
  value: Credential;
  close(): void;
}) {
  const { client, t, run, busy, error } = useUI(),
    [draft, setDraft] = useState(value),
    [secret, setSecret] = useState<Record<string, string>>({}),
    [confirmDelete, setConfirmDelete] = useState(false);
  const fields =
    draft.kind === "postgres"
      ? ["username", "password"]
      : draft.kind === "qwen"
        ? ["access_key_id", "access_key_secret", "security_token"]
        : draft.kind === "notification"
          ? ["token"]
          : ["api_key"];
  const labels: Record<string, string> = {
    username: "username",
    password: "password",
    access_key_id: "accessID",
    access_key_secret: "accessSecret",
    security_token: "securityToken",
    token: "notificationToken",
    api_key: "apiKey",
  };
  const save = async () => {
    const values = Object.fromEntries(
      fields.filter((key) => secret[key]).map((key) => [key, secret[key]]),
    );
    if (
      await run(() =>
        client.request("PUT", "/v1/manage/credentials", {
          ...draft,
          ...(Object.keys(values).length ? { secret: values } : {}),
        }),
      )
    ) {
      setSecret({});
      close();
    }
  };
  return (
    <Modal
      title={t(value.id ? "edit" : "newCredential")}
      open
      onCancel={close}
      footer={
        <Flex justify="space-between" gap={8} wrap>
          {value.id ? (
            <Button
              danger
              onClick={() => setConfirmDelete(true)}
              disabled={busy}
            >
              {t("delete")}
            </Button>
          ) : (
            <span />
          )}
          <Space>
            <Button onClick={close} disabled={busy}>
              {t("cancel")}
            </Button>
            <Button
              type="primary"
              loading={busy}
              disabled={busy}
              onClick={save}
            >
              {t("save")}
            </Button>
          </Space>
        </Flex>
      }
      destroyOnHidden
    >
      {error && (
        <div tabIndex={-1} data-app-error className="section-gap">
          <Alert role="alert" type="error" title={error} showIcon />
        </div>
      )}
      <Form component="div" layout="vertical" disabled={busy}>
        <Field
          label={t("name")}
          value={draft.label}
          onChange={(label) => setDraft({ ...draft, label })}
        />
        <Choice
          label={t("kind")}
          value={draft.kind}
          disabled={!!value.id}
          options={[
            "http",
            "dify",
            "postgres",
            "deepseek",
            "qwen",
            "heartbeat",
            "notification",
          ].map((value) => ({ value, label: t(value) }))}
          onChange={(kind) => {
            setDraft({ ...draft, kind: String(kind) });
            setSecret({});
          }}
        />
        <Typography.Paragraph type="secondary">
          {t("secretHint")}
        </Typography.Paragraph>
        {fields.map((key) => (
          <Field
            key={key}
            label={t(labels[key])}
            value={secret[key]}
            secret={key !== "username"}
            onChange={(value) => setSecret({ ...secret, [key]: value })}
          />
        ))}
      </Form>
      <Modal
        open={confirmDelete}
        title={t("deleteApproval")}
        onCancel={() => setConfirmDelete(false)}
        onOk={() =>
          run(async () => {
            await client.request("DELETE", "/v1/manage/credentials", {
              id: value.id,
              revision: value.revision,
            });
            setSecret({});
            close();
          })
        }
        okButtonProps={{ danger: true, loading: busy }}
      >
        {t("credentialDeleteHint")}
      </Modal>
    </Modal>
  );
}

function OperationsView({
  components,
  credentials,
}: {
  components: Component[];
  credentials: Credential[];
}) {
  const { client, t, revision, busy, run } = useUI(),
    [resume, setResume] = useState(false);
  const load = useCallback(
    () => client.request<Operations>("GET", "/v1/manage/operations"),
    [client, revision],
  );
  const { data, loading, error } = useResource<Operations | null>(load, null);
  if (error) return <Alert type="error" title={error} role="alert" showIcon />;
  if (!data) return <Card loading={loading} />;
  return (
    <Space direction="vertical" size={16} style={{ display: "flex" }}>
      <div className="status-grid">
        <Card
          size="small"
          title={t("checksStep")}
          extra={
            <Tag color={data.settings.probes_paused ? "default" : "processing"}>
              {t(data.settings.probes_paused ? "paused" : "enabled")}
            </Tag>
          }
        >
          <Typography.Paragraph type="secondary">
            {t("probeControlHint")}
          </Typography.Paragraph>
          {data.settings.probes_paused ? (
            <Button onClick={() => setResume(true)}>{t("reviewResume")}</Button>
          ) : (
            <Button
              onClick={() =>
                run(() =>
                  client.request("PUT", "/v1/manage/settings", {
                    ...data.settings,
                    probes_paused: true,
                  }),
                )
              }
              disabled={busy}
            >
              {t("probesPaused")}
            </Button>
          )}
        </Card>
        <Card
          size="small"
          title={t("notification")}
          extra={
            <Tag>{t(data.settings.outbox_paused ? "paused" : "enabled")}</Tag>
          }
        >
          <Typography.Paragraph type="secondary">
            {t("notificationControlHint")}
          </Typography.Paragraph>
          {data.settings.outbox_paused ? (
            <Button onClick={() => setResume(true)}>{t("reviewResume")}</Button>
          ) : (
            <Button
              onClick={() =>
                run(() =>
                  client.request("PUT", "/v1/manage/settings", {
                    ...data.settings,
                    outbox_paused: true,
                  }),
                )
              }
              disabled={busy}
            >
              {t("outboxPaused")}
            </Button>
          )}
        </Card>
      </div>
      {data.outbox.length > 0 && (
        <Card
          title={t("outbox")}
          extra={
            <Button onClick={() => setResume(true)}>{t("reviewResume")}</Button>
          }
        >
          <Outbox data={data} />
        </Card>
      )}
      <Collapse
        items={[
          {
            key: "settings",
            label: (
              <Space>
                <SettingOutlined />
                {t("serviceSettings")}
              </Space>
            ),
            children: <SettingsEditor value={data.settings} />,
          },
          {
            key: "publishers",
            label: t("publishers"),
            children: components.length ? (
              <PublisherEditor
                data={data}
                components={components}
                credentials={credentials}
              />
            ) : (
              <Empty description={t("configureFirst")} />
            ),
          },
          {
            key: "maintenance",
            label: t("scheduleMaintenance"),
            children: components.length ? (
              <MaintenanceEditor components={components} />
            ) : (
              <Empty description={t("configureFirst")} />
            ),
          },
        ]}
      />
      {resume && <ResumeDialog data={data} close={() => setResume(false)} />}
    </Space>
  );
}
function ResumeDialog({ data, close }: { data: Operations; close(): void }) {
  const { client, t, run, busy, error } = useUI(),
    [probes, setProbes] = useState(false),
    [outbox, setOutbox] = useState(false),
    [reviewed, setReviewed] = useState(false);
  return (
    <Modal
      open
      title={t("reviewResume")}
      onCancel={close}
      footer={
        <Space>
          <Button onClick={close}>{t("cancel")}</Button>
          <Button
            type="primary"
            loading={busy}
            disabled={!reviewed || (!probes && !outbox) || busy}
            onClick={async () => {
              if (
                await run(() =>
                  client.request("POST", "/v1/manage/resume", {
                    queue_fingerprint: data.queue_fingerprint,
                    probes,
                    outbox,
                  }),
                )
              )
                close();
            }}
          >
            {t("resumeSelected")}
          </Button>
        </Space>
      }
    >
      {error && (
        <div tabIndex={-1} data-app-error className="section-gap">
          <Alert role="alert" type="error" title={error} showIcon />
        </div>
      )}
      <Typography.Paragraph>{t("resumeHint")}</Typography.Paragraph>
      <Check checked={probes} onChange={setProbes}>
        {t("resumeProbes")}
      </Check>
      <Check checked={outbox} onChange={setOutbox}>
        {t("resumeOutbox")}
      </Check>
      <Outbox data={data} />
      <Check checked={reviewed} onChange={setReviewed}>
        {t("reviewed")}
      </Check>
      <Collapse
        size="small"
        items={[
          {
            key: "fingerprint",
            label: t("technicalDetails"),
            children: (
              <Typography.Text code style={{ overflowWrap: "anywhere" }}>
                {data.queue_fingerprint}
              </Typography.Text>
            ),
          },
        ]}
      />
    </Modal>
  );
}
function Outbox({ data }: { data: Operations }) {
  const { t, client, run, busy } = useUI(),
    [reviewed, setReviewed] = useState(false);
  if (!data.outbox.length)
    return (
      <Typography.Paragraph type="secondary">
        {t("emptyOutbox")}
      </Typography.Paragraph>
    );
  return (
    <>
      <Table
        rowKey="id"
        pagination={false}
        scroll={{ x: 460 }}
        dataSource={data.outbox}
        columns={[
          {
            title: t("component"),
            dataIndex: "component_id",
            render: (value) => value.slice(0, 8),
          },
          {
            title: t("state"),
            dataIndex: "state",
            render: (value) => t(value === "retry" ? "retryState" : value),
          },
          { title: t("attempts"), dataIndex: "attempts" },
          { title: t("reason"), dataIndex: "last_error" },
          {
            title: t("manage"),
            render: (_, notice) =>
              notice.state === "review_required" && (
                <Space wrap>
                  {["discard", "retry"].map((action) => (
                    <Button
                      key={action}
                      disabled={!reviewed || busy}
                      onClick={() =>
                        run(() =>
                          client.request("POST", "/v1/manage/outbox/review", {
                            id: notice.id,
                            queue_fingerprint: data.queue_fingerprint,
                            action:
                              action === "discard"
                                ? "discard"
                                : "retry_same_publisher",
                          }),
                        )
                      }
                    >
                      {t(action)}
                    </Button>
                  ))}
                </Space>
              ),
          },
        ]}
      />
      <Check checked={reviewed} onChange={setReviewed}>
        {t("reviewed")}
      </Check>
    </>
  );
}
function SettingsEditor({ value }: { value: Settings }) {
  const { client, t, run, busy } = useUI(),
    [draft, setDraft] = useState(value);
  useEffect(() => {
    setDraft(value);
  }, [value]);
  return (
    <Form component="div" layout="vertical" disabled={busy}>
      <Typography.Paragraph type="secondary">
        {t("publicHint")}
      </Typography.Paragraph>
      <Check
        checked={draft.public_enabled}
        onChange={(public_enabled) => setDraft({ ...draft, public_enabled })}
      >
        {t("publicEnabled")}
      </Check>
      <Field
        label={t("portalURL")}
        value={draft.portal_url}
        onChange={(portal_url) => setDraft({ ...draft, portal_url })}
      />
      <Field
        label={t("portalNetworks")}
        multiline
        value={draft.portal_networks.join("\n")}
        onChange={(v) =>
          setDraft({
            ...draft,
            portal_networks: v.split(/\s+/).filter(Boolean),
          })
        }
      />
      <div className="field-grid">
        <NumberField
          label={t("rawRetention")}
          value={draft.raw_retention_days}
          min={1}
          max={30}
          onChange={(raw_retention_days) =>
            setDraft({ ...draft, raw_retention_days })
          }
        />
        <NumberField
          label={t("historyRetention")}
          value={draft.history_retention_days}
          min={draft.raw_retention_days}
          max={90}
          onChange={(history_retention_days) =>
            setDraft({ ...draft, history_retention_days })
          }
        />
      </div>
      <Typography.Paragraph type="secondary">
        {t("retentionHint")}
      </Typography.Paragraph>
      <Button
        type="primary"
        loading={busy}
        onClick={() =>
          run(() => client.request("PUT", "/v1/manage/settings", draft))
        }
      >
        {t("save")}
      </Button>
    </Form>
  );
}
function PublisherEditor({
  data,
  components,
  credentials,
}: {
  data: Operations;
  components: Component[];
  credentials: Credential[];
}) {
  const { t, client, run, busy } = useUI(),
    [id, setId] = useState(components[0].id!),
    prior = data.publishers.find((p) => p.component_id === id),
    [credential, setCredential] = useState(prior?.credential_id ?? ""),
    [enabled, setEnabled] = useState(prior?.enabled ?? false);
  const choose = (id: string) => {
    setId(id);
    const p = data.publishers.find((p) => p.component_id === id);
    setCredential(p?.credential_id ?? "");
    setEnabled(p?.enabled ?? false);
  };
  return (
    <Form component="div" layout="vertical" disabled={busy}>
      <Typography.Paragraph type="secondary">
        {t("publisherHint")}
      </Typography.Paragraph>
      <Choice
        label={t("component")}
        value={id}
        options={components.map((c) => ({ value: c.id!, label: c.label }))}
        onChange={(v) => choose(String(v))}
      />
      <Typography.Paragraph code>{"notify:status-" + id}</Typography.Paragraph>
      <Choice
        label={t("credential")}
        value={credential}
        options={[
          { value: "", label: t("none") },
          ...credentials
            .filter((c) => c.kind === "notification")
            .map((c) => ({ value: c.id!, label: c.label })),
        ]}
        onChange={(v) => setCredential(String(v))}
      />
      <Check checked={enabled} onChange={setEnabled}>
        {t("enabled")}
      </Check>
      <Button
        type="primary"
        loading={busy}
        onClick={() =>
          run(() =>
            client.request("PUT", "/v1/manage/publishers", {
              component_id: id,
              publisher_name: "status-" + id,
              credential_id: credential,
              enabled,
              revision: prior?.revision ?? 0,
            }),
          )
        }
      >
        {t("save")}
      </Button>
    </Form>
  );
}
function MaintenanceEditor({ components }: { components: Component[] }) {
  const { t, client, run, busy } = useUI(),
    [component, setComponent] = useState(components[0].id!),
    [start, setStart] = useState(new Date().toISOString()),
    [end, setEnd] = useState(new Date(Date.now() + 3600000).toISOString()),
    [summary, setSummary] = useState("");
  return (
    <Form component="div" layout="vertical" disabled={busy}>
      <Choice
        label={t("component")}
        value={component}
        options={components.map((c) => ({ value: c.id!, label: c.label }))}
        onChange={(v) => setComponent(String(v))}
      />
      <Field label={t("maintenanceStart")} value={start} onChange={setStart} />
      <Field label={t("maintenanceEnd")} value={end} onChange={setEnd} />
      <Field label={t("summary")} value={summary} onChange={setSummary} />
      <Button
        type="primary"
        loading={busy}
        onClick={() =>
          run(() =>
            client.request("POST", "/v1/manage/maintenance", {
              component_id: component,
              starts_at: start,
              ends_at: end,
              summary,
            }),
          )
        }
      >
        {t("scheduleMaintenance")}
      </Button>
    </Form>
  );
}
