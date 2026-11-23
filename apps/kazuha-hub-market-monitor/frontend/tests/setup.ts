import { vi } from "vitest";

Object.defineProperty(window, "matchMedia", {
  value: vi.fn(() => ({
    matches: false,
    addListener() {},
    removeListener() {},
    addEventListener() {},
    removeEventListener() {},
  })),
});
globalThis.ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
};
Element.prototype.scrollIntoView = vi.fn();

const computedStyle = window.getComputedStyle;
window.getComputedStyle = (element) => computedStyle(element);

// jsdom never fires the transition events antd waits for, so a closed dialog
// would stay on screen: switch antd's motion off for the whole test run.
import { theme } from "antd";
theme.defaultConfig.token = { ...theme.defaultConfig.token, motion: false };
