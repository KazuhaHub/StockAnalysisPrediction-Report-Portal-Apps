// DEVELOPMENT AND CI ONLY. Layout check of the market-monitor frontend on
// phone and desktop widths. It is never imported by src/ and is not part of
// dist/ or frontend.zip.
//
// It starts the dev server (vite.dev.config.ts) on the committed fixture
// snapshots in dev/fixtures, drives headless Chrome through the DevTools
// protocol, loads every tab of the app inside the stand-in host page
// (dev/host.html), measures inside the sandboxed app frame, and exits non-zero
// when any of these fail:
//
//   page-scroll-x     the app frame's document is wider than its viewport
//   overflow-x        an element extends past the viewport's right edge
//                     (unless a clipping ancestor that fits contains it)
//   host-scroll-x     the stand-in host page itself scrolls sideways
//   legend-overlap    an ECharts legend's rectangle overlaps its plot (grid
//                     or pie) rectangle
//   table-not-cards   a table header is visible on a phone
//   segmented-not-folded  a segmented choice of 3+ options on a phone
//   kpi-columns / kpi-truncated   KPI cards are not two to a row, or cut a number
//   ellipsis          text is squeezed to an ellipsis
//   toolbar-overlap   the module tabs and the date picker overlap
//   tabs-menu         antd's "…" tab overflow menu is visible
//   active-tab-hidden the active module tab is not scrolled into view
//   tabs-unreachable  a swipe on the tab row does not reach its last (or first) tab
//   touch-target      a control is under 44px high on a touch screen
//   no-sort-control   a phone card list of a server-paged table has no sort control
//
// Environment:
//   CHROME     path of the Chrome binary to start (default google-chrome)
//   CDP_PORT   use a Chrome that is already listening on this port instead
//   VITE_PORT  dev server port (default 5194)
//   VITE_RUNNING=1  use a dev server already running on VITE_PORT
//   WIDTHS     comma-separated widths (default 360,390,768,1280)
//   THEMES     comma-separated light,dark (default light,dark)
//   ROUTES     comma-separated route names to check (default all)
//   SHOT_DIR   write a screenshot of every page into this directory
import { spawn } from "node:child_process";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const frontend = dirname(here);
const csv = (value, fallback) =>
  (value ?? fallback)
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);

const VITE_PORT = Number(process.env.VITE_PORT ?? 5194);
// Reuse a dev server that is already running (the check starts its own otherwise).
const VITE_RUNNING = process.env.VITE_RUNNING === "1";
const WIDTHS = csv(process.env.WIDTHS, "360,390,768,1280").map(Number);
const THEMES = csv(process.env.THEMES, "light,dark");
const SHOT_DIR = process.env.SHOT_DIR;
const ALL_ROUTES = [
  ["overview", "/"],
  ["margin", "/margin"],
  ["sentiment", "/sentiment"],
  ["etf", "/etf"],
  ["panorama", "/panorama"],
  ["quant", "/quant"],
  ["admin", "/admin"],
];
const wanted = csv(process.env.ROUTES, ALL_ROUTES.map(([n]) => n).join(","));
const ROUTES = ALL_ROUTES.filter(([name]) => wanted.includes(name));
// Server-paged tables: a phone has no header to sort by, so each needs the
// sort control above its cards.
const SORTABLE = new Set(["margin", "etf", "panorama"]);
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// ---------------------------------------------------------------- processes
const children = [];
function cleanup() {
  for (const child of children.splice(0))
    try {
      process.kill(child.pid);
    } catch {
      /* already gone */
    }
}
process.on("exit", cleanup);
for (const signal of ["SIGINT", "SIGTERM"])
  process.on(signal, () => {
    cleanup();
    process.exit(130);
  });

async function until(fn, what, timeout = 60_000) {
  const end = Date.now() + timeout;
  for (;;) {
    try {
      const value = await fn();
      if (value) return value;
    } catch {
      /* not ready yet */
    }
    if (Date.now() > end) throw new Error(`timed out waiting for ${what}`);
    await sleep(150);
  }
}

