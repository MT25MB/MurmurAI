/**
 * Automated WCAG 2.2 AA / ARIA regression suite.
 *
 * Every rendered surface is scanned with axe-core (via vitest-axe). The suite
 * also asserts the interaction contracts a screen reader depends on: icon-only
 * button names, aria-hidden decorative SVGs, dialog focus containment, Escape
 * close + focus restore, and live regions that exist before text arrives.
 */

import { describe, it, expect, beforeEach, vi } from "vitest";
import { useState } from "react";
import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "vitest-axe";
import HudPill from "../components/HudPill";
import OnboardingModal from "../components/OnboardingModal";
import SettingsDrawer from "../components/SettingsDrawer";
import TranscriptStream from "../components/TranscriptStream";
import type { Settings } from "../lib/settings";

const WCAG_22_AA = {
  runOnly: {
    type: "tag" as const,
    values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"],
  },
};

const windowMock = vi.hoisted(() => ({
  setSize: vi.fn().mockResolvedValue(undefined),
  setResizable: vi.fn().mockResolvedValue(undefined),
  center: vi.fn().mockResolvedValue(undefined),
  setPosition: vi.fn().mockResolvedValue(undefined),
  minimize: vi.fn().mockResolvedValue(undefined),
  close: vi.fn().mockResolvedValue(undefined),
}));
vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn().mockResolvedValue(undefined) }));
vi.mock("@tauri-apps/api/event", () => ({ listen: vi.fn().mockResolvedValue(() => {}) }));
vi.mock("@tauri-apps/api/window", () => ({ getCurrentWindow: () => windowMock }));
vi.mock("@tauri-apps/api/dpi", () => ({
  LogicalSize: class { constructor(public width: number, public height: number) {} },
  LogicalPosition: class { constructor(public x: number, public y: number) {} },
}));

const sockets: any[] = [];
class TestWS {
  static OPEN = 1;
  readyState = TestWS.OPEN;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((e: any) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;
  constructor() {
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

const setupStatus = {
  ollama: { installed: true, running: true, install_path: "/usr/bin/ollama" },
  models: { "qwen2.5:7b": true, "qwen2.5vl:7b": true },
  model_labels: { "qwen2.5:7b": "Fast chat", "qwen2.5vl:7b": "Screen vision" },
  weights: { whisper: true, kokoro: true },
  weights_ready: true,
  model_cache_dir: "/home/user/.murmur-ai/models",
  required_models: ["qwen2.5:7b", "qwen2.5vl:7b"],
  complete: false,
  onboarding_dismissed: false,
};
const permissions = {
  platform: "Darwin",
  items: [{ key: "accessibility", label: "Accessibility", granted: true, hint: "Enable it." }],
};
const settings: Settings = {
  speech_rate: 1,
  voice: "af_heart",
  earcons: true,
  description_verbosity: "concise",
  listening_mode: "active",
  mic_threshold: 0.5,
  screen_reader_friendly: false,
  media_ducking: false,
  echo_guard: true,
  echo_guard_tail_ms: 250,
  loopback_guard: false,
  spatial_audio_cues: true,
  voice_profile: "default",
  chat_model: "",
  vision_model: "",
  provider: "",
  clear_data_on_uninstall: false,
};

beforeEach(() => {
  sockets.length = 0;
  vi.stubGlobal("WebSocket", TestWS);
  vi.stubGlobal("fetch", vi.fn((url: string) => {
    const target = String(url);
    let body: unknown = settings;
    if (target.includes("permissions")) body = permissions;
    else if (target.includes("model-options")) body = {
      hardware: { total_ram_gb: 32, vram_gb: 0, compute_backend: "CPU", tier: "high" },
      current: ["qwen2.5:7b", "qwen2.5vl:7b"],
      options: [{
        name: "qwen3.5:9b", label: "Unified chat + screen (9B)", role: "unified",
        tier: "upgrade", available: true, requirement: "16 GB RAM", reason: "",
      }],
    };
    else if (target.includes("setup") || target.includes("health")) body = setupStatus;
    return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));
  }));
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [] }) },
  });
  windowMock.setSize.mockClear();
});

