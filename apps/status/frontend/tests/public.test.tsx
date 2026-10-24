import { afterEach, expect, test, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { PublicStatus } from "../public-src/App";
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
test("anonymous Status reads only public projections without session credentials", async () => {
  const fetch = vi.fn(async (path: string) => ({
    ok: true,
    json: async () =>
      path.includes("incidents")
        ? { items: [], total: 0 }
        : {
            items: [
              {
                id: "component",
                label: "Reviewed public service",
                state: "operational",
              },
            ],
            total: 1,
          },
  }));
  vi.stubGlobal("fetch", fetch);
  render(<PublicStatus />);
  expect(
    await screen.findByRole("heading", { name: "Reviewed public service" }),
  ).toBeTruthy();
  expect(fetch).toHaveBeenCalledTimes(2);
  for (const [path, options] of fetch.mock.calls) {
    expect(path).toMatch(/^public\/v1\/(status|incidents)\?/);
    expect(options).toEqual({ credentials: "omit", cache: "no-store" });
  }
});
test("failed public reads do not show stale service health as a current result", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false }));
  render(<PublicStatus />);
  expect(await screen.findByRole("alert")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "History" })).toBeNull();
});
