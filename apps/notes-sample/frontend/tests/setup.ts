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
