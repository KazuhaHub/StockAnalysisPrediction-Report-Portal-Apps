import { useEffect, useState } from "react";
import {
  Alert,
  Button,
  Descriptions,
  Empty,
  Space,
  Spin,
  Statistic,
  Tag,
  Typography,
} from "antd";
import {
  useAppBackend,
  useAppDraft,
  useAppNavigation,
  useAppNetwork,
  useAppPage,
  useAppPresentation,
} from "@portal-app/sdk/root-v2";
import enUS from "../locales/en-US.json";
import zhCN from "../locales/zh-CN.json";
import zhTW from "../locales/zh-TW.json";
import "./style.css";

type DigestRun = {
  occurrenceId: string;
  generatedAt: string;
  itemCount: number;
  digest: string;
  duplicate: boolean;
};

type DigestState = {
  format: "scheduled-digest.state/1-dev.1";
  scheduleId: string;
  lastRun: DigestRun | null;
  recentRuns: DigestRun[];
};

function parseState(body: string): DigestState {
  const value: unknown = JSON.parse(body);
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new Error("invalid digest state");
  const state = value as Partial<DigestState>;
  const validRun = (run: unknown): run is DigestRun => {
    if (!run || typeof run !== "object" || Array.isArray(run)) return false;
    const item = run as Partial<DigestRun>;
    return (
      typeof item.occurrenceId === "string" &&
      typeof item.generatedAt === "string" &&
      Number.isInteger(item.itemCount) &&
      typeof item.digest === "string" &&
      /^[a-f0-9]{64}$/.test(item.digest) &&
      typeof item.duplicate === "boolean"
    );
  };
  if (
    state.format !== "scheduled-digest.state/1-dev.1" ||
    typeof state.scheduleId !== "string" ||
    !Array.isArray(state.recentRuns) ||
    state.recentRuns.length > 16 ||
    !state.recentRuns.every(validRun) ||
    (state.lastRun !== null && !validRun(state.lastRun))
  )
    throw new Error("invalid digest state");
  return {
    format: state.format,
    scheduleId: state.scheduleId,
    lastRun: state.lastRun as DigestRun | null,
    recentRuns: state.recentRuns as DigestRun[],
  };
}

export function Application() {
  const { presentation } = useAppPresentation();
  const backend = useAppBackend();
  const network = useAppNetwork();
  const navigation = useAppNavigation();
  const copy = { "en-US": enUS, "zh-CN": zhCN, "zh-TW": zhTW }[
    presentation.locale
  ];
  const [state, setState] = useState<DigestState | null>(null);
  const [loading, setLoading] = useState(true);
  const [failure, setFailure] = useState<string | null>(null);
  const [feedResult, setFeedResult] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const history = navigation.path === "/history";
  useAppDraft(false);

  useEffect(() => {
    if (!backend.ready) return;
    const abort = new AbortController();
    setLoading(true);
    setFailure(null);
    backend
      .request(
        { method: "GET", path: "/v1/digest", body: "" },
        abort.signal,
      )
      .then((response) => {
        if (abort.signal.aborted) return;
        if (response.status !== 200) throw new Error("unavailable");
        setState(parseState(response.body));
      })
      .catch(() => {
        if (!abort.signal.aborted) setFailure(copy.unavailable);
      })
      .finally(() => {
        if (!abort.signal.aborted) setLoading(false);
      });
    return () => abort.abort();
  }, [backend.ready, backend.request, copy.unavailable, revision]);

  async function checkFeed(signal: AbortSignal) {
    setFeedResult(null);
    try {
      const response = await network.request(
        {
          method: "GET",
          url: "https://digest-feed.example.invalid/v1/summary",
          accept: "application/json",
          contentType: "",
          credential: "digest-feed",
        },
        signal,
      );
      if (signal.aborted) return;
      if (response.status !== 200) throw new Error("unavailable");
      setFeedResult(copy.feedReady);
    } catch {
      if (!signal.aborted) setFeedResult(copy.feedFailed);
    }
  }

  useAppPage({
    title: history ? copy.historyTitle : copy.title,
    description: copy.description,
    actions: history
      ? [
          {
            id: "home",
            label: copy.home,
            disabled: !navigation.ready,
            onAction: () => {
              navigation.navigate("/");
            },
          },
        ]
      : [
          {
            id: "refresh",
            label: copy.refresh,
            variant: "primary",
            loading,
            disabled: !backend.ready,
            onAction: () => setRevision((value) => value + 1),
          },
          {
            id: "history",
            label: copy.history,
            disabled: !navigation.ready,
            onAction: () => {
              navigation.navigate("/history");
            },
          },
        ],
  });

  if (!backend.available)
    return <Alert type="warning" showIcon title={copy.backendUnavailable} />;
  if (!backend.ready || loading) return <Spin aria-label={copy.loading} />;
  if (failure) return <Alert type="error" showIcon title={failure} />;
  if (!state) return <Empty description={copy.empty} />;

  const formatTime = (value: string) =>
    new Intl.DateTimeFormat(presentation.locale, {
      dateStyle: "medium",
      timeStyle: "short",
      timeZone: presentation.timeZone,
    }).format(new Date(value));

  return (
    <div className="digest">
      <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
        <div className="digest-summary">
          <Statistic
            title={copy.itemCount}
            value={state.lastRun?.itemCount ?? 0}
          />
          <Tag color="blue">{state.scheduleId}</Tag>
        </div>
        {history ? (
          state.recentRuns.length === 0 ? (
            <Empty description={copy.empty} />
          ) : (
            <div className="digest-history">
              {state.recentRuns.map((run) => (
                <div className="digest-history-row" key={run.occurrenceId}>
                  <div>
                    <Typography.Text strong>
                      {run.occurrenceId}
                    </Typography.Text>
                    <Typography.Paragraph type="secondary">
                      {formatTime(run.generatedAt)} · {run.itemCount}
                    </Typography.Paragraph>
                  </div>
                  <Typography.Text code>
                    {run.digest.slice(0, 12)}
                  </Typography.Text>
                </div>
              ))}
            </div>
          )
        ) : state.lastRun ? (
          <Descriptions
            column={1}
            size="small"
            items={[
              {
                key: "occurrence",
                label: copy.occurrence,
                children: state.lastRun.occurrenceId,
              },
              {
                key: "generated",
                label: copy.generated,
                children: formatTime(state.lastRun.generatedAt),
              },
              {
                key: "digest",
                label: copy.digest,
                children: (
                  <Typography.Text code copyable>
                    {state.lastRun.digest}
                  </Typography.Text>
                ),
              },
            ]}
          />
        ) : (
          <Empty description={copy.empty} />
        )}
        {network.available && network.credentialAvailable && (
          <div className="digest-feed">
            <Typography.Text strong>{copy.feedTitle}</Typography.Text>
            <Typography.Paragraph type="secondary">
              {copy.feedHint}
            </Typography.Paragraph>
            <Button
              disabled={!network.ready}
              onClick={() =>
                void checkFeed(new AbortController().signal)
              }
            >
              {copy.checkFeed}
            </Button>
            {feedResult && <Alert type="info" showIcon title={feedResult} />}
          </div>
        )}
      </Space>
    </div>
  );
}