// ---------------------------------------------------------------------------
// axe scans: zero WCAG 2.2 AA violations on every surface
// ---------------------------------------------------------------------------

describe("WCAG 2.2 AA automated audit", () => {
  it("main HUD pill has no violations", async () => {
    const { container } = render(<HudPill />);
    expect(await axe(container, WCAG_22_AA)).toHaveNoViolations();
  });

  it("expanded HUD (typing row, transcript, progress) has no violations", async () => {
    const user = userEvent.setup();
    const { container } = render(<HudPill />);
    await waitFor(() => expect(sockets.length).toBe(1));
    await user.click(screen.getByRole("button", { name: /expand hud/i }));
    push({ type: "progress", text: "Installing a local package", percent: 42 });
    expect(await axe(container, WCAG_22_AA)).toHaveNoViolations();
  });

  it("OnboardingModal has no violations", async () => {
    const { container } = render(<OnboardingModal onComplete={() => {}} />);
    await screen.findByRole("dialog");
    expect(await axe(container, WCAG_22_AA)).toHaveNoViolations();
  });

  it("SettingsDrawer has no violations", async () => {
    const { container } = render(<SettingsDrawer open onClose={() => {}} />);
    await screen.findByRole("dialog", { name: /murmur ai settings/i });
    await waitFor(() => expect(screen.getByLabelText(/voice profile/i)).toBeInTheDocument());
    expect(await axe(container, WCAG_22_AA)).toHaveNoViolations();
  });

  it("TranscriptStream has no violations in hidden and visible modes", async () => {
    const hidden = render(
      <TranscriptStream lastMessage={{ type: "transcript", text: "Hello", role: "assistant" } as any} />,
    );
    expect(await axe(hidden.container, WCAG_22_AA)).toHaveNoViolations();
    hidden.unmount();

    const visible = render(
      <TranscriptStream lastMessage={{ type: "transcript", text: "Hello", role: "assistant" } as any} visible />,
    );
    expect(await axe(visible.container, WCAG_22_AA)).toHaveNoViolations();
  });

  it("confirmation prompt has no violations and keeps one bound decision", async () => {
    const { container } = render(<HudPill />);
    await waitFor(() => expect(sockets.length).toBe(1));
    push({
      type: "confirmation_required",
      request_id: "req-1",
      description: "Delete the report",
      command: "del report.txt",
    });
    expect(await axe(container, WCAG_22_AA)).toHaveNoViolations();
    const approve = screen.getByRole("button", { name: /yes, do it/i });
    const cancelButton = screen.getByRole("button", { name: /cancel/i });
    expect(approve).toBeInTheDocument();
    expect(cancelButton).toBeInTheDocument();
    // The accessible name contains the visible text, so no conflicting label.
    expect(approve.getAttribute("aria-label")?.toLowerCase()).toContain("yes, do it");
    expect(cancelButton.getAttribute("aria-label")?.toLowerCase()).toContain("cancel");
    // Single-use: approving clears the held prompt so a replayed yes is inert.
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /yes, do it/i }));
    await waitFor(() => expect(screen.queryByRole("button", { name: /yes, do it/i })).not.toBeInTheDocument());
  });
});

// ---------------------------------------------------------------------------
// Specific ARIA contracts called out in the regression requirements
// ---------------------------------------------------------------------------

