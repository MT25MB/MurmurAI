import "@testing-library/jest-dom/vitest";
import "vitest-axe/extend-expect";
import * as axeMatchers from "vitest-axe/matchers";
import { expect } from "vitest";

// WCAG 2.2 AA regression gate: every UI test can assert toHaveNoViolations().
expect.extend(axeMatchers);

// vitest-axe augments the legacy Vi namespace; Vitest 5 exposes Assertion on
// the "vitest" module, so add the matcher to that interface as well.
declare module "vitest" {
  interface Assertion {
    toHaveNoViolations(): void;
  }
}

// axe-core probes a canvas for its color-contrast rule; jsdom has no canvas
// implementation and would log "not implemented" for every scan. Returning
// null makes axe mark that check "incomplete" (not a violation) without noise.
Object.defineProperty(HTMLCanvasElement.prototype, "getContext", {
  writable: true,
  value: () => null,
});

// The Tauri runtime and WebSocket are not available under jsdom.
// Stub them so components mount deterministically in tests.
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

class MockWebSocket {
  static OPEN = 1;
  readyState = MockWebSocket.OPEN;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((e: MessageEvent<string>) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;
  constructor(public url: string) {
    setTimeout(() => this.onopen?.(), 0);
  }
  send(data: string) {
    this.sent.push(data);
  }
  close() {}
}

// @ts-expect-error - test global override
globalThis.WebSocket = MockWebSocket;

// @ts-expect-error - Tauri IPC is absent in jsdom
window.__TAURI_INTERNALS__ = {};
