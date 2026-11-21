// DEVELOPMENT ONLY stand-in for the Portal host page. It uses the SDK's own
// bridge host, so the app runs through the same handshake and hooks as in
// Portal, with backend requests answered by the dev server's mock.
import {
  createBridgeHost,
  type BridgePresentation,
  type PageActionSnapshot,
} from "@portal-app/sdk/bridge-v2";
import manifest from "../../app.v2.json";

const frame = document.getElementById("frame") as HTMLIFrameElement;
const title = document.getElementById("title")!;
const actions = document.getElementById("actions")!;
const locale = document.getElementById("locale") as HTMLSelectElement;
const dark = document.getElementById("dark") as HTMLInputElement;

const routes = manifest.presentation.routes.map((route) => ({
  id: route.id,
  path: route.path,
  layout: "document" as const,
}));
// Dev-only start state from the query string: ?path=/margin&dark=1&locale=en-US
const start = new URLSearchParams(window.location.search);
let path = routes.some((r) => r.path === start.get("path"))
  ? start.get("path")!
  : "/";
if (start.get("dark") === "1") dark.checked = true;
if (start.get("locale")) locale.value = start.get("locale")!;
let snapshot: PageActionSnapshot | null = null;

function presentation(): BridgePresentation {
  const isDark = dark.checked;
  return {
    locale: locale.value as BridgePresentation["locale"],
    timeZone: "Asia/Shanghai",
    layout: "document",
    theme: {
      dark: isDark,
      colorPrimary: "#1677ff",
      colorBg: isDark ? "#141414" : "#ffffff",
      colorText: isDark ? "#f0f0f0" : "#1f1f1f",
      colorBorder: isDark ? "#424242" : "#d9d9d9",
      colorBgLayout: isDark ? "#000000" : "#f5f5f5",
      borderRadius: 8,
    },
    navigation: { path, search: "", routes },
  };
}

function paint() {
  document.body.style.background = dark.checked ? "#000000" : "#f5f5f5";
  document.body.style.color = dark.checked ? "#f0f0f0" : "#1f1f1f";
  title.textContent = snapshot?.page.title ?? "";
  actions.replaceChildren(
    ...(snapshot?.page.actions ?? []).map((action) => {
      const button = document.createElement("button");
      button.textContent = action.label;
      button.disabled = !!action.disabled || !!action.loading;
      button.onclick = () => snapshot?.invoke(action.id);
      return button;
    }),
  );
}

const host = createBridgeHost({
  localWindow: window,
  frameWindow: frame.contentWindow!,
  binding: {
    installationId: "00000000-0000-0000-0000-000000000001",
    generation: "1",
    policyRevision: "1",
    releaseSha256: "0".repeat(64),
  },
  capabilities: ["background.run"],
  presentation: presentation(),
  onPageChange: (value) => {
    snapshot = value;
    paint();
  },
  onNavigate: (next) => {
    path = next;
    host.updatePresentation(presentation());
  },
  onDocumentHeight: (height) => {
    frame.style.height = `${Math.max(height, 400)}px`;
  },
  onBackendRequest: async (request, signal) => {
    const response = await fetch(`/__mock${request.path}`, { signal });
    return { status: response.status, body: await response.text() };
  },
});

for (const control of [locale, dark])
  control.addEventListener("change", () => {
    host.updatePresentation(presentation());
    paint();
  });
paint();