let viteServer = null;
async function startVite() {
  if (VITE_RUNNING) return;
  // In-process, so the server goes away with this script.
  process.env.MM_SNAPSHOT_DIR = join(here, "fixtures");
  const { createServer } = await import("vite");
  viteServer = await createServer({
    configFile: join(frontend, "vite.dev.config.ts"),
    logLevel: "warn",
    server: { port: VITE_PORT, strictPort: true },
  });
  await viteServer.listen();
  await until(
    async () => (await fetch(`http://127.0.0.1:${VITE_PORT}/dev/host.html`)).ok,
    "the dev server",
  );
}

async function browserEndpoint() {
  if (process.env.CDP_PORT) return `http://127.0.0.1:${process.env.CDP_PORT}`;
  const profile = mkdtempSync(join(tmpdir(), "mm-layout-"));
  const chrome = spawn(
    process.env.CHROME ?? "google-chrome",
    [
      "--headless=new",
      "--no-sandbox",
      "--disable-gpu",
      "--no-first-run",
      "--remote-debugging-address=127.0.0.1",
      "--remote-debugging-port=0",
      `--user-data-dir=${profile}`,
      "about:blank",
    ],
    { stdio: "ignore" },
  );
  children.push(chrome);
  process.on("exit", () => rmSync(profile, { recursive: true, force: true }));
  const portFile = join(profile, "DevToolsActivePort");
  const port = await until(
    () => existsSync(portFile) && readFileSync(portFile, "utf8").split("\n")[0],
    "Chrome",
  );
  return `http://127.0.0.1:${port}`;
}

// --------------------------------------------------------------------- CDP
class Cdp {
  constructor(ws) {
    this.ws = ws;
    this.id = 0;
    this.pending = new Map();
    this.listeners = new Set();
    ws.onmessage = (event) => {
      const message = JSON.parse(event.data);
      if (message.id) {
        const waiting = this.pending.get(message.id);
        this.pending.delete(message.id);
        if (message.error)
          waiting.reject(
            new Error(`${waiting.method}: ${message.error.message}`),
          );
        else waiting.resolve(message.result);
      } else for (const listener of this.listeners) listener(message);
    };
  }
  send(method, params = {}, sessionId) {
    const id = ++this.id;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject, method });
      this.ws.send(JSON.stringify({ id, method, params, sessionId }));
    });
  }
  on(listener) {
    this.listeners.add(listener);
  }
}

async function connect(endpoint) {
  const { webSocketDebuggerUrl } = await (
    await fetch(`${endpoint}/json/version`)
  ).json();
  const ws = new WebSocket(webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    ws.onopen = resolve;
    ws.onerror = () => reject(new Error("cannot connect to Chrome"));
  });
  return new Cdp(ws);
}

