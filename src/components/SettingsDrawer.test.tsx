import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
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
};

let current = { ...defaults };
let posts: Array<Record<string, unknown>> = [];

vi.mock("@tauri-apps/api/event", () => ({ listen: vi.fn().mockResolvedValue(() => {}) }));

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
    vi.stubGlobal("fetch", mockFetch());
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
});
