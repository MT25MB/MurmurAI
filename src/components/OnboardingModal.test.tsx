import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import OnboardingModal from "./OnboardingModal";

const status = {
  ollama: { installed: true, running: true, install_path: "/usr/bin/ollama" },
  models: { "qwen2.5:7b": true, "qwen2.5-vl:7b": true },
  model_labels: { "qwen2.5:7b": "Fast chat", "qwen2.5-vl:7b": "Screen vision" },
  weights: { whisper: true, kokoro: true },
  weights_ready: true,
  model_cache_dir: "/home/user/.murmur-ai/models",
  required_models: ["qwen2.5:7b", "qwen2.5-vl:7b"],
  complete: false,
  onboarding_dismissed: false,
};
const perms = {
  platform: "Darwin",
  items: [{ key: "accessibility", label: "Accessibility", granted: true, hint: "Enable in System Settings." }],
};

function mockFetch() {
  vi.stubGlobal("fetch", vi.fn((url: string) => {
    const body = String(url).includes("permissions") ? perms : status;
    return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));
  }));
}

describe("OnboardingModal", () => {
  beforeEach(() => {
    mockFetch();
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [] }) },
    });
  });

  it("renders an accessible dialog with all setup sections", async () => {
    render(<OnboardingModal onComplete={() => {}} />);
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveAttribute("aria-labelledby", "setup-title");
    expect(screen.getByRole("heading", { name: /welcome to murmur ai/i })).toBeInTheDocument();
    expect(screen.getByText("Environment")).toBeInTheDocument();
    expect(screen.getByText("Local models")).toBeInTheDocument();
    expect(screen.getByText("Microphone")).toBeInTheDocument();
    expect(screen.getByText("Permissions")).toBeInTheDocument();
  });

  it("announces readiness via a polite live region", async () => {
    render(<OnboardingModal onComplete={() => {}} />);
    await screen.findByRole("dialog");
    const live = screen.getByRole("status");
    expect(live).toHaveAttribute("aria-live", "polite");
    expect(live).toHaveTextContent("You're all set.");
  });

  it("calls onComplete when setup is ready and Finish is clicked", async () => {
    const user = userEvent.setup();
    const done = vi.fn();
    render(<OnboardingModal onComplete={done} />);
    const button = await screen.findByRole("button", { name: /start murmur ai/i });
    await user.click(button);
    await waitFor(() => expect(done).toHaveBeenCalledOnce());
  });

  it("has labeled controls for mic test, permissions and model pulls", async () => {
    render(<OnboardingModal onComplete={() => {}} />);
    await screen.findByRole("dialog");
    expect(screen.getByRole("button", { name: /test your microphone/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /check your system permissions/i })).toBeInTheDocument();
    expect(screen.getByRole("meter", { name: /microphone input level/i })).toBeInTheDocument();
  });

  it("shows the backend error alert with a retry button when fetch fails", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new Error("offline"))));
    render(<OnboardingModal onComplete={() => {}} />);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveAttribute("aria-live", "assertive");
    expect(alert).toHaveTextContent(/can't reach the local backend/i);
    expect(screen.getByRole("button", { name: /try connecting/i })).toBeInTheDocument();
  });
});
