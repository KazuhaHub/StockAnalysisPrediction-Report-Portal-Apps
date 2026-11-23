import type { ReactNode } from "react";
import { Alert, Button, Empty, Segmented, Select, Space, Spin } from "antd";
import {
  useAppBackend,
  useAppDraft,
  useAppNavigation,
  useAppPage,
} from "@portal-app/sdk/root-v2";
import type { ModuleId } from "../lib/api";
import { useCopy } from "../lib/copy";
import { useSnapshot } from "../lib/hooks";

export const ROUTES: {
  path: string;
  key: "overview" | "margin" | "sentiment" | "etf" | "panorama";
}[] = [
  { path: "/", key: "overview" },
  { path: "/margin", key: "margin" },
  { path: "/sentiment", key: "sentiment" },
  { path: "/etf", key: "etf" },
  { path: "/panorama", key: "panorama" },
];

export function ModuleNav() {
  const { copy } = useCopy();
  const navigation = useAppNavigation();
  return (
    <Segmented
      aria-label={copy.navigation}
      value={navigation.path ?? "/"}
      disabled={!navigation.ready}
      onChange={(path) => {
        navigation.navigate(String(path));
      }}
      options={ROUTES.map((route) => ({
        value: route.path,
        label: copy[`nav_${route.key}`],
      }))}
    />
  );
}

export type DashboardContext<S> = {
  summary: S;
  date: string;
  asOf: string;
  revision: number;
};

type Props<S> = {
  module: ModuleId;
  title: string;
  children: (context: DashboardContext<S>) => ReactNode;
};

/**
 * The shared frame of every route: host title and actions, the module
 * switcher, the date picker driven by `/dates`, and the loading, empty and
 * error states of the module's summary.
 */
export function Dashboard<S>({ module, title, children }: Props<S>) {
  const { copy } = useCopy();
  const backend = useAppBackend();
  const navigation = useAppNavigation();
  const snap = useSnapshot<S>(module);
  useAppDraft(false); // read-only dashboards never hold unsaved input
  const home = navigation.path === "/" || navigation.path === null;

  useAppPage({
    title,
    description: copy.description,
    actions: [
      {
        id: "refresh",
        label: copy.refresh,
        variant: "primary",
        loading: snap.fetching,
        disabled: !backend.ready,
        onAction: () => snap.reload(),
      },
      ...(home
        ? []
        : [
            {
              id: "overview",
              label: copy.nav_overview,
              disabled: !navigation.ready,
              onAction: () => {
                navigation.navigate("/");
              },
            },
          ]),
    ],
  });

  if (!backend.available)
    return <Alert type="warning" showIcon title={copy.backendUnavailable} />;

  // Content stays mounted while a Refresh or date change is in flight, so
  // table search, filters, sort, paging and view toggles survive it; only the
  // very first load, an error or an empty module replaces the body.
  let body: ReactNode;
  if (!backend.ready || snap.phase === "loading")
    body = <Spin aria-label={copy.loading} />;
  else if (snap.phase === "error")
    body = (
      <Alert
        type="error"
        showIcon
        title={copy.unavailable}
        action={
          <Button size="small" onClick={snap.reload}>
            {copy.retry}
          </Button>
        }
      />
    );
  else if (
    snap.phase === "empty" ||
    !snap.summary ||
    !snap.date ||
    !snap.summaryDate
  )
    body = <Empty description={copy.preparing} />;
  else
    body = (
      <Spin spinning={snap.fetching} aria-label={copy.loading}>
        {children({
          summary: snap.summary,
          date: snap.summaryDate,
          asOf: snap.asOf ?? snap.summaryDate,
          revision: snap.revision,
        })}
      </Spin>
    );

  return (
    <div className="mm">
      <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
        <div className="mm-toolbar">
          <ModuleNav />
          <Space>
            <span className="mm-muted">{copy.date}</span>
            <Select
              aria-label={copy.date}
              style={{ width: 140 }}
              value={snap.date}
              disabled={snap.dates.length === 0}
              onChange={snap.setDate}
              options={snap.dates.map((value) => ({ value, label: value }))}
            />
          </Space>
        </div>
        {body}
      </Space>
    </div>
  );
}
