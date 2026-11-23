import { useCallback, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import {
  Alert,
  Button,
  Card,
  Collapse,
  ConfigProvider,
  Empty,
  Modal,
  Space,
  Spin,
  Tag,
} from "antd";
import { useAppDraft, useAppPage } from "@portal-app/sdk/root-v2";
import {
  useApi,
  type AdminJob,
  type AdminJobs,
  type AdminLog,
  type AdminRun,
  type AdminRuns,
  type AdminSlot,
  type RunNowResult,
} from "../lib/api";
import { useCopy, type Copy } from "../lib/copy";
import { DASH, fill } from "../lib/format";
import { useMediaQuery } from "../lib/hooks";

// The admin view of the app: scheduled jobs, a manual "Run now" and the run
// history with each run's log. The backend serves these routes only to an
// admin-surface assertion; this page only decides what to draw.

const HISTORY_STEP = 20;
const WEEKDAYS = [
  "Sunday",
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
];

type Phase<T> =
  | { phase: "loading" }
  | { phase: "ok"; data: T }
  | { phase: "error" };

/** Loads one admin route; `revision` or `reload` fetch it again, keeping the old data meanwhile. */
function useAdminResource<T>(path: string, revision: number) {
  const { get, ready } = useApi();
  const [state, setState] = useState<Phase<T>>({ phase: "loading" });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!ready) return;
    const abort = new AbortController();
    get<T>(path, {}, abort.signal).then((result) => {
      if (abort.signal.aborted) return;
      setState(
        result.status === "ok"
          ? { phase: "ok", data: result.data }
          : { phase: "error" },
      );
    });
    return () => abort.abort();
  }, [get, ready, path, revision, attempt]);
  const reload = useCallback(() => {
    setState((current) =>
      current.phase === "ok" ? current : { phase: "loading" },
    );
    setAttempt((n) => n + 1);
  }, []);
  return { state, reload };
}

function formatTime(value: string | undefined, locale: string, zone: string) {
  if (!value) return DASH;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  try {
    return new Intl.DateTimeFormat(locale, {
      dateStyle: "medium",
      timeStyle: "short",
      timeZone: zone,
    }).format(date);
  } catch {
    return value;
  }
}

const pad = (n: number) => String(n).padStart(2, "0");

/** "Mon–Fri 21:00", or "Mon, Wed 09:00" when the days are not consecutive. */
export function formatSlot(slot: AdminSlot, locale: string): string {
  const indexes = slot.days
    .map((day) => WEEKDAYS.indexOf(day))
    .filter((i) => i >= 0)
    .sort((a, b) => a - b);
  // 2026-11-15 is a Sunday.
  const name = (i: number) =>
    new Intl.DateTimeFormat(locale, {
      weekday: "short",
      timeZone: "UTC",
    }).format(new Date(Date.UTC(2026, 10, 15 + i)));
  const consecutive =
    indexes.length > 2 &&
    indexes.every((value, i) => i === 0 || value === indexes[i - 1] + 1);
  const days = consecutive
    ? `${name(indexes[0])}–${name(indexes[indexes.length - 1])}`
    : indexes.map(name).join(", ");
  return `${days} ${pad(slot.hour)}:${pad(slot.minute)}`;
}

const STATUS_TONE: Record<string, string> = {
  succeeded: "success",
  failed: "error",
  running: "processing",
  queued: "default",
  interrupted: "warning",
};

/** Status is a word, an icon and a colour, so it never relies on colour alone. */
function StatusIcon({ status }: { status: string }) {
  const common = {
    width: 12,
    height: 12,
    viewBox: "0 0 12 12",
    "aria-hidden": true,
    focusable: false,
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.6,
    strokeLinecap: "round",
    strokeLinejoin: "round",
  } as const;
  switch (status) {
    case "succeeded":
      return (
        <svg {...common}>
          <path d="M2 6.5 5 9l5-6" />
        </svg>
      );
    case "failed":
      return (
        <svg {...common}>
          <path d="M3 3l6 6M9 3 3 9" />
        </svg>
      );
    case "running":
      return (
        <svg {...common}>
          <path d="M6 1.5a4.5 4.5 0 1 0 4.5 4.5" />
        </svg>
      );
    case "interrupted":
      return (
        <svg {...common}>
          <path d="M4 2.5v7M8 2.5v7" />
        </svg>
      );
    default:
      return (
        <svg {...common}>
          <circle cx="6" cy="6" r="4.5" />
          <path d="M6 3.5V6l1.8 1" />
        </svg>
      );
  }
}

