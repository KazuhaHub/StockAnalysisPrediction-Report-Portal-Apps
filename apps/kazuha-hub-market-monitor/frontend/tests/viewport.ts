// jsdom has no layout. Media queries are answered from a settable viewport
// width (a desktop by default), so antd and the app's own hooks see a desktop
// unless a test calls setViewport() with a phone width before rendering.
let width = 1024;

export function setViewport(next: number) {
  width = next;
  Object.defineProperty(window, "innerWidth", {
    configurable: true,
    value: next,
  });
}

export function resetViewport() {
  setViewport(1024);
}

function matches(query: string): boolean {
  return query.split(/\s+and\s+/).every((part) => {
    const m = /\((min|max)-width:\s*(\d+(?:\.\d+)?)px\)/.exec(part);
    if (!m) return false;
    return m[1] === "min" ? width >= Number(m[2]) : width <= Number(m[2]);
  });
}

export function installMatchMedia() {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: (query: string) => ({
      media: query,
      get matches() {
        return matches(query);
      },
      onchange: null,
      addListener() {},
      removeListener() {},
      addEventListener() {},
      removeEventListener() {},
      dispatchEvent: () => false,
    }),
  });
}
