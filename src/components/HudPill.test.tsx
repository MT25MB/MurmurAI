import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import HudPill from "./HudPill";

// The updater bridge is exercised in src/lib/updater.test.ts; here we keep the
// HUD unit tests offline so they only observe WebSocket messages.
vi.mock("@tauri-apps/api/core", () => ({
  invoke: vi.fn().mockRejectedValue(new Error("not running in Tauri")),
}));
vi.mock("@tauri-apps/api/event", () => ({
  listen: vi.fn().mockResolvedValue(() => {}),
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
  });

  it("exposes an accessible status live region and mute button", async () => {
    render(<HudPill />);
    expect(screen.getByRole("region", { name: /status and controls/i })).toBeInTheDocument();
    const status = screen.getByRole("status");
    expect(status).toHaveAttribute("aria-live", "polite");
    expect(screen.getByRole("button", { name: /mute microphone/i })).toBeInTheDocument();
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
    expect(screen.getByRole("button", { name: /cancel the action/i })).toBeInTheDocument();
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
    const bar = await screen.findByRole("progressbar");
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
    expect(screen.getByRole("button", { name: /download and install the update/i })).toBeInTheDocument();
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
    await user.click(await screen.findByRole("button", { name: /download and install the update/i }));

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
    await screen.findByRole("button", { name: /download and install the update/i });

    push({ type: "update_install", request_id: "u1", version: "9.9.9", text: "Installing version 9.9.9…" });
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: /download and install the update/i })).not.toBeInTheDocument();
    });
    expect(screen.getByRole("status")).toHaveTextContent(/installing version 9\.9\.9/i);
  });
});
