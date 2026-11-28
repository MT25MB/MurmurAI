import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import SettingsDrawer from "./SettingsDrawer";
import App from "../App";

const defaults = {
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
  autostart_enabled: false,
  clear_data_on_uninstall: false,
};

let current = { ...defaults };
let posts: Array<Record<string, unknown>> = [];

const { invokeMock, listenMock } = vi.hoisted(() => ({
  invokeMock: vi.fn(),
  listenMock: vi.fn().mockResolvedValue(() => {}),
}));

vi.mock("@tauri-apps/api/core", () => ({ invoke: invokeMock }));
vi.mock("@tauri-apps/api/event", () => ({ listen: listenMock }));

// Keep App's bounded backend polling instantaneous in tests.
vi.mock("../lib/backendReady", () => ({
  waitForBackend: async (probe: () => Promise<unknown>) => {
    try {
      await probe();
      return { ready: true, attempts: 1 };
    } catch {
      return { ready: false, attempts: 1 };
    }
  },
}));

const windowMock = vi.hoisted(() => ({
  setSize: vi.fn().mockResolvedValue(undefined),
  setResizable: vi.fn().mockResolvedValue(undefined),
  center: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("@tauri-apps/api/window", () => ({
  getCurrentWindow: () => windowMock,
}));

vi.mock("@tauri-apps/api/dpi", () => ({
  LogicalSize: class {
    constructor(public width: number, public height: number) {}
  },
}));

function mockFetch() {
  return vi.fn((input: string | URL | Request, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    let body: Record<string, unknown> = {};
    if (url.endsWith("/setup/status")) {
      return Promise.resolve(new Response(JSON.stringify({
        ollama: { installed: true, running: true, install_path: null },
        models: {},
        model_labels: {},
        weights: { whisper: true, kokoro: true },
        weights_ready: true,
        model_cache_dir: "/tmp/models",
        required_models: [],
        complete: true,
        onboarding_dismissed: true,
      }), { status: 200 }));
    }
    if (url.endsWith("/settings") && method === "GET") {
      return Promise.resolve(new Response(JSON.stringify(current), { status: 200 }));
    }
    if (url.endsWith("/settings") && method === "POST") {
      body = JSON.parse(String(init?.body ?? "{}"));
      posts.push(body);
      current = { ...current, ...body } as typeof current;
      return Promise.resolve(new Response(JSON.stringify(current), { status: 200 }));
    }
    if (url.endsWith("/settings/reset")) {
      current = { ...defaults };
      return Promise.resolve(new Response(JSON.stringify(current), { status: 200 }));
    }
    if (url.endsWith("/model-options")) {
      return Promise.resolve(new Response(JSON.stringify({
        hardware: { total_ram_gb: 32, vram_gb: 0, compute_backend: "CPU", tier: "high" },
        current: ["qwen2.5:7b", "qwen2.5vl:7b"],
        options: [
          {
            name: "qwen3.5:9b", label: "Unified chat + screen (9B)", role: "unified",
            tier: "upgrade", available: true, requirement: "16 GB RAM or 6 GB GPU VRAM", reason: "",
          },
          {
            name: "qwen3.5:27b", label: "Unified chat + screen (27B)", role: "unified",
            tier: "upgrade", available: false, requirement: "24 GB GPU VRAM required",
            reason: "Needs 24 GB GPU VRAM; this device has 32 GB RAM and 0 GB VRAM.",
          },
        ],
      }), { status: 200 }));
    }
    if (url.endsWith("/models/install") && method === "POST") {
      return Promise.resolve(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    }
    if (url.endsWith("/models/use") && method === "POST") {
      body = JSON.parse(String(init?.body ?? "{}"));
      const model = String(body.model);
      const role = String(body.role);
      current = {
        ...current,
        ...(role === "vision" ? { vision_model: model } : role === "chat" ? { chat_model: model } : {
          chat_model: model, vision_model: model,
        }),
      } as typeof current;
      return Promise.resolve(new Response(JSON.stringify({ ok: true, summary: `${model} selected.` }), { status: 200 }));
    }
    if (url.endsWith("/providers") && method === "GET") {
      return Promise.resolve(new Response(JSON.stringify({
        providers: [{ name: "llama", base_url: "http://127.0.0.1:8080/v1", model: "local", cloud: false, api_key_ref: "", key_configured: false }],
      }), { status: 200 }));
    }
    if (url.endsWith("/providers/remove") && method === "POST") {
      return Promise.resolve(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    }
    if (url.endsWith("/diagnostics")) {
      return Promise.resolve(
        new Response(JSON.stringify({ checks: {}, issues: [], summary: "Everything looks healthy." }), { status: 200 }),
      );
    }
    return Promise.resolve(new Response("{}", { status: 200 }));
  });
}

describe("SettingsDrawer", () => {
  beforeEach(() => {
    current = { ...defaults };
    posts = [];
    invokeMock.mockReset();
    invokeMock.mockImplementation((command: string) =>
      command === "set_autostart"
        ? Promise.resolve(true)
        : Promise.resolve({
            available: false, version: null, notes: null, currentVersion: "1.2.68", error: null,
          }),
    );
    listenMock.mockClear();
    listenMock.mockResolvedValue(() => {});
    windowMock.setSize.mockClear();
    windowMock.setResizable.mockClear();
    windowMock.center.mockClear();
    vi.stubGlobal("fetch", mockFetch());
  });

  it("offers only hardware-supported model upgrades", async () => {
    const user = userEvent.setup();
    render(<SettingsDrawer open onClose={() => {}} />);
    const group = await screen.findByRole("group", { name: /optional model upgrades/i });
    expect(within(group).getByRole("button", { name: /install qwen3\.5:9b/i })).toBeEnabled();
    const unsupported = within(group).getByRole("button", { name: /install qwen3\.5:27b/i });
    expect(unsupported).toBeDisabled();
    expect(group).toHaveTextContent(/24 GB GPU VRAM/);

    await user.click(within(group).getByRole("button", { name: /use qwen3\.5:9b/i }));
    await waitFor(() => expect(current.vision_model).toBe("qwen3.5:9b"));
    expect(current.chat_model).toBe("qwen3.5:9b");
  });

  it("uses gated selects instead of free-text model fields", async () => {
    render(<SettingsDrawer open onClose={() => {}} />);
    const group = await screen.findByRole("group", { name: /models/i });

    expect(within(group).getByLabelText("Chat model").tagName).toBe("SELECT");
    expect(within(group).getByLabelText("Vision model").tagName).toBe("SELECT");
    expect(within(group).getAllByRole("option", { name: /qwen3\.5:27b/ }).every((o) => (o as HTMLOptionElement).disabled)).toBe(true);
    expect(within(group).getAllByRole("option", { name: /qwen3\.5:9b/ }).some((o) => !(o as HTMLOptionElement).disabled)).toBe(true);
  });

  it("lists registered providers with an explicit local default", async () => {
    const user = userEvent.setup();
    render(<SettingsDrawer open onClose={() => {}} />);
    const group = await screen.findByRole("group", { name: /model providers/i });

    expect(within(group).getByText("llama")).toBeInTheDocument();
    expect(within(group).getByText(/local · local/)).toBeInTheDocument();
    const useLocal = within(group).getByRole("button", { name: /use local ollama/i });
    expect(useLocal).toBeDisabled();
    await user.click(within(group).getByRole("button", { name: /^use$/i }));
    await waitFor(() => expect(posts).toContainEqual({ provider: "llama" }));
  });

  it("checks for and installs updates from Settings", async () => {
    const user = userEvent.setup();
    invokeMock.mockImplementation((command: string) =>
      command === "check_for_updates"
        ? Promise.resolve({ available: true, version: "9.9.9", notes: "New release", currentVersion: "1.2.60", error: null })
        : Promise.resolve(undefined),
    );
    render(<SettingsDrawer open onClose={() => {}} />);
    const group = await screen.findByRole("group", { name: /updates/i });

    await user.click(within(group).getByRole("button", { name: /check for updates/i }));
    expect(await within(group).findByText(/version 9\.9\.9 is available/i)).toBeInTheDocument();

    const install = within(group).getByRole("button", { name: /download & install/i });
    expect(install).toBeEnabled();
    await user.click(install);
    expect(invokeMock).toHaveBeenCalledWith("install_update");
  });

  it("exposes an opt-in launch-at-login toggle", async () => {
    const user = userEvent.setup();
    render(<SettingsDrawer open onClose={() => {}} />);
    const toggle = await screen.findByLabelText(/start murmur when i log in/i);
    expect(toggle).not.toBeChecked();

    await user.click(toggle);
    await waitFor(() => expect(posts).toContainEqual({ autostart_enabled: true }));
    expect(invokeMock).toHaveBeenCalledWith("set_autostart", { enabled: true });
  });

  it("renders a full-ARIA dialog with every settings group", async () => {
    render(<SettingsDrawer open onClose={() => {}} />);

    await screen.findByRole("group", { name: /speech and voice/i });
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAttribute("aria-labelledby", "settings-title");
    expect(screen.getByRole("heading", { name: /murmur ai settings/i })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: /speech and voice/i })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: /listening and privacy/i })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: /models/i })).toBeInTheDocument();
  });

  it("loads values from the backend config", async () => {
    current = { ...current, speech_rate: 1.4, voice: "af_bella", earcons: false, description_verbosity: "detailed" };
    render(<SettingsDrawer open onClose={() => {}} />);

    await waitFor(() => {
      expect(screen.getByLabelText("Voice")).toHaveValue("af_bella");
    });
    expect(screen.getByLabelText("Speech rate: 1.40x")).toHaveValue("1.4");
    expect(screen.getByLabelText("Play state chimes")).not.toBeChecked();
    expect(screen.getByLabelText("Screen descriptions")).toHaveValue("detailed");
  });

  it("saves a changed setting and announces it", async () => {
    const user = userEvent.setup();
    render(<SettingsDrawer open onClose={() => {}} />);
    await screen.findByLabelText("Voice");

    await user.selectOptions(screen.getByLabelText("Voice"), "am_adam");
    await waitFor(() => expect(posts).toContainEqual({ voice: "am_adam" }));
    expect(screen.getByText("Settings saved.")).toBeInTheDocument();
  });

  it("toggles chimes and listening mode", async () => {
    const user = userEvent.setup();
    render(<SettingsDrawer open onClose={() => {}} />);
    await screen.findByLabelText("Play state chimes");

    await user.click(screen.getByLabelText("Play state chimes"));
    expect(posts).toContainEqual({ earcons: false });

    await user.selectOptions(screen.getByLabelText("Listening mode"), "wake");
    expect(posts).toContainEqual({ listening_mode: "wake" });
  });

  it("opt-in to clearing data on uninstall is off by default and can be enabled", async () => {
    const user = userEvent.setup();
    render(<SettingsDrawer open onClose={() => {}} />);

    const choice = await screen.findByLabelText(
      "Clear my data if Murmur AI is uninstalled"
    );
    expect(choice).not.toBeChecked();

    await user.click(choice);
    expect(posts).toContainEqual({ clear_data_on_uninstall: true });
  });

  it("runs diagnostics and shows the spoken report", async () => {
    const user = userEvent.setup();
    render(<SettingsDrawer open onClose={() => {}} />);
    await screen.findByRole("button", { name: /run diagnostics/i });

    await user.click(screen.getByRole("button", { name: /run diagnostics/i }));
    expect(await screen.findByText("Everything looks healthy.")).toBeInTheDocument();
  });

  it("closes on Escape and on the Close button", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<SettingsDrawer open onClose={onClose} />);
    await screen.findByRole("dialog");

    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: /close settings/i }));
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("renders nothing when closed", () => {
    render(<SettingsDrawer open={false} onClose={() => {}} />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("opens from the Ctrl+, keyboard shortcut", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.keyboard("{Control>},{/Control}");
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });

  it("gives the connecting message room before setup status is known", async () => {
    // A never-resolving probe keeps App in its connecting state.
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
    render(<App />);
    await waitFor(() => expect(windowMock.setSize).toHaveBeenCalled());
    const size = windowMock.setSize.mock.calls.at(-1)?.[0];
    expect(size.width).toBe(560);
    expect(size.height).toBeGreaterThan(84);
    expect(screen.getByText("Connecting to the local backend…")).toBeInTheDocument();
  });

  it("shrinks the native window to the HUD size when setup is complete", async () => {
    render(<App />);
    await waitFor(() => {
      const size = windowMock.setSize.mock.calls.at(-1)?.[0];
      expect(size?.width).toBe(560);
      expect(size?.height).toBe(120);
    });
    expect(windowMock.setResizable).toHaveBeenCalledWith(false);
  });

  it("enlarges the native window so the Retry button is reachable on backend failure", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new Error("Failed to fetch"))));
    render(<App />);
    await screen.findByRole("alert");
    await waitFor(() => expect(windowMock.setSize).toHaveBeenCalled());
    const size = windowMock.setSize.mock.calls.at(-1)?.[0];
    expect(size.width).toBe(560);
    expect(size.height).toBe(680);
    expect(windowMock.setResizable).toHaveBeenCalledWith(true);
    expect(screen.getByRole("button", { name: /try connecting/i })).toBeInTheDocument();
  });
});
