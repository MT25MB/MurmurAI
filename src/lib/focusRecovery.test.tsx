import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import {
  FOCUS_RESTORED_EVENT,
  focusAnnouncement,
  isFocusLost,
  useFocusRecovery,
} from "./focusRecovery";

const listeners: Record<string, (event: { payload: string }) => void> = {};
vi.mock("@tauri-apps/api/event", () => ({
  listen: vi.fn((event: string, callback: (event: { payload: string }) => void) => {
    listeners[event] = callback;
    return Promise.resolve(() => {
      delete listeners[event];
    });
  }),
}));

function Harness() {
  const { containerRef, announcement } = useFocusRecovery();
  return (
    <div ref={containerRef} tabIndex={-1} data-testid="recovery-root">
      <button type="button">First control</button>
      <div role="status" aria-live="polite">
        {announcement}
      </div>
    </div>
  );
}

describe("isFocusLost", () => {
  it("detects focus that fell back to the document", () => {
    expect(isFocusLost(null)).toBe(true);
    expect(isFocusLost(document.body)).toBe(true);
    expect(isFocusLost(document.documentElement)).toBe(true);
  });

  it("leaves real control focus alone", () => {
    const button = document.createElement("button");
    expect(isFocusLost(button)).toBe(false);
  });
});

describe("useFocusRecovery", () => {
  beforeEach(() => {
    for (const key of Object.keys(listeners)) delete listeners[key];
  });

  it("announces the exact message the Rust shell emits", () => {
    expect(focusAnnouncement("Murmur AI")).toBe(
      "Murmur AI window is active. Keyboard focus restored.",
    );
  });

  it("restores focus to the HUD root and re-announces after returning", () => {
    render(<Harness />);
    const root = screen.getByTestId("recovery-root");
    const live = screen.getByRole("status");

    fireEvent.blur(window);
    expect(live.textContent).toBe("");

    (document.activeElement as HTMLElement | null)?.blur();
    fireEvent.focus(window);

    expect(document.activeElement).toBe(root);
    expect(root.dataset.focusRestored).toBe("true");
    expect(live.textContent).toBe(focusAnnouncement("Murmur AI"));
  });

  it("never steals focus from a real control and never traps Tab", () => {
    render(<Harness />);
    const root = screen.getByTestId("recovery-root");
    const button = screen.getByRole("button", { name: /first control/i });

    button.focus();
    fireEvent.blur(window);
    fireEvent.focus(window);
    expect(document.activeElement).toBe(button);

    const notCancelled = fireEvent.keyDown(document, { key: "Tab" });
    expect(notCancelled).toBe(true);
    expect(root.dataset.focusRestored).toBeUndefined();
  });

  it("recovers from the native Tauri focus event as well", async () => {
    render(<Harness />);
    // The helper imports the event API dynamically; let that promise settle.
    await vi.waitFor(() => expect(listeners[FOCUS_RESTORED_EVENT]).toBeTypeOf("function"));
    const callback = listeners[FOCUS_RESTORED_EVENT];

    fireEvent.blur(window);
    act(() => callback({ payload: focusAnnouncement("Murmur AI") }));

    expect(screen.getByRole("status").textContent).toBe(focusAnnouncement("Murmur AI"));
  });
});
