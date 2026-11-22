import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import type { ClientMessage, ServerMessage } from "./websocket";

const { invokeMock, listenMock } = vi.hoisted(() => ({
  invokeMock: vi.fn(),
  listenMock: vi.fn(),
}));

vi.mock("@tauri-apps/api/core", () => ({ invoke: invokeMock }));
vi.mock("@tauri-apps/api/event", () => ({ listen: listenMock }));

import { checkForUpdates, installUpdate, useAutoUpdater } from "./updater";

const available = {
  available: true,
  version: "9.9.9",
  notes: "Faster startup",
  currentVersion: "1.0.0",
  error: null,
};

describe("updater bridge", () => {
  beforeEach(() => {
    invokeMock.mockReset();
    listenMock.mockReset();
    listenMock.mockResolvedValue(() => {});
  });

  it("reports an available release from the Tauri command", async () => {
    invokeMock.mockResolvedValue(available);
    await expect(checkForUpdates()).resolves.toEqual(available);
    expect(invokeMock).toHaveBeenCalledWith("check_for_updates");
  });

  it("degrades gracefully when GitHub is unreachable", async () => {
    invokeMock.mockRejectedValue(new Error("network unreachable"));
    const result = await checkForUpdates();
    expect(result.available).toBe(false);
    expect(result.error).toContain("network unreachable");
  });

  it("installs through the Tauri command and reports failures", async () => {
    invokeMock.mockResolvedValueOnce(undefined);
    await expect(installUpdate()).resolves.toEqual({ ok: true });
    expect(invokeMock).toHaveBeenCalledWith("install_update");

    invokeMock.mockRejectedValueOnce(new Error("verification failed"));
    const failed = await installUpdate();
    expect(failed.ok).toBe(false);
  });

  it("relays a discovered update to the backend exactly once", async () => {
    invokeMock.mockResolvedValue(available);
    const send = vi.fn<(message: ClientMessage) => void>();
    renderHook(() => useAutoUpdater(send, null));

    await waitFor(() => {
      expect(send).toHaveBeenCalledWith({
        type: "update_available",
        version: "9.9.9",
        notes: "Faster startup",
      });
    });
    expect(send.mock.calls.filter(([m]) => m.type === "update_available")).toHaveLength(1);
  });

  it("does not announce an update when offline", async () => {
    invokeMock.mockRejectedValue(new Error("offline"));
    const send = vi.fn<(message: ClientMessage) => void>();
    renderHook(() => useAutoUpdater(send, null));

    await waitFor(() => expect(send).toHaveBeenCalled());
    expect(send.mock.calls.some(([m]) => m.type === "update_available")).toBe(false);
    expect(send.mock.calls.some(([m]) => m.type === "update_status")).toBe(true);
  });

  it("re-checks when the user asks by voice and installs on confirmation", async () => {
    invokeMock.mockResolvedValue(available);
    const send = vi.fn<(message: ClientMessage) => void>();
    const { rerender } = renderHook(
      ({ message }: { message: ServerMessage | null }) => useAutoUpdater(send, message),
      { initialProps: { message: null as ServerMessage | null } },
    );

    await waitFor(() => expect(send).toHaveBeenCalled());
    const before = invokeMock.mock.calls.length;

    rerender({
      message: { type: "update_check_request", text: "Checking for updates…" } as ServerMessage,
    });
    await waitFor(() => expect(invokeMock.mock.calls.length).toBeGreaterThan(before));

    invokeMock.mockClear();
    rerender({
      message: {
        type: "update_install",
        request_id: "r1",
        version: "9.9.9",
        text: "Installing…",
      } as ServerMessage,
    });
    await waitFor(() => expect(invokeMock).toHaveBeenCalledWith("install_update"));
  });

  it("subscribes to Tauri update events", async () => {
    renderHook(() => useAutoUpdater(vi.fn(), null));
    await waitFor(() => expect(listenMock).toHaveBeenCalled());
    expect(listenMock.mock.calls[0][0]).toBe("murmur://update-available");
  });
});
