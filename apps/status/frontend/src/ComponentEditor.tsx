import { useState } from "react";
import {
  Alert,
  Button,
  Card,
  Collapse,
  Drawer,
  Flex,
  Form,
  Space,
  Steps,
  Typography,
} from "antd";
import { PlusOutlined } from "@ant-design/icons";
import type { Component, Credential, Monitor, Page, Principal } from "./client";
import { Check, Choice, Field, NumberField, useUI } from "./ui";

export const freshMonitor = (): Monitor => ({
  kind: "http",
  label: "HTTP",
  enabled: true,
  interval_seconds: 60,
  timeout_seconds: 5,
  config: { version: 1 },
});
export function serializeMonitor(m: Monitor): Monitor {
  const c = m.config,
    config: Record<string, unknown> = { version: 1 };
  if (["http", "dify"].includes(m.kind))
    Object.assign(config, {
      url: c.url ?? "",
      networks: c.networks ?? [],
      plain_http: c.plain_http === true,
    });
  if (m.kind === "http")
    Object.assign(config, {
      expected_status: c.expected_status ?? 0,
      body_contains: c.body_contains ?? "",
    });
  if (m.kind === "postgres") {
    Object.assign(config, {
      postgres_transport: c.postgres_transport ?? "tls",
      port: c.port ?? 5432,
      database: c.database ?? "",
    });
    if (config.postgres_transport !== "unix")
      Object.assign(config, { host: c.host ?? "", networks: c.networks ?? [] });
  }
  if (["deepseek", "qwen"].includes(m.kind))
    Object.assign(config, {
      account_ref: c.account_ref ?? "",
      currency: c.currency ?? "CNY",
      low_balance: c.low_balance ?? "",
      recovery_balance: c.recovery_balance ?? "",
    });
  if (m.kind === "qwen") config.site = c.site ?? "china";
  return {
    id: m.id,
    label: m.label,
    kind: m.kind,
    credential_id: m.credential_id ?? "",
    enabled: m.enabled,
    interval_seconds: m.interval_seconds,
    timeout_seconds: m.timeout_seconds,
    config,
  };
}
export function ComponentEditor({
  value,
  credentials,
  close,
}: {
  value: Component;
  credentials: Credential[];
  close(): void;
}) {
  const { client, t, busy, run, error } = useUI(),
    [draft, setDraft] = useState<Component>(() =>
      structuredClone({
        ...value,
        monitors: value.monitors ?? [],
        grants: value.grants ?? [],
      }),
    ),
    [step, setStep] = useState(0),
    [directory, setDirectory] = useState<Principal[]>([]),
    [offset, setOffset] = useState(0),
    [validation, setValidation] = useState("");
  const update = (patch: Partial<Component>) =>
    setDraft((old) => ({ ...old, ...patch }));
  const updateMonitor = (index: number, m: Monitor) =>
    update({
      monitors: draft.monitors.map((prior, i) => (i === index ? m : prior)),
    });
  const advance = () => {
    if (!draft.label.trim()) {
      setStep(0);
      setValidation(t("requiredName"));
      return;
    }
    if (
      step === 1 &&
      draft.monitors.some(
        (m) =>
          !m.label.trim() ||
          (["http", "dify"].includes(m.kind) &&
            !/^https?:\/\//.test(String(m.config.url ?? ""))),
      )
    ) {
      setValidation(t("invalidConfiguration"));
      return;
    }
    setValidation("");
    setStep(step + 1);
  };
  const save = async () => {
    if (
      await run(() =>
        client.request("PUT", "/v1/manage/components", {
          ...draft,
          monitors: draft.monitors.map(serializeMonitor),
        }),
      )
    )
      close();
  };
  const loadDirectory = () =>
    run(async () => {
      const pages = await Promise.all(
        ["ou", "user"].map((kind) =>
          client.directory<Page<Principal>>(kind as "ou" | "user", offset),
        ),
      );
      setDirectory((old) => [
        ...new Map(
          [...old, ...pages.flatMap((page) => page.items)].map((item) => [
            item.principal,
            item,
          ]),
        ).values(),
      ]);
      setOffset(offset + 100);
    }, "");
  const grantOptions = [
    ...new Map([
      ...directory.map((p) => [p.principal, p.label] as const),
      ...draft.grants
        .filter((g) => !directory.some((p) => p.principal === g.principal))
        .map((g) => [g.principal, g.principal] as const),
    ]).entries(),
  ].map(([value, label]) => ({ value, label }));
  const setGrants = (permission: string, values: string[]) =>
    update({
      grants: [
        ...draft.grants.filter((g) => g.permission !== permission),
        ...values.map((principal) => ({ principal, permission })),
      ],
    });
  return (
    <Drawer
      title={t(value.id ? "edit" : "newComponent")}
      open
      width={720}
      onClose={close}
      destroyOnHidden
      footer={
        <Flex justify="space-between" gap={8} wrap>
          <Button onClick={close} disabled={busy}>
            {t("cancel")}
          </Button>
          <Space>
            {step > 0 && (
              <Button onClick={() => setStep(step - 1)} disabled={busy}>
                {t("previous")}
              </Button>
            )}
            {step < 2 ? (
              <Button type="primary" onClick={advance}>
                {t("next")}
              </Button>
            ) : (
              <Button
                type="primary"
                onClick={save}
                aria-label={t("save")}
                loading={busy}
                disabled={busy}
              >
                {t("save")}
              </Button>
            )}
          </Space>
        </Flex>
      }
    >
      <Steps
        current={step}
        size="small"
        items={["basicStep", "checksStep", "visibilityStep"].map((key) => ({
          title: t(key),
        }))}
      />
      {(validation || error) && (
        <div tabIndex={-1} data-app-error className="section-gap">
          <Alert
            type="error"
            role="alert"
            title={validation || error}
            showIcon
          />
        </div>
      )}
      <Form
        component="div"
        layout="vertical"
        disabled={busy}
        className="section-gap"
        onKeyDown={(event) => {
          if (
            event.key === "Enter" &&
            (event.target as HTMLElement).tagName === "INPUT"
          ) {
            event.preventDefault();
            if (step < 2) advance();
            else void save();
          }
        }}
      >
        {step === 0 && (
          <>
            <Field
              label={t("name")}
              value={draft.label}
              onChange={(label) => update({ label })}
            />
            <Check
              checked={draft.enabled}
              onChange={(enabled) => update({ enabled })}
            >
              {t("enabled")}
            </Check>
            <Typography.Paragraph type="secondary">
              {t("privateDefaultHint")}
            </Typography.Paragraph>
          </>
        )}
        {step === 1 && (
          <>
            <Typography.Paragraph type="secondary">
              {t("checksHint")}
            </Typography.Paragraph>
            {draft.monitors.map((m, index) => (
              <MonitorEditor
                key={m.id ?? index}
                value={m}
                credentials={credentials}
                onChange={(m) => updateMonitor(index, m)}
              />
            ))}
            <Button
              aria-label={t("addMonitor")}
              icon={<PlusOutlined />}
              onClick={() =>
                update({ monitors: [...draft.monitors, freshMonitor()] })
              }
            >
              {t("addMonitor")}
            </Button>
          </>
        )}
        {step === 2 && (
          <>
            <Alert type="info" title={t("privateDefaultHint")} showIcon />
            <div className="section-gap">
              <Button onClick={loadDirectory} loading={busy}>
                {t(offset ? "directoryMore" : "loadDirectory")}
              </Button>
            </div>
            <Choice
              label={t("readGrants")}
              multiple
              value={draft.grants
                .filter((g) => g.permission === "read")
                .map((g) => g.principal)}
              options={grantOptions}
              onChange={(v) => setGrants("read", v as string[])}
              help={t("grantHint")}
            />
            <Collapse
              items={[
                {
                  key: "finance",
                  label: t("financeGrants"),
                  children: (
                    <Choice
                      label={t("financeGrants")}
                      multiple
                      value={draft.grants
                        .filter((g) => g.permission === "finance")
                        .map((g) => g.principal)}
                      options={grantOptions.filter((o) =>
                        draft.grants.some(
                          (g) =>
                            g.principal === o.value && g.permission === "read",
                        ),
                      )}
                      onChange={(v) => setGrants("finance", v as string[])}
                    />
                  ),
                },
                {
                  key: "public",
                  label: t("publicOptions"),
                  children: (
                    <>
                      <Check
                        checked={draft.public_enabled}
                        onChange={(public_enabled) =>
                          update({ public_enabled })
                        }
                      >
                        {t("publicComponent")}
                      </Check>
                      <Field
                        label={t("publicLabel")}
                        value={draft.public_label}
                        onChange={(public_label) => update({ public_label })}
                        help={t("publicHint")}
                      />
                    </>
                  ),
                },
              ]}
            />
          </>
        )}
      </Form>
    </Drawer>
  );
}

function MonitorEditor({
  value: m,
  credentials,
  onChange,
}: {
  value: Monitor;
  credentials: Credential[];
  onChange(m: Monitor): void;
}) {
  const { t, busy, client, run } = useUI(),
    c = m.config;
  const set = (patch: Partial<Monitor>) => onChange({ ...m, ...patch });
  const config = (patch: Record<string, unknown>) =>
    set({ config: { ...c, ...patch } });
  const field = (key: string, configKey: string, help?: string) => (
    <Field
      label={t(key)}
      value={String(c[configKey] ?? "")}
      onChange={(v) => config({ [configKey]: v })}
      help={help}
    />
  );
  const networks = (
    <Field
      label={t("networks")}
      multiline
      value={((c.networks as string[]) ?? []).join("\n")}
      onChange={(v) => config({ networks: v.split(/\s+/).filter(Boolean) })}
    />
  );
  return (
    <fieldset className="monitor-editor">
      <legend>{t("monitor")}</legend>
      <Card size="small" className="section-gap">
        <Field
          label={t("name")}
          value={m.label}
          onChange={(label) => set({ label })}
        />
        <Choice
          label={t("kind")}
          value={m.kind}
          options={[
            "http",
            "dify",
            "postgres",
            "deepseek",
            "qwen",
            "heartbeat",
          ].map((value) => ({ value, label: t(value) }))}
          onChange={(kind) =>
            set({
              kind: String(kind),
              credential_id: "",
              interval_seconds: ["deepseek", "qwen"].includes(String(kind))
                ? 300
                : 60,
              timeout_seconds: ["deepseek", "qwen"].includes(String(kind))
                ? 10
                : 5,
            })
          }
        />
        <Choice
          label={t("credential")}
          value={m.credential_id ?? ""}
          options={[
            { value: "", label: t("none") },
            ...credentials
              .filter((cred) => cred.kind === m.kind)
              .map((cred) => ({ value: cred.id!, label: cred.label })),
          ]}
          onChange={(v) => set({ credential_id: String(v) })}
          help={
            credentials.some((cred) => cred.kind === m.kind) ||
            m.kind === "http"
              ? undefined
              : t("credentialSetupHint")
          }
        />
        {["http", "dify"].includes(m.kind) &&
          field(
            "url",
            "url",
            m.kind === "dify" ? t("difyReadHint") : undefined,
          )}
        {m.kind === "postgres" && (
          <>
            <Choice
              label={t("postgresConnection")}
              value={String(c.postgres_transport ?? "tls")}
              options={["tls", "unix"].map((value) => ({
                value,
                label: t(value === "tls" ? "postgresTLS" : "postgresUnix"),
              }))}
              onChange={(v) => config({ postgres_transport: v })}
            />
            {c.postgres_transport === "unix" ? (
              <Typography.Paragraph type="secondary">
                {t("postgresUnixHint")}
              </Typography.Paragraph>
            ) : (
              field("host", "host")
            )}
            {field("database", "database")}
          </>
        )}
        {["deepseek", "qwen"].includes(m.kind) && (
          <>
            <Typography.Paragraph type="secondary">
              {t("accountBalanceHint")}
            </Typography.Paragraph>
            {field("accountRef", "account_ref", t("accountRefHint"))}
            <Choice
              label={t("currency")}
              value={String(c.currency ?? "CNY")}
              options={["CNY", "USD"].map((value) => ({ value, label: value }))}
              onChange={(v) => config({ currency: v })}
            />
            {field("low", "low_balance")}
            {field("recovery", "recovery_balance")}
          </>
        )}
        {m.kind === "qwen" && (
          <Choice
            label={t("site")}
            value={String(c.site ?? "china")}
            options={["china", "international"].map((value) => ({
              value,
              label: t(value),
            }))}
            onChange={(v) => config({ site: v })}
          />
        )}
        <Collapse
          size="small"
          items={[
            {
              key: "advanced",
              label: t("advancedOptions"),
              children: (
                <>
                  <div className="field-grid">
                    <NumberField
                      label={t("interval")}
                      value={m.interval_seconds}
                      min={30}
                      max={86400}
                      onChange={(interval_seconds) => set({ interval_seconds })}
                    />
                    <NumberField
                      label={t("timeout")}
                      value={m.timeout_seconds}
                      min={1}
                      max={15}
                      onChange={(timeout_seconds) => set({ timeout_seconds })}
                    />
                  </div>
                  {["http", "dify"].includes(m.kind) && (
                    <>
                      {networks}
                      <Check
                        checked={c.plain_http === true}
                        onChange={(plain_http) => config({ plain_http })}
                      >
                        {t("plainHTTP")}
                      </Check>
                    </>
                  )}
                  {m.kind === "http" && (
                    <>
                      <NumberField
                        label={t("expectedStatus")}
                        value={Number(c.expected_status ?? 0)}
                        min={0}
                        max={599}
                        onChange={(expected_status) =>
                          config({ expected_status })
                        }
                      />
                      {field("bodyContains", "body_contains")}
                      <Typography.Paragraph type="secondary">
                        {t("httpConditionHint")}
                      </Typography.Paragraph>
                    </>
                  )}
                  {m.kind === "postgres" && (
                    <>
                      <NumberField
                        label={t("port")}
                        value={Number(c.port ?? 5432)}
                        min={1}
                        max={65535}
                        onChange={(port) => config({ port })}
                      />
                      {c.postgres_transport !== "unix" && networks}
                    </>
                  )}
                </>
              ),
            },
          ]}
        />
        <div className="section-gap">
          <Check checked={m.enabled} onChange={(enabled) => set({ enabled })}>
            {t("enabled")}
          </Check>
          {m.id && (
            <Button
              disabled={busy}
              onClick={() =>
                run(
                  () =>
                    client.request("POST", "/v1/manage/probes/request", {
                      id: m.id,
                      revision: m.revision,
                    }),
                  "checkQueued",
                )
              }
            >
              {t("checkNow")}
            </Button>
          )}
        </div>
      </Card>
    </fieldset>
  );
}