function StatusTag({ status, copy }: { status: string; copy: Copy }) {
  return (
    <Tag
      color={STATUS_TONE[status] ?? "default"}
      icon={<StatusIcon status={status} />}
      style={{ marginInlineEnd: 0 }}
    >
      {copy[`run_${status}` as "run_queued"] ?? status}
    </Tag>
  );
}

function sourceLabel(copy: Copy, source: string) {
  return copy[`run_source_${source}` as "run_source_manual"] ?? source;
}

function usePrefersReducedMotion() {
  return useMediaQuery("(prefers-reduced-motion: reduce)");
}

function LoadState<T>({
  state,
  reload,
  children,
}: {
  state: Phase<T>;
  reload: () => void;
  children: (data: T) => ReactNode;
}) {
  const { copy } = useCopy();
  if (state.phase === "loading") return <Spin aria-label={copy.loading} />;
  if (state.phase === "error")
    return (
      <Alert
        type="error"
        showIcon
        title={copy.admin_loadFailed}
        action={
          <Button size="small" onClick={reload}>
            {copy.retry}
          </Button>
        }
      />
    );
  return <>{children(state.data)}</>;
}

export function AdminPage() {
  const { copy } = useCopy();
  const [revision, setRevision] = useState(0);
  const jobs = useAdminResource<AdminJobs>("/v1/admin/jobs", revision);
  const runs = useAdminResource<AdminRuns>("/v1/admin/runs", revision);
  useAppDraft(false); // nothing on this page keeps unsaved input
  useAppPage({
    title: copy.admin_title,
    description: copy.admin_description,
    actions: [
      {
        id: "refresh",
        label: copy.refresh,
        variant: "primary",
        onAction: () => setRevision((n) => n + 1),
      },
    ],
  });
  const zone =
    jobs.state.phase === "ok" ? jobs.state.data.time_zone : "Asia/Shanghai";
  return (
    <div className="mm">
      <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
        <JobsCard
          state={jobs.state}
          reload={jobs.reload}
          zone={zone}
          onQueued={() => setRevision((n) => n + 1)}
        />
        <HistoryCard state={runs.state} reload={runs.reload} zone={zone} />
      </Space>
    </div>
  );
}

function JobsCard({
  state,
  reload,
  zone,
  onQueued,
}: {
  state: Phase<AdminJobs>;
  reload: () => void;
  zone: string;
  onQueued: () => void;
}) {
  const { copy } = useCopy();
  const [notice, setNotice] = useState<string | null>(null);
  return (
    <Card size="small" title={copy.admin_jobs}>
      <Space orientation="vertical" size="small" style={{ width: "100%" }}>
        {notice && (
          <Alert
            type="success"
            showIcon
            closable={{ onClose: () => setNotice(null) }}
            title={notice}
          />
        )}
        <LoadState state={state} reload={reload}>
          {(data) => (
            <>
              <span className="mm-muted">
                {fill(copy.admin_zone, { zone: data.time_zone })}
              </span>
              <div className="mm-admin-jobs">
                {data.jobs.map((job) => (
                  <JobRow
                    key={job.name}
                    job={job}
                    zone={zone}
                    onQueued={(name) => {
                      setNotice(fill(copy.admin_runQueued, { job: name }));
                      onQueued();
                    }}
                  />
                ))}
              </div>
            </>
          )}
        </LoadState>
      </Space>
    </Card>
  );
}

