import { cleanup, configure } from "@testing-library/react";
import { afterEach, vi } from "vitest";
import { installMatchMedia, resetViewport } from "./viewport";

// findBy*/waitFor give up after one second by default. A page mount here renders antd tables and
// forms; on a loaded shared runner the first mount of a file took 1.9 s and failed with "Unable to
// find ... Stock0" although the page was fine. A passing wait returns as soon as the element
// appears, so the longer limit costs nothing except when something is really wrong.
configure({ asyncUtilTimeout: 8000 });

installMatchMedia();
afterEach(() => {
  cleanup();
  resetViewport();
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
