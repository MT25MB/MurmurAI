import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, waitFor } from "@testing-library/react";
import CursorOverlay from "./CursorOverlay";

vi.mock("@tauri-apps/api/window", () => ({
  getCurrentWindow: () => ({
    setSize: vi.fn().mockResolvedValue(undefined),
    setPosition: vi.fn().mockResolvedValue(undefined),
  }),
}));
vi.mock("@tauri-apps/api/dpi", () => ({
  LogicalSize: class {
    constructor(public width: number, public height: number) {}
  },
  LogicalPosition: class {
    constructor(public x: number, public y: number) {}
  },
}));

const sockets: any[] = [];
class TestWS {
  static OPEN = 1;
  readyState = TestWS.OPEN;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;
  constructor() {
    sockets.push(this);
    setTimeout(() => this.onopen?.(), 0);
  }
  send() {}
  close() {}
}

describe("CursorOverlay", () => {
  beforeEach(() => {
    sockets.length = 0;
    vi.stubGlobal("WebSocket", TestWS);
  });

  it("shows a ring at real action coordinates", async () => {
    render(<CursorOverlay />);
    await waitFor(() => expect(sockets.length).toBe(1));

    act(() =>
      sockets[0].onmessage?.({
        data: JSON.stringify({ type: "cursor", x: 400, y: 300, kind: "click" }),
      })
    );

    const ring = document.querySelector('[aria-hidden="true"]') as HTMLElement;
    expect(ring).not.toBeNull();
    expect(ring.style.left).toBe("400px");
    expect(ring.style.top).toBe("300px");
  });

  it("renders nothing until the agent acts", () => {
    render(<CursorOverlay />);
    expect(document.querySelector('[aria-hidden="true"]')).toBeNull();
  });
});