function JobRow({
  job,
  zone,
  onQueued,
}: {
  job: AdminJob;
  zone: string;
  onQueued: (job: string) => void;
}) {
  const { copy, locale } = useCopy();
  const last = job.last_run;
  return (
    <div className="mm-admin-job">
      <div className="mm-admin-job-main">
        <strong className="mm-admin-name">{job.name}</strong>
        <ul className="mm-admin-slots" aria-label={job.name}>
          {job.schedule.length === 0 && (
            <li className="mm-muted">{copy.admin_notScheduled}</li>
          )}
          {job.schedule.map((slot, i) => (
            <li key={i}>
              {formatSlot(slot, locale)}
              {slot.fallback && (
                <span className="mm-muted"> ({copy.admin_fallback})</span>
              )}
            </li>
          ))}
        </ul>
        <div className="mm-admin-facts">
          <span>
            <span className="mm-muted">{copy.admin_nextRun}: </span>
            {job.next_run ? formatTime(job.next_run, locale, zone) : DASH}
          </span>
          <span>
            <span className="mm-muted">{copy.admin_lastRun}: </span>
            {last ? (
              <>
                <StatusTag status={last.status} copy={copy} />{" "}
                {formatTime(
                  last.finished_at ?? last.started_at ?? last.queued_at,
                  locale,
                  zone,
                )}
                {last.error && (
                  <code className="mm-admin-code"> {last.error}</code>
                )}
              </>
            ) : (
              copy.admin_never
            )}
          </span>
        </div>
      </div>
      <RunNow job={job.name} onQueued={onQueued} />
    </div>
  );
}

function newRequestId(): string {
  return crypto.randomUUID();
}

function RunNow({
  job,
  onQueued,
}: {
  job: string;
  onQueued: (job: string) => void;
}) {
  const { copy } = useCopy();
  const { post } = useApi();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // A refusal that repeating the request cannot change: no confirm button.
  const [final, setFinal] = useState(false);
  // One identifier per opened dialog: retries reuse it, so the backend can
  // tell a repeat of this click from a new one and never queues twice.
  const requestId = useRef<string | null>(null);
  const cancel = useRef<HTMLButtonElement>(null);
  const names = { job };

  const show = () => {
    requestId.current = newRequestId();
    setError(null);
    setFinal(false);
    setOpen(true);
  };
  const close = () => {
    if (busy) return;
    requestId.current = null;
    setOpen(false);
  };
  const confirm = async () => {
    if (!requestId.current) return;
    setBusy(true);
    setError(null);
    const result = await post<RunNowResult>(
      `/v1/admin/jobs/${encodeURIComponent(job)}/run`,
      { request_id: requestId.current },
    );
    setBusy(false);
    if (result.status === "ok") {
      requestId.current = null;
      setOpen(false);
      onQueued(job);
      return;
    }
    const code = result.status === "error" ? result.code : "";
    setFinal(code === "already_active" || code === "conflict");
    setError(
      code === "queue_full"
        ? copy.admin_runQueueFull
        : code === "not_found"
          ? copy.admin_runUnknownJob
          : code === "already_active"
            ? copy.admin_runAlreadyActive
            : code === "conflict"
              ? copy.admin_runConflict
              : copy.admin_runFailed,
    );
  };
  return (
    <>
      <Button onClick={show} aria-label={`${copy.admin_runNow}: ${job}`}>
        {copy.admin_runNow}
      </Button>
      <Modal
        open={open}
        title={fill(copy.admin_runNowTitle, names)}
        onCancel={close}
        mask={{ closable: !busy }}
        keyboard={!busy}
        closable={!busy}
        destroyOnHidden
        afterOpenChange={(visible) => {
          if (visible) cancel.current?.focus();
        }}
        footer={
          <Space wrap>
            <Button ref={cancel} onClick={close} disabled={busy} autoFocus>
              {copy.admin_cancel}
            </Button>
            {!final && (
              <Button type="primary" onClick={confirm} loading={busy}>
                {fill(copy.admin_runNowConfirm, names)}
              </Button>
            )}
          </Space>
        }
      >
        <p>{fill(copy.admin_runNowBody, names)}</p>
        {error && <Alert type="error" showIcon title={error} role="alert" />}
      </Modal>
    </>
  );
}

function HistoryCard({
  state,
  reload,
  zone,
}: {
  state: Phase<AdminRuns>;
  reload: () => void;
  zone: string;
}) {
  const { copy } = useCopy();
  return (
    <Card size="small" title={copy.admin_history}>
      <LoadState state={state} reload={reload}>
        {(data) => <RunList runs={data.runs} zone={zone} />}
      </LoadState>
    </Card>
  );
}

