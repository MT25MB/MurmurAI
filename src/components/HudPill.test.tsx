import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor, act, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import HudPill from "./HudPill";

// The updater bridge is exercised in src/lib/updater.test.ts; here we keep the
// HUD unit tests offline so they only observe WebSocket messages.
const invokeMock = vi.hoisted(() => vi.fn().mockResolvedValue(undefined));
vi.mock("@tauri-apps/api/core", () => ({ invoke: invokeMock }));
vi.mock("@tauri-apps/api/event", () => ({
  listen: vi.fn().mockResolvedValue(() => {}),
}));

const windowMock = vi.hoisted(() => ({
  setSize: vi.fn().mockResolvedValue(undefined),
  setResizable: vi.fn().mockResolvedValue(undefined),
  center: vi.fn().mockResolvedValue(undefined),
  setPosition: vi.fn().mockResolvedValue(undefined),
  minimize: vi.fn().mockResolvedValue(undefined),
  close: vi.fn().mockResolvedValue(undefined),
}));
vi.mock("@tauri-apps/api/window", () => ({ getCurrentWindow: () => windowMock }));
vi.mock("@tauri-apps/api/dpi", () => ({
  LogicalSize: class {
    constructor(public width: number, public height: number) {}
  },
  LogicalPosition: class {
    constructor(public x: number, public y: number) {}
  },
}));

// Capture WebSocket instances so tests can push server messages.
const sockets: any[] = [];
class TestWS {
  static OPEN = 1;
  readyState = TestWS.OPEN;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((e: any) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;
  constructor(public url: string) {
    sockets.push(this);
    setTimeout(() => this.onopen?.(), 0);
  }
  send(data: string) { this.sent.push(data); }
  close() {}
}

function push(msg: Record<string, unknown>) {
  const ws = sockets[sockets.length - 1];
  act(() => ws.onmessage?.({ data: JSON.stringify(msg) }));
}

describe("HudPill", () => {
  beforeEach(() => {
    sockets.length = 0;
    vi.stubGlobal("WebSocket", TestWS);
    windowMock.setSize.mockClear();
    windowMock.minimize.mockClear();
    windowMock.close.mockClear();
  });

  it("exposes an accessible status live region and mute button", async () => {
    render(<HudPill />);
    expect(screen.getByRole("region", { name: /status and controls/i })).toBeInTheDocument();
    const status = screen.getByRole("status");
    expect(status).toHaveAttribute("aria-live", "polite");
    expect(screen.getByRole("button", { name: /mute microphone/i })).toBeInTheDocument();
  });

  it("sends mute to the sidecar and shows the muted state", async () => {
    const user = userEvent.setup();
    render(<HudPill />);
    await waitFor(() => expect(sockets.length).toBe(1));

    await user.click(screen.getByRole("button", { name: /mute microphone/i }));

    expect(sockets[0].sent.map((raw: string) => JSON.parse(raw))).toContainEqual({
      type: "set_muted",
      muted: true,
    });
    expect(screen.getByRole("button", { name: /unmute microphone/i })).toBeInTheDocument();
    expect(screen.getByRole("status").textContent).toContain("Muted");
  });

  it("fills the expanded window with a visible transcript panel", async () => {
    const user = userEvent.setup();
    render(<HudPill />);
    await waitFor(() => expect(sockets.length).toBe(1));
    push({ type: "transcript", text: "Hello from Murmur" });

    await user.click(screen.getByRole("button", { name: /expand hud/i }));

    const log = screen.getByRole("log", { name: /murmur ai transcript/i });
    expect(log).not.toHaveClass("sr-only");
    expect(within(log).getByText("Hello from Murmur")).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/type a command/i)).toBeInTheDocument();
  });