// ------------------------------------------------- measured inside the frame
/* eslint-disable */
function measure(opts) {
  const out = { vw: 0, violations: [], charts: [], tabs: null };
  const add = (rule, detail) => out.violations.push({ rule, detail });
  const vw = document.documentElement.clientWidth;
  out.vw = vw;
  const describe = (el) => {
    const cls = [...el.classList].slice(0, 2).join(".");
    const text = (el.textContent || "")
      .trim()
      .replace(/\s+/g, " ")
      .slice(0, 24);
    return `${el.tagName.toLowerCase()}${cls ? "." + cls : ""}${text ? ` "${text}"` : ""}`;
  };
  const visible = (el) => {
    const cs = getComputedStyle(el);
    if (cs.display === "none" || cs.visibility === "hidden") return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const all = [...document.querySelectorAll("body *")].filter(
    (el) => !["SCRIPT", "STYLE", "NOSCRIPT"].includes(el.tagName),
  );

  const root = document.documentElement;
  if (root.scrollWidth > root.clientWidth)
    add(
      "page-scroll-x",
      `scrollWidth ${root.scrollWidth} > clientWidth ${root.clientWidth}`,
    );

  // Elements past the right edge, unless a scrolling ancestor that fits holds them.
  const clipped = (el) => {
    for (
      let p = el.parentElement;
      p && p !== document.body;
      p = p.parentElement
    ) {
      // Only a box meant to scroll excuses what it holds; one that clips (hidden) hides it.
      if (["auto", "scroll"].includes(getComputedStyle(p).overflowX)) {
        const r = p.getBoundingClientRect();
        if (r.right <= vw + 1 && r.left >= -1) return true;
      }
    }
    return false;
  };
  const over = all.filter(
    (el) =>
      visible(el) && el.getBoundingClientRect().right > vw + 1 && !clipped(el),
  );
  for (const el of over
    .filter((e) => !over.includes(e.parentElement))
    .slice(0, 5))
    add(
      "overflow-x",
      `${describe(el)} right ${Math.round(el.getBoundingClientRect().right)} > ${vw}`,
    );

  // Legends against their plots.
  const rectOf = (g) => {
    g.updateTransform && g.updateTransform();
    const r = g.getBoundingRect().clone();
    if (g.transform) r.applyTransform(g.transform);
    return r;
  };
  const overlap = (a, b) =>
    Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x) > 1 &&
    Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y) > 1;
  for (const el of document.querySelectorAll(".mm-chart")) {
    const chart = el.__mmChart;
    if (!chart || !visible(el)) continue;
    const label = el.getAttribute("aria-label") || "chart";
    const width = chart.getWidth();
    const legends = (chart._componentsViews || [])
      .filter((v) => String(v.type).startsWith("legend") && v.group)
      .map((v) => {
        const r = rectOf(v.group);
        // A scrolling legend clips its page of items to the chart; its
        // children's union can run past it.
        return {
          x: Math.max(0, r.x),
          y: r.y,
          width: Math.min(r.width, width),
          height: r.height,
        };
      })
      .filter((r) => r.width > 0 && r.height > 0);
    const model = chart.getModel();
    const plots = [];
    for (const g of model.queryComponents({ mainType: "grid" })) {
      const rc = g.coordinateSystem && g.coordinateSystem.getRect();
      if (rc)
        plots.push({
          kind: "grid",
          x: rc.x,
          y: rc.y,
          width: rc.width,
          height: rc.height,
        });
    }
    for (const s of model.getSeriesByType("pie")) {
      const l = s.getData().getItemLayout(0);
      if (l)
        plots.push({
          kind: "pie",
          x: l.cx - l.r,
          y: l.cy - l.r,
          width: 2 * l.r,
          height: 2 * l.r,
        });
    }
    out.charts.push({
      label,
      legends: legends.length,
      plots: plots.length,
      width,
    });
    for (const lg of legends)
      for (const plot of plots)
        if (overlap(lg, plot))
          add(
            "legend-overlap",
            `${label}: legend y ${Math.round(lg.y)}..${Math.round(lg.y + lg.height)} over ${plot.kind} y ${Math.round(plot.y)}..${Math.round(plot.y + plot.height)}`,
          );
  }

  const phone = vw < 576;
  const narrow = vw < 768;
  if (phone) {
    for (const el of document.querySelectorAll(".ant-table-thead"))
      if (visible(el))
        add(
          "table-not-cards",
          describe(el.closest(".ant-table-wrapper") || el),
        );
    for (const el of document.querySelectorAll(".mm-spec thead"))
      if (visible(el)) add("table-not-cards", "methodology table");
  }
  if (narrow)
    for (const el of document.querySelectorAll(".ant-segmented"))
      if (visible(el) && el.querySelectorAll(".ant-segmented-item").length >= 3)
        add("segmented-not-folded", describe(el));
  if (phone) {
    // Per KPI row: two cards to a line, an odd last card on a line of its own.
    for (const row of document.querySelectorAll(".ant-row")) {
      const cards = [
        ...row.querySelectorAll(":scope > .ant-col > .mm-kpi"),
      ].filter(visible);
      if (!cards.length) continue;
      const lines = new Map();
      for (const el of cards) {
        const top = Math.round(el.getBoundingClientRect().top);
        lines.set(top, (lines.get(top) || 0) + 1);
      }
      const counts = [...lines.entries()]
        .sort((a, b) => a[0] - b[0])
        .map((e) => e[1]);
      counts.forEach((n, i) => {
        if (n > 2 || (n < 2 && i < counts.length - 1))
          add(
            "kpi-columns",
            `line ${i + 1} has ${n} card(s): ${counts.join(",")}`,
          );
      });
    }
    for (const el of document.querySelectorAll(".ant-statistic-content-value"))
      if (visible(el) && el.scrollWidth > el.clientWidth + 1)
        add("kpi-truncated", describe(el));
  }
  for (const el of all) {
    if (!visible(el) || getComputedStyle(el).textOverflow !== "ellipsis")
      continue;
    if (el.scrollWidth > el.clientWidth + 1)
      add("ellipsis", `${describe(el)} ${el.scrollWidth}>${el.clientWidth}`);
  }

  // The header: tabs and date picker never overlap, the tabs have no "…" menu,
  // and the active tab is in view.
  const nav = document.querySelector(".mm-nav-landmark");
  const date = document.querySelector(".mm-date");
  if (nav && date && visible(nav) && visible(date)) {
    const a = nav.getBoundingClientRect();
    const b = date.getBoundingClientRect();
    if (
      Math.min(a.right, b.right) - Math.max(a.left, b.left) > 1 &&
      Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 1
    )
      add("toolbar-overlap", "module tabs and date picker");
  }
  const wrap = document.querySelector(".mm-nav");
  if (wrap) {
    const tabs = [...document.querySelectorAll(".mm-nav [role=tab]")];
    const w = wrap.getBoundingClientRect();
    const active = document.querySelector('.mm-nav [aria-selected="true"]');
    if (active) {
      const r = active.getBoundingClientRect();
      if (r.left < w.left - 1 || r.right > w.right + 1)
        add(
          "active-tab-hidden",
          `${describe(active)} ${Math.round(r.left)}..${Math.round(r.right)} not in ${Math.round(w.left)}..${Math.round(w.right)}`,
        );
    }
    for (const op of document.querySelectorAll(".ant-tabs-nav-operations"))
      if (getComputedStyle(op).display !== "none")
        add("tabs-menu", "the … overflow menu is displayed");
    const first = tabs[0].getBoundingClientRect();
    const last = tabs[tabs.length - 1].getBoundingClientRect();
    out.tabs = {
      count: tabs.length,
      overflows: first.left < w.left - 1 || last.right > w.right + 1,
      y: Math.round(w.top + w.height / 2),
      left: Math.round(w.left),
      right: Math.round(w.right),
      firstLeft: Math.round(first.left),
      lastRight: Math.round(last.right),
    };
  }

  if (matchMedia("(pointer: coarse)").matches) {
    const targets = [
      '[role="tab"]',
      ".ant-btn",
      ".ant-select-selector",
      ".ant-segmented-item",
      ".ant-pagination-item",
      ".ant-pagination-prev",
      ".ant-pagination-next",
      ".ant-drawer-close",
      ".ant-input-affix-wrapper",
    ];
    for (const el of document.querySelectorAll(targets.join(","))) {
      if (!visible(el)) continue;
      const h = el.getBoundingClientRect().height;
      if (h < 43.5)
        add("touch-target", `${describe(el)} is ${Math.round(h)}px high`);
    }
  }
  if (opts.sortControl && phone && !document.querySelector(".mm-card-sort"))
    add("no-sort-control", "no sort control above the cards");
  out.coarse = matchMedia("(pointer: coarse)").matches;
  return out;
}
/* eslint-enable */

