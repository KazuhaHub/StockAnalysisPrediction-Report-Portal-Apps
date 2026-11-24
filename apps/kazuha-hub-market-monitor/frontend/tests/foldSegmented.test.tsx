import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FoldSegmented } from "../src/components/FoldSegmented";
import { setViewport } from "./viewport";

const three = [
  { label: "60 days", value: 60 },
  { label: "120 days", value: 120 },
  { label: "1 year", value: 250 },
];

describe("FoldSegmented", () => {
  it("is a segmented control on a wide screen", () => {
    render(
      <FoldSegmented
        label="Range"
        value={60}
        onChange={() => {}}
        options={three}
      />,
    );
    expect(screen.getAllByRole("radio")).toHaveLength(3);
    expect(screen.queryByRole("combobox")).toBeNull();
  });

  // Below 768px a choice of three or more becomes a small Select, so a card
  // header stays on one line.
  it("folds to a small Select below 768px and still changes the value", async () => {
    setViewport(767);
    const onChange = vi.fn();
    render(
      <FoldSegmented
        label="Range"
        value={60}
        onChange={onChange}
        options={three}
      />,
    );
    expect(screen.queryByRole("radio")).toBeNull();
    const select = screen.getByRole("combobox", { name: "Range" });
    expect(select.closest(".ant-select-sm")).not.toBeNull();
    await userEvent.click(select);
    await userEvent.click(screen.getByTitle("1 year"));
    expect(onChange).toHaveBeenCalledWith(250);
  });

  it("stays segmented from 768px up", () => {
    setViewport(768);
    render(
      <FoldSegmented
        label="Range"
        value={60}
        onChange={() => {}}
        options={three}
      />,
    );
    expect(screen.getAllByRole("radio")).toHaveLength(3);
  });

  it("keeps a choice of two as a segmented control on a phone", () => {
    setViewport(390);
    render(
      <FoldSegmented
        label="View"
        value="a"
        onChange={() => {}}
        options={[
          { label: "A", value: "a" },
          { label: "B", value: "b" },
        ]}
      />,
    );
    expect(screen.getAllByRole("radio")).toHaveLength(2);
    expect(screen.queryByRole("combobox")).toBeNull();
  });
});