  it("minimizes and closes through the native window", async () => {
    const user = userEvent.setup();
    render(<HudPill />);

    await user.click(screen.getByRole("button", { name: /minimize hud/i }));
    expect(windowMock.minimize).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: /close murmur ai/i }));
    expect(invokeMock).toHaveBeenCalledWith("quit_app");
  });

  it("expands and collapses the HUD panel", async () => {
    const user = userEvent.setup();
    render(<HudPill />);

    windowMock.setResizable.mockClear();
    await user.click(screen.getByRole("button", { name: /expand hud/i }));
    await waitFor(() => {
      const size = windowMock.setSize.mock.calls.at(-1)?.[0];
      expect(size.width).toBe(560);
      expect(size.height).toBeLessThanOrEqual(620);
      expect(size.height).toBeGreaterThanOrEqual(240);
    });
    expect(windowMock.setResizable).toHaveBeenCalledWith(true);

    await user.click(screen.getByRole("button", { name: /collapse hud/i }));
    await waitFor(() => {
      const size = windowMock.setSize.mock.calls.at(-1)?.[0];
      expect(size.width).toBe(440);
      expect(size.height).toBe(120);
    });
  });

  it("does not approve a destructive action when Cancel has focus", async () => {
    const user = userEvent.setup();
    render(<HudPill />);
    await waitFor(() => expect(sockets.length).toBe(1));
    push({
      type: "confirmation_required",
      request_id: "req-1",
      description: "Delete C:\\data",
      command: "rd /s /q C:\\data",
    });

    screen.getByRole("button", { name: /cancel/i }).focus();
    await user.keyboard("{Enter}");

    const sent = sockets[0].sent.map((raw: string) => JSON.parse(raw));
    expect(sent).not.toContainEqual({ type: "confirm", request_id: "req-1", approved: true });
  });

  it("shows a working indicator while the backend is thinking", async () => {
    render(<HudPill />);
    await waitFor(() => expect(sockets.length).toBe(1));
    push({ type: "state", status: "THINKING", uptime_s: 1 });

    expect(screen.getByText("Working on it")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: /working on it/i })).toBeInTheDocument();
  });

  it("keeps the expanded log in a scrollable region", async () => {
    const user = userEvent.setup();
    render(<HudPill />);
    await waitFor(() => expect(sockets.length).toBe(1));
    push({ type: "transcript", text: "A long reply that should scroll" });

    await user.click(screen.getByRole("button", { name: /expand hud/i }));

    const log = screen.getByRole("log", { name: /murmur ai transcript/i });
    const scroller = log.parentElement as HTMLElement;
    expect(scroller.className).toContain("overflow-y-auto");
    expect(scroller.className).toContain("min-h-0");
    expect(screen.getByPlaceholderText(/type a command/i)).toBeInTheDocument();
  });

  it("shows each activity step and a working bar in typing mode", async () => {
    const user = userEvent.setup();
    render(<HudPill />);
    await waitFor(() => expect(sockets.length).toBe(1));
    push({ type: "activity", text: "Running open_application…" });
    push({ type: "state", status: "THINKING", uptime_s: 1 });

    await user.click(screen.getByRole("button", { name: /type a command/i }));

    expect(screen.getByRole("log", { name: /what murmur is doing/i })).toHaveTextContent(
      "Running open_application…"
    );
    expect(screen.getByRole("progressbar", { name: /working on it/i })).toBeInTheDocument();
  });

  it("marks the pill as a drag region", async () => {
    render(<HudPill />);
    const region = screen.getByRole("region", { name: /status and controls/i });
    expect(region).toHaveClass("app-region-drag");
  });

  it("reveals a typed-command field and sends text_input on Enter", async () => {
    const user = userEvent.setup();
    render(<HudPill />);
    await waitFor(() => expect(sockets.length).toBe(1));

    await user.click(screen.getByRole("button", { name: /type a command/i }));
    const input = screen.getByRole("textbox", { name: /command to send/i });
    await user.type(input, "open notepad{Enter}");

    expect(JSON.parse(sockets[0].sent.at(-1))).toEqual({
      type: "text_input",
      text: "open notepad",
    });
  });

  it("shows replies as a visible message while typing", async () => {
    const user = userEvent.setup();
    render(<HudPill />);
    await waitFor(() => expect(sockets.length).toBe(1));
    push({ type: "transcript", text: "Which file did you mean?" });

    await user.click(screen.getByRole("button", { name: /type a command/i }));

    const log = screen.getByRole("log", { name: /murmur ai transcript/i });
    expect(log).not.toHaveClass("sr-only");
    expect(within(log).getByText("Which file did you mean?")).toBeInTheDocument();
  });

  it("hides the typed-command field on Escape", async () => {
    const user = userEvent.setup();
    render(<HudPill />);
    await user.click(screen.getByRole("button", { name: /type a command/i }));
    const input = screen.getByRole("textbox", { name: /command to send/i });
    await user.type(input, "{Escape}");
    expect(screen.queryByRole("textbox", { name: /command to send/i })).toBeNull();
  });

  it("T shortcut opens the typed-command field", async () => {
    const user = userEvent.setup();
    render(<HudPill />);
    await user.keyboard("t");
    expect(screen.getByRole("textbox", { name: /command to send/i })).toBeInTheDocument();
  });

  it("toggles mute state and announces it", async () => {
    const user = userEvent.setup();
    render(<HudPill />);
    const btn = screen.getByRole("button", { name: /mute microphone/i });
    await user.click(btn);
    expect(screen.getByRole("button", { name: /unmute microphone/i })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(/microphone muted/i);
  });

  it("shows captions and updates status from WebSocket messages", async () => {
    render(<HudPill />);
    await waitFor(() => expect(sockets.length).toBe(1));
    push({ type: "text_output", text: "Opening Blender" });
    push({ type: "state", status: "SPEAKING", uptime_s: 1 });
    await waitFor(() => {
      expect(screen.getByTitle("Opening Blender")).toBeInTheDocument();
    });
    expect(screen.getByRole("status")).toHaveTextContent(/speaking/i);
  });

  it("renders a confirmation alert with accessible approve/cancel buttons", async () => {
    render(<HudPill />);
    await waitFor(() => expect(sockets.length).toBe(1));
    push({
      type: "confirmation_required",
      request_id: "req-1",
      description: "Delete file report.txt",
      command: "del report.txt",
    });
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveAttribute("aria-live", "assertive");
    expect(alert).toHaveTextContent("Delete file report.txt");
    expect(screen.getByRole("button", { name: /approve and run/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /cancel/i })).toBeInTheDocument();
  });

  it("sends approval over the WebSocket when confirmed", async () => {
    const user = userEvent.setup();
    render(<HudPill />);
    await waitFor(() => expect(sockets.length).toBe(1));
    push({
      type: "confirmation_required",
      request_id: "req-9",
      description: "Install Blender",
      command: "winget install --id BlenderFoundation.Blender --silent",
    });
    await user.click(await screen.findByRole("button", { name: /approve and run/i }));
    expect(sockets[0].sent.some((m: string) => m.includes('"approved":true'))).toBe(true);
  });

  it("shows a guidance form when the agent is stuck", async () => {
    render(<HudPill />);
    await waitFor(() => expect(sockets.length).toBe(1));
    push({ type: "guidance_required", request_id: "g-1", text: "I'm stuck on the menu" });
    expect(await screen.findByText(/i'm stuck on the menu/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/your guidance/i)).toBeInTheDocument();
  });

  it("exposes an accessible progress bar with a value", async () => {
    render(<HudPill />);
    await waitFor(() => expect(sockets.length).toBe(1));
    push({ type: "progress", text: "Downloading 45%", percent: 45 });
    const bar = await screen.findByRole("progressbar", { name: /download progress/i });
    expect(bar).toHaveAttribute("aria-valuenow", "45");
  });

  it("sleep button switches to standby and sends set_listening_mode", async () => {
    const user = userEvent.setup();
    render(<HudPill />);
    await waitFor(() => expect(sockets.length).toBe(1));

    const sleepBtn = screen.getByRole("button", { name: /put murmur to sleep/i });
    await user.click(sleepBtn);

    expect(screen.getByRole("button", { name: /wake murmur/i })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(/sleeping/i);
    expect(sockets[0].sent.some((m: string) => m.includes('"mode":"sleep"'))).toBe(true);
  });

  it("wake button resumes active mode and announces listening", async () => {
    const user = userEvent.setup();
    render(<HudPill />);
    await waitFor(() => expect(sockets.length).toBe(1));

    await user.click(screen.getByRole("button", { name: /put murmur to sleep/i }));
    await user.click(screen.getByRole("button", { name: /wake murmur/i }));

    expect(screen.getByRole("button", { name: /put murmur to sleep/i })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(/listening/i);
    expect(sockets[0].sent.some((m: string) => m.includes('"mode":"active"'))).toBe(true);
  });

  it("reflects a SLEEPING state broadcast from the backend", async () => {
    render(<HudPill />);
    await waitFor(() => expect(sockets.length).toBe(1));
    push({ type: "state", status: "SLEEPING", uptime_s: 1 });
    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent(/sleeping/i);
    });
    expect(screen.getByRole("button", { name: /wake murmur/i })).toBeInTheDocument();
  });

  it("shows an accessible update alert with the version and summary", async () => {
    render(<HudPill />);
    await waitFor(() => expect(sockets.length).toBe(1));
    push({
      type: "update_available",
      request_id: "u1",
      version: "9.9.9",
      notes: "Faster startup and better labels",
      text: "Version 9.9.9 is available. Install it?",
    });

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveAttribute("aria-live", "assertive");
    expect(alert).toHaveTextContent("Version 9.9.9");
    expect(alert).toHaveTextContent("Faster startup and better labels");
    expect(screen.getByRole("button", { name: /install update/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /skip this update/i })).toBeInTheDocument();
  });

  it("sends verbal-style update confirmation when Install is clicked", async () => {
    const user = userEvent.setup();
    render(<HudPill />);
    await waitFor(() => expect(sockets.length).toBe(1));
    push({
      type: "update_available",
      request_id: "u42",
      version: "9.9.9",
      notes: "Fixes",
      text: "Install?",
    });
    await user.click(await screen.findByRole("button", { name: /install update/i }));

    expect(sockets[0].sent.some((m: string) =>
      m.includes('"type":"update_confirm"') && m.includes('"approved":true')
    )).toBe(true);
  });

  it("clears the update alert once installation starts", async () => {
    render(<HudPill />);
    await waitFor(() => expect(sockets.length).toBe(1));
    push({
      type: "update_available",
      request_id: "u1",
      version: "9.9.9",
      notes: "Fixes",
      text: "Install?",
    });
    await screen.findByRole("button", { name: /install update/i });

    push({ type: "update_install", request_id: "u1", version: "9.9.9", text: "Installing version 9.9.9…" });
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: /install update/i })).not.toBeInTheDocument();
    });
    expect(screen.getByRole("status")).toHaveTextContent(/installing version 9\.9\.9/i);
  });
});
