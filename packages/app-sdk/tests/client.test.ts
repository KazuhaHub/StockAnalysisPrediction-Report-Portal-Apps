import { afterEach, expect, test, vi } from "vitest";
import {
  bridgeRequest,
  PortalClient,
  localeOf,
  primaryColors,
  requestErrorKey,
} from "../src/index";

afterEach(() => vi.restoreAllMocks());
test("extension requests cannot escape their installed application or inject authority", () => {
  expect(bridgeRequest("status", "GET", "/v1/components")).toEqual({
    method: "POST",
    path: "/api/v1/extensions/status/request",
    body: { method: "GET", path: "/v1/components" },
  });
  for (const path of [
    "/api/admin/users",
    "/v1/../x",
    "/v1/%252e%252e/x",
    "/v1//x",
    "https://other/v1/x",
  ])
    expect(() => bridgeRequest("status", "GET", path)).toThrow();
  expect(() => bridgeRequest("../other", "GET", "/v1/me")).toThrow();
  expect(() => bridgeRequest("status", "GET", "/v1/me", {})).toThrow();
});
test("only the real parent may initialize or change theme and dispose removes listeners", () => {
  const parent = {} as Window,
    client = new PortalClient("fixture", { parent, current: window });
  window.dispatchEvent(
    new MessageEvent("message", {
      source: {} as Window,
      data: { type: "rp:theme", theme: { dark: true } },
    }),
  );
  expect(client.getTheme().dark).toBe(false);
  window.dispatchEvent(
    new MessageEvent("message", {
      source: parent,
      data: { type: "rp:init", theme: { dark: true }, locale: "zh-TW" },
    }),
  );
  expect(client.getTheme().dark).toBe(true);
  expect(client.getTheme().locale).toBe("zh-TW");
  client.dispose();
  window.dispatchEvent(
    new MessageEvent("message", {
      source: parent,
      data: { type: "rp:theme", theme: { dark: false } },
    }),
  );
  expect(client.getTheme().dark).toBe(true);
});
test("opaque-origin clients fail safely when opened outside the Portal", async () => {
  const client = new PortalClient("fixture");
  await expect(client.request("GET", "/v1/me")).rejects.toMatchObject({
    key: "privateOnly",
  });
  client.dispose();
});
test("locale fallback and host locale use the same supported language set", () => {
  expect(localeOf("zh-Hant")).toBe("zh-TW");
  expect(localeOf("zh-SG")).toBe("zh-CN");
  expect(localeOf("fr-FR")).toBe("en-US");
});

test("a forged result cannot settle a request and disposal rejects pending work", async () => {
  const parent = { postMessage: vi.fn() } as unknown as Window;
  const client = new PortalClient("fixture", { parent, current: window });
  window.dispatchEvent(
    new MessageEvent("message", { source: parent, data: { type: "rp:init" } }),
  );
  const result = client.request("GET", "/v1/me");
  await Promise.resolve();
  const sent = vi.mocked(parent.postMessage).mock.calls[0][0] as {
    reqId: string;
  };
  window.dispatchEvent(
    new MessageEvent("message", {
      source: {} as Window,
      data: {
        type: "rp:api:result",
        reqId: sent.reqId,
        ok: true,
        data: { admin: true },
      },
    }),
  );
  const expected = expect(result).rejects.toMatchObject({ key: "unavailable" });
  client.dispose();
  await expected;
});

test("disposing before initialization cancels the readiness wait immediately", async () => {
  const parent = {} as Window;
  const client = new PortalClient("fixture", { parent, current: window });
  const result = client.request("GET", "/v1/me");
  const expected = expect(result).rejects.toMatchObject({ key: "unavailable" });
  client.dispose();
  await expected;
});

test("machine requests reject nested traversal and malformed escapes before messaging", async () => {
  const parent = { postMessage: vi.fn() } as unknown as Window;
  const client = new PortalClient("fixture", { parent, current: window });
  for (const path of [
    "/api/v1/%252e%252e/users",
    "/api/v1/%ZZ",
    "/api/v1/%255cadmin",
  ]) {
    await expect(client.machine("GET", path)).rejects.toMatchObject({
      key: "invalidConfiguration",
    });
  }
  expect(parent.postMessage).not.toHaveBeenCalled();
  client.dispose();
});

test("shared primary button text contrasts with host colors in either theme", () => {
  expect(primaryColors("#1677ff").foreground).toBe("#000000");
  expect(primaryColors("#1668dc").foreground).toBe("#ffffff");
  expect(primaryColors("#ffffff").foreground).toBe("#000000");
  expect(primaryColors("#000000").foreground).toBe("#ffffff");
  expect(primaryColors("invalid")).toEqual(primaryColors("#1762c4"));
});
test("shared bridge status errors remain bounded localized keys", () => {
  expect(requestErrorKey(400)).toBe("invalidConfiguration");
  expect(requestErrorKey(409)).toBe("configurationConflict");
  expect(requestErrorKey(429)).toBe("requestBusy");
  expect(requestErrorKey(502)).toBe("unavailable");
});
