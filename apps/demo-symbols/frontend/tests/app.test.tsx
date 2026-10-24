import { afterEach, expect, test, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PortalClient } from "@portal-app/sdk";
import { Demo } from "../src/App";
afterEach(cleanup);
const client = (machine: ReturnType<typeof vi.fn>) =>
  ({ machine }) as unknown as PortalClient;
test("symbol search uses the scoped machine API and renders the returned rows", async () => {
  const machine = vi
    .fn()
    .mockResolvedValue({
      items: [
        { symbol: "600000", name: "Fixture", count: 2, latest: "2026-10-24" },
      ],
    });
  render(<Demo client={client(machine)} />);
  expect(await screen.findByText("Fixture")).toBeTruthy();
  await userEvent.type(screen.getByRole("textbox"), "600000{Enter}");
  await waitFor(() =>
    expect(machine).toHaveBeenLastCalledWith(
      "GET",
      "/api/v1/symbols?limit=20&q=600000",
    ),
  );
});
test("a rejected read displays an error and clears stale rows", async () => {
  const machine = vi
    .fn()
    .mockResolvedValueOnce({
      items: [{ symbol: "600000", name: "Fixture", count: 2 }],
    })
    .mockRejectedValue({ key: "unavailable" });
  render(<Demo client={client(machine)} />);
  expect(await screen.findByText("Fixture")).toBeTruthy();
  await userEvent.type(screen.getByRole("textbox"), "600000{Enter}");
  expect(await screen.findByRole("alert")).toBeTruthy();
  expect(screen.queryByText("Fixture")).toBeNull();
});
