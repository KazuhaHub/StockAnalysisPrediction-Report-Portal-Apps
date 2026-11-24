import { useLayoutEffect, useRef, type ReactNode } from "react";
import { Alert, Button, Empty, Select, Space, Spin } from "antd";
import {
  useAppBackend,
  useAppDraft,
  useAppNavigation,
  useAppPage,
} from "@portal-app/sdk/root-v2";
import type { ModuleId } from "../lib/api";
import { useCopy } from "../lib/copy";
import { useSnapshot } from "../lib/hooks";
import { useScrollEdges } from "../lib/useScrollEdges";

export const ROUTES: {
  path: string;
  key: "overview" | "margin" | "sentiment" | "etf" | "panorama" | "quant";
}[] = [
  { path: "/", key: "overview" },
  { path: "/margin", key: "margin" },
  { path: "/sentiment", key: "sentiment" },
  { path: "/etf", key: "etf" },
  { path: "/panorama", key: "panorama" },
  { path: "/quant", key: "quant" },
];

/**
 * The module switcher: one row of tabs that never wraps. When they do not fit
 * (a phone) the row scrolls sideways, by swipe, wheel or drag, with a fade at
 * the side that has more (useScrollEdges, `.mm-scroll-row`); there is no "…"
 * overflow menu. The active tab is kept in view, also when the row is resized.
 */
export function ModuleNav() {
  const { copy } = useCopy();
  const navigation = useAppNavigation();
  const row = useRef<HTMLDivElement>(null);
  const active = navigation.path ?? "/";
  useScrollEdges(row, [active]);
  useLayoutEffect(() => {
    const element = row.current;
    if (!element) return;
    const reveal = () => {
      const tab = element.querySelector<HTMLElement>('[aria-selected="true"]');
      if (!tab) return;
      const room = element.clientWidth;
      const left = tab.offsetLeft;
      const right = left + tab.offsetWidth;
      if (left >= element.scrollLeft && right <= element.scrollLeft + room)
        return;
      element.scrollTo?.({ left: left - (room - tab.offsetWidth) / 2 });
    };
    reveal();
    const observer = new ResizeObserver(reveal);
    observer.observe(element);
    return () => observer.disconnect();
  }, [active]);
  const go = (index: number) => {
    const next = ROUTES[(index + ROUTES.length) % ROUTES.length];
    navigation.navigate(next.path);
    row.current
      ?.querySelectorAll<HTMLElement>('[role="tab"]')
      [(index + ROUTES.length) % ROUTES.length]?.focus();
  };
  return (
    <nav aria-label={copy.navigation} className="mm-nav-landmark">
      <div
        ref={row}
        role="tablist"
        className="mm-nav mm-scroll-row"
        onKeyDown={(event) => {
          const at = ROUTES.findIndex((route) => route.path === active);
          const step =
            event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
          if (step) go(at + step);
          else if (event.key === "Home") go(0);
          else if (event.key === "End") go(ROUTES.length - 1);
          else return;
          event.preventDefault();
        }}
      >
        {ROUTES.map((route) => (
          <button
            key={route.path}
            type="button"
            role="tab"
            className="mm-nav-tab"
            aria-selected={route.path === active}
            tabIndex={route.path === active ? 0 : -1}
            disabled={!navigation.ready}
            onClick={() => navigation.navigate(route.path)}
          >
            {copy[`nav_${route.key}`]}
          </button>
        ))}
      </div>
    </nav>
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
          <div className="mm-date">
            <span className="mm-muted">{copy.date}</span>
            <Select
              aria-label={copy.date}
              className="mm-date-select"
              value={snap.date}
              disabled={snap.dates.length === 0}
              onChange={snap.setDate}
              options={snap.dates.map((value) => ({ value, label: value }))}
            />
          </div>
        </div>
        {body}
      </Space>
    </div>
  );
}