// ------------------------------------------------------------------ driver
async function main() {
  await startVite();
  const cdp = await connect(await browserEndpoint());
  const { targetId } = await cdp.send("Target.createTarget", {
    url: "about:blank",
  });
  const { sessionId } = await cdp.send("Target.attachToTarget", {
    targetId,
    flatten: true,
  });
  const page = (method, params) => cdp.send(method, params, sessionId);

  // The app frame is sandboxed without allow-same-origin: it is either a
  // separate target (its own session) or an execution context of the page.
  const frame = { session: null, contexts: new Map(), id: null };
  cdp.on((m) => {
    if (
      m.method === "Target.attachedToTarget" &&
      m.sessionId === sessionId &&
      m.params.targetInfo.type === "iframe"
    ) {
      frame.session = m.params.sessionId;
      pending.push(emulate(frame.session));
    }
    if (
      m.method === "Target.detachedFromTarget" &&
      m.params.sessionId === frame.session
    )
      frame.session = null;
    if (
      m.method === "Runtime.executionContextCreated" &&
      m.sessionId === sessionId
    ) {
      const { id, auxData } = m.params.context;
      if (auxData && auxData.isDefault && auxData.frameId)
        frame.contexts.set(auxData.frameId, id);
    }
    if (
      m.method === "Runtime.executionContextDestroyed" &&
      m.sessionId === sessionId
    )
      for (const [k, v] of frame.contexts)
        if (v === m.params.executionContextId) frame.contexts.delete(k);
    if (
      m.method === "Runtime.executionContextsCleared" &&
      m.sessionId === sessionId
    )
      frame.contexts.clear();
  });
  const pending = [];
  let emulation = null;
  const emulate = async (session) => {
    if (!emulation) return;
    const to = (method, params) => cdp.send(method, params, session);
    await to("Emulation.setDeviceMetricsOverride", emulation.metrics).catch(
      () => {},
    );
    await to("Emulation.setTouchEmulationEnabled", emulation.touch).catch(
      () => {},
    );
    await to("Emulation.setEmulatedMedia", emulation.media).catch(() => {});
  };
  await page("Page.enable");
  await page("Runtime.enable");
  await page("Target.setAutoAttach", {
    autoAttach: true,
    waitForDebuggerOnStart: false,
    flatten: true,
  });

  // Where the app frame can be evaluated in right now. A document that is
  // still switching process answers "no context" or "no session": retried.
  const frameTarget = async () => {
    if (frame.session) return { sessionId: frame.session, params: {} };
    const tree = await page("Page.getFrameTree");
    frame.id = tree.frameTree.childFrames?.[0]?.frame.id;
    const contextId = frame.id && frame.contexts.get(frame.id);
    if (contextId === undefined || contextId === null)
      throw new Error("the app frame has no execution context yet");
    return { sessionId, params: { contextId } };
  };
  const value = async (expression, where) => {
    for (let attempt = 0; ; attempt++) {
      try {
        const target =
          where === "host" ? { sessionId, params: {} } : await frameTarget();
        const r = await cdp.send(
          "Runtime.evaluate",
          {
            expression,
            returnByValue: true,
            awaitPromise: true,
            ...target.params,
          },
          target.sessionId,
        );
        if (r.exceptionDetails)
          throw new Error(
            r.exceptionDetails.exception?.description ??
              r.exceptionDetails.text,
          );
        return r.result.value;
      } catch (error) {
        const transient =
          /no execution context|not found|Cannot find context|detached/i.test(
            String(error.message),
          );
        if (!transient || attempt > 60) throw error;
        await sleep(150);
      }
    }
  };
  const inFrame = (expression) => value(expression);
  const inHost = (expression) => value(expression, "host");

  async function load(url, width, dark) {
    emulation = {
      metrics: {
        width,
        height: 900,
        deviceScaleFactor: 1,
        mobile: width < 768,
      },
      touch: { enabled: width < 768, maxTouchPoints: 5 },
      media: {
        features: [
          { name: "prefers-color-scheme", value: dark ? "dark" : "light" },
        ],
      },
    };
    frame.session = null;
    await page("Emulation.setDeviceMetricsOverride", emulation.metrics);
    await page("Emulation.setTouchEmulationEnabled", emulation.touch);
    await page("Emulation.setEmulatedMedia", emulation.media);
    await page("Page.navigate", { url: "about:blank" });
    await page("Page.navigate", { url });
    await until(
      async () =>
        (await inHost("`${location.pathname} ${document.readyState}`")) ===
        "/dev/host.html complete",
      "the host page",
    );
    await Promise.all(pending.splice(0));
    await until(
      () => inFrame("!!document.querySelector('.mm')"),
      "the app to render",
      90_000,
    );
    await settle();
  }

  // Rendered, not loading, and still: heights stop changing and charts are drawn.
  async function settle() {
    let last = -1;
    let stable = 0;
    await until(async () => {
      const state = await inFrame(`(() => {
        const charts = [...document.querySelectorAll('.mm-chart')];
        return {
          busy: !!document.querySelector('.ant-spin-spinning'),
          drawn: charts.every((c) => c.__mmChart),
          height: document.documentElement.scrollHeight,
        };
      })()`);
      if (state.busy || !state.drawn) return false;
      stable = state.height === last ? stable + 1 : 0;
      last = state.height;
      return stable >= 4;
    }, "the page to settle");
    await sleep(500);
  }

  // A swipe on the tab row, as a finger would make it.
  async function swipe(y, fromX, toX) {
    const touch = (type, x) =>
      page("Input.dispatchTouchEvent", {
        type,
        touchPoints: type === "touchEnd" ? [] : [{ x, y }],
      });
    await touch("touchStart", fromX);
    const steps = 8;
    for (let i = 1; i <= steps; i++) {
      await touch("touchMove", fromX + ((toX - fromX) * i) / steps);
      await sleep(16);
    }
    await touch("touchEnd", toX);
    await sleep(500);
  }

  const failures = [];
  const results = [];
  const record = (name, width, theme, locale, state, found) => {
    const label = `${name} ${width}px ${theme} ${locale}${state ? ` [${state}]` : ""}`;
    results.push({ label, violations: found });
    for (const v of found) failures.push(`${label}: ${v.rule}: ${v.detail}`);
  };
  const check = async (name, width, opts) =>
    inFrame(`(${measure.toString()})(${JSON.stringify(opts)})`);

  const matrix = [];
  for (const theme of THEMES)
    for (const width of WIDTHS) matrix.push({ width, theme, locale: "en-US" });
  // The owner reads zh-CN: phone widths again, in that language.
  for (const width of WIDTHS.filter((w) => w < 576))
    matrix.push({ width, theme: "light", locale: "zh-CN" });

  for (const { width, theme, locale } of matrix) {
    for (const [name, path] of ROUTES) {
      const query = new URLSearchParams({
        path,
        dark: theme === "dark" ? "1" : "0",
        locale,
        ...(name === "admin" ? { surface: "admin" } : {}),
      });
      await load(
        `http://127.0.0.1:${VITE_PORT}/dev/host.html?${query}`,
        width,
        theme === "dark",
      );
      const found = (
        await check(name, width, { sortControl: SORTABLE.has(name) })
      ).violations;
      const info = await check(name, width, {});
      // The host stand-in page must not scroll sideways either.
      if (
        await inHost(
          "document.documentElement.scrollWidth > document.documentElement.clientWidth",
        )
      )
        found.push({
          rule: "host-scroll-x",
          detail: "the stand-in host page scrolls sideways",
        });
      if (info.tabs && info.tabs.overflows) {
        // Every tab must be reachable by swiping the row.
        const offset = await inHost(
          "(() => { const r = document.getElementById('frame').getBoundingClientRect(); return { x: r.left, y: r.top }; })()",
        );
        const y = offset.y + info.tabs.y;
        await swipe(
          y,
          offset.x + info.tabs.right - 20,
          offset.x + info.tabs.left + 20,
        );
        const end = (await check(name, width, {})).tabs;
        if (end.lastRight > end.right + 1)
          found.push({
            rule: "tabs-unreachable",
            detail: `last tab ends at ${end.lastRight}, row ends at ${end.right}`,
          });
        await swipe(
          y,
          offset.x + info.tabs.left + 20,
          offset.x + info.tabs.right - 20,
        );
        await swipe(
          y,
          offset.x + info.tabs.left + 20,
          offset.x + info.tabs.right - 20,
        );
        const start = (await check(name, width, {})).tabs;
        if (start.firstLeft < start.left - 1)
          found.push({
            rule: "tabs-unreachable",
            detail: `first tab starts at ${start.firstLeft}, row starts at ${start.left}`,
          });
      }
      record(name, width, theme, locale, "", found);
      if (SHOT_DIR) {
        mkdirSync(SHOT_DIR, { recursive: true });
        // A frame in its own process is not drawn by a beyond-the-viewport
        // capture: grow the viewport to the whole page instead.
        const full = await inHost("document.documentElement.scrollHeight");
        await page("Emulation.setDeviceMetricsOverride", {
          ...emulation.metrics,
          height: Math.min(full, 16000),
        });
        await sleep(400);
        const shot = await page("Page.captureScreenshot", {
          format: "jpeg",
          quality: 70,
        });
        await page("Emulation.setDeviceMetricsOverride", emulation.metrics);
        writeFileSync(
          join(SHOT_DIR, `${name}-${width}-${theme}-${locale}.jpg`),
          Buffer.from(shot.data, "base64"),
        );
      }

      // Overlays: a stock drawer, the Run-now popover, the sort menu.
      const overlay = async (state, open, ready) => {
        const opened = await inFrame(open).catch(() => false);
        if (!opened)
          return record(name, width, theme, locale, state, [
            { rule: "overlay", detail: "could not open it" },
          ]);
        await until(() => inFrame(ready), `${state} to open`, 15_000).catch(
          () => {},
        );
        await sleep(600);
        await settle().catch(() => {});
        // The tab-row swipe test above leaves the row scrolled away from the
        // active tab on purpose; that is not what an overlay is checked for.
        const found = (await check(name, width, {})).violations.filter(
          (v) => v.rule !== "active-tab-hidden",
        );
        record(name, width, theme, locale, state, found);
        await inFrame(
          "document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); true",
        );
        await sleep(300);
      };
      if (name === "margin" || name === "panorama")
        await overlay(
          "drawer",
          "(() => { const row = document.querySelector('tr.mm-row-select'); if (!row) return false; row.click(); return true; })()",
          "!!document.querySelector('.ant-drawer-open .mm-chart') && !!document.querySelector('.ant-drawer-open .mm-chart').__mmChart",
        );
      if (name === "admin")
        await overlay(
          "run-now",
          "(() => { const b = document.querySelector('.mm-admin-job button'); if (!b) return false; b.click(); return true; })()",
          "!!document.querySelector('.mm-confirm')",
        );
      if (name === "etf" && width < 576)
        await overlay(
          "sort-menu",
          "(() => { const s = document.querySelector('.mm-card-sort .ant-select-content, .mm-card-sort .ant-select-selector'); if (!s) return false; s.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })); return true; })()",
          "!!document.querySelector('.ant-select-dropdown:not(.ant-select-dropdown-hidden)')",
        );
    }
  }

  const bad = results.filter((r) => r.violations.length);
  for (const r of results)
    console.log(`${r.violations.length ? "FAIL" : "ok  "}  ${r.label}`);
  console.log(
    `\n${results.length} pages checked, ${bad.length} failing, ${failures.length} violation(s)`,
  );
  for (const f of failures) console.log(`  ${f}`);
  return failures.length ? 1 : 0;
}

let code = 1;
try {
  code = await main();
} catch (error) {
  console.error(error);
}
cleanup();
await viteServer?.close();
process.exit(code);
