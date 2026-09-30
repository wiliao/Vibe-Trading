import "@testing-library/jest-dom/vitest";
// Initialize i18n so `useTranslation()` resolves real strings in tests.
// With no localStorage entry under jsdom this falls back to English, keeping
// the suite's English assertions stable.
import "../i18n";

// ── Global mocks for jsdom ───────────────────────────────────

// jsdom doesn't implement ResizeObserver (ECharts + layout components need it)
globalThis.ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof ResizeObserver;

// jsdom doesn't implement matchMedia
if (typeof window !== "undefined") {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }),
  });
}

// Node >= 25 exposes an experimental global `localStorage` that is only backed
// when the process is started with `--localstorage-file`; without it the getter
// resolves to `undefined` and shadows jsdom's Storage. Tests that touch browser
// storage then throw on `window.localStorage.clear()`. Install an in-memory
// Storage (fresh per test file, matching jsdom's isolation) whenever the real
// implementation is missing, so `npm test` works on every supported Node.
if (typeof window !== "undefined") {
  const installMemoryStorage = (name: "localStorage" | "sessionStorage") => {
    let existing: Storage | undefined;
    try {
      existing = window[name];
    } catch {
      existing = undefined;
    }
    if (existing) return;
    const store = new Map<string, string>();
    const storage = {
      get length() {
        return store.size;
      },
      clear: () => store.clear(),
      getItem: (key: string) => (store.has(key) ? store.get(key)! : null),
      key: (index: number) => Array.from(store.keys())[index] ?? null,
      removeItem: (key: string) => {
        store.delete(key);
      },
      setItem: (key: string, value: string) => {
        store.set(key, String(value));
      },
    } as Storage;
    Object.defineProperty(window, name, { configurable: true, value: storage });
  };
  installMemoryStorage("localStorage");
  installMemoryStorage("sessionStorage");
}
