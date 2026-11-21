import "@testing-library/jest-dom/vitest";

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