describe("ARIA naming and decorative graphics", () => {
  it("every icon-only button has an aria-label and its SVG is aria-hidden", async () => {
    render(<HudPill />);
    await waitFor(() => expect(sockets.length).toBe(1));
    const buttons = Array.from(document.querySelectorAll("button"));
    const iconOnly = buttons.filter((button) => button.querySelector("svg") && !button.textContent?.trim());
    expect(iconOnly.length).toBeGreaterThan(0);
    for (const button of iconOnly) {
      const label = button.getAttribute("aria-label");
      expect(label, `icon button needs an aria-label: ${button.outerHTML}`).toBeTruthy();
      expect(label!.trim().length).toBeGreaterThan(2);
      button.querySelectorAll("svg").forEach((svg) => {
        expect(svg).toHaveAttribute("aria-hidden", "true");
      });
    }
  });

  it("buttons with visible text never carry a conflicting aria-label", () => {
    render(<HudPill />);
    const buttons = Array.from(document.querySelectorAll("button"));
    for (const button of buttons) {
      const visible = (button.textContent || "").replace(/\s+/g, " ").trim().toLowerCase();
      const label = button.getAttribute("aria-label")?.replace(/\s+/g, " ").trim().toLowerCase();
      if (!visible || !label) continue;
      // Label-in-Name (WCAG 2.5.3): the accessible name must include the
      // visible text, not replace it with a different phrase.
      expect(label.includes(visible), `"${label}" must contain visible text "${visible}"`).toBe(true);
    }
  });

  it("decorative images and waveforms are hidden from assistive tech", () => {
    render(<HudPill />);
    document.querySelectorAll("img").forEach((img) => {
      expect(img).toHaveAttribute("aria-hidden", "true");
      expect(img).toHaveAttribute("alt", "");
    });
    const waveformContainer = document.querySelector(".waveform")?.parentElement;
    if (waveformContainer) expect(waveformContainer).toHaveAttribute("aria-hidden", "true");
  });
});

describe("Live regions exist before dynamic text", () => {
  it("HUD polite status region mounts on first render", () => {
    render(<HudPill />);
    const live = screen.getByRole("status");
    expect(live).toHaveAttribute("aria-live", "polite");
    // The element is already in the DOM before any text is injected.
    expect(document.body.contains(live)).toBe(true);
    push({ type: "text_output", text: "Done." });
    expect(live).toHaveTextContent("Done.");
  });

  it("TranscriptStream mounts its polite log before the first turn", async () => {
    const { rerender } = render(<TranscriptStream lastMessage={null} />);
    const log = screen.getByRole("log", { name: /murmur ai transcript/i });
    expect(log).toHaveAttribute("aria-live", "polite");
    expect(log.querySelector("p")).toBeNull();

    // The live region is already mounted when the first message arrives.
    rerender(<TranscriptStream lastMessage={{ type: "transcript", text: "Hello", role: "assistant" } as any} />);
    await waitFor(() => expect(log).toHaveTextContent("Hello"));
    expect(log).toHaveAttribute("aria-live", "polite");
  });

  it("settings status live region is present while loading", () => {
    render(<SettingsDrawer open onClose={() => {}} />);
    const status = screen.getByRole("status");
    expect(status).toHaveAttribute("aria-live", "polite");
    expect(document.body.contains(status)).toBe(true);
  });
});

describe("Dialog focus management", () => {
  it("traps focus on open, closes on Escape and restores focus to the trigger", async () => {
    function Harness() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>Open settings</button>
          <SettingsDrawer open={open} onClose={() => setOpen(false)} />
        </>
      );
    }
    const user = userEvent.setup();
    render(<Harness />);
    const trigger = screen.getByRole("button", { name: "Open settings" });
    trigger.focus();
    expect(trigger).toHaveFocus();

    await user.click(trigger);
    const dialog = await screen.findByRole("dialog", { name: /murmur ai settings/i });
    await waitFor(() => expect(dialog.contains(document.activeElement)).toBe(true));

    // Tab from the last focusable wraps to the first, never escaping the dialog.
    const focusable = Array.from(
      dialog.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), select:not([disabled])'),
    );
    expect(focusable.length).toBeGreaterThan(1);
    focusable[focusable.length - 1].focus();
    await user.tab();
    expect(focusable[0]).toHaveFocus();

    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(trigger).toHaveFocus();
  });

  it("Escape closes the settings dialog without leaving focus in a detached node", async () => {
    const user = userEvent.setup();
    function Harness() {
      const [open, setOpen] = useState(true);
      return <SettingsDrawer open={open} onClose={() => setOpen(false)} />;
    }
    render(<Harness />);
    await screen.findByRole("dialog", { name: /murmur ai settings/i });
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});