function RunList({ runs, zone }: { runs: AdminRun[]; zone: string }) {
  const { copy, locale } = useCopy();
  const reduce = usePrefersReducedMotion();
  const [shown, setShown] = useState(HISTORY_STEP);
  const [active, setActive] = useState<string[]>([]);
  if (runs.length === 0) return <Empty description={copy.admin_noRuns} />;
  const items = runs.slice(0, shown).map((run) => ({
    key: run.id,
    label: (
      <div className="mm-admin-run">
        <span className="mm-admin-run-line">
          <strong className="mm-admin-name">{run.job}</strong>
          <Tag style={{ marginInlineEnd: 0 }}>
            {sourceLabel(copy, run.source)}
          </Tag>
          <StatusTag status={run.status} copy={copy} />
        </span>
        <span className="mm-muted mm-admin-run-line">
          <span>
            {copy.admin_queuedAt} {formatTime(run.queued_at, locale, zone)}
          </span>
          {run.started_at && (
            <span>
              {copy.admin_startedAt} {formatTime(run.started_at, locale, zone)}
            </span>
          )}
          {run.finished_at && (
            <span>
              {copy.admin_finishedAt}{" "}
              {formatTime(run.finished_at, locale, zone)}
            </span>
          )}
          <span>
            {copy.run_attempt} {run.attempt}
          </span>
          {run.error && (
            <span>
              {copy.run_error}{" "}
              <code className="mm-admin-code">{run.error}</code>
            </span>
          )}
        </span>
      </div>
    ),
    children: <RunDetail run={run} />,
  }));
  return (
    // Collapse animates through antd's motion tokens; with reduced motion
    // requested they are switched off, so panels open and close instantly.
    <ConfigProvider theme={{ token: { motion: !reduce } }}>
      <Space orientation="vertical" size="small" style={{ width: "100%" }}>
        <Collapse
          className="mm-admin-runs"
          items={items}
          activeKey={active}
          onChange={(keys) => setActive(keys)}
          destroyOnHidden
        />
        {runs.length > shown && (
          <Button onClick={() => setShown((n) => n + HISTORY_STEP)}>
            {copy.admin_showMore}
          </Button>
        )}
      </Space>
    </ConfigProvider>
  );
}

function RunDetail({ run }: { run: AdminRun }) {
  const { copy } = useCopy();
  const { get, ready } = useApi();
  const [log, setLog] = useState<Phase<AdminLog>>({ phase: "loading" });
  const [attempt, setAttempt] = useState(0);
  // A run still queued or running keeps writing its log, so every refresh of
  // the page (which replaces the run object) fetches the tail again.
  const live = run.status === "queued" || run.status === "running";
  const refresh = live ? run : null;
  useEffect(() => {
    if (!ready) return;
    const abort = new AbortController();
    // Keep the shown log while a newer one loads.
    setLog((current) =>
      current.phase === "ok" ? current : { phase: "loading" },
    );
    get<AdminLog>(
      `/v1/admin/runs/${encodeURIComponent(run.id)}/log`,
      {},
      abort.signal,
    ).then((result) => {
      if (abort.signal.aborted) return;
      setLog(
        result.status === "ok"
          ? { phase: "ok", data: result.data }
          : { phase: "error" },
      );
    });
    return () => abort.abort();
  }, [get, ready, run.id, run.status, refresh, attempt]);
  return (
    <div
      className="mm-admin-detail"
      aria-label={fill(copy.admin_runDetails, { job: run.job })}
    >
      {run.installed && run.installed.length > 0 && (
        <p>
          <span className="mm-muted">{copy.admin_installed}: </span>
          {run.installed.join(", ")}
        </p>
      )}
      <p className="mm-muted">
        {copy.admin_exitCode}: {run.exit_code}
      </p>
      <strong>{copy.admin_log}</strong>
      {log.phase === "loading" && <Spin aria-label={copy.admin_logLoading} />}
      {log.phase === "error" && (
        <Alert
          type="error"
          showIcon
          title={copy.admin_logFailed}
          action={
            <Button size="small" onClick={() => setAttempt((n) => n + 1)}>
              {copy.retry}
            </Button>
          }
        />
      )}
      {log.phase === "ok" && (
        <>
          {log.data.truncated && (
            <p className="mm-muted">{copy.admin_logTruncated}</p>
          )}
          {log.data.log === "" ? (
            <p className="mm-muted">{copy.admin_logEmpty}</p>
          ) : (
            <pre
              className="mm-admin-log"
              tabIndex={0}
              aria-label={copy.admin_log}
            >
              {log.data.log}
            </pre>
          )}
        </>
      )}
    </div>
  );
}
