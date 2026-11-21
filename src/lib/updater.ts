/**
 * Tauri updater bridge. The Rust commands own the network call; the HUD owns
 * the WebSocket to the Python sidecar, so update state is relayed here.
 *
 * Offline / unverified manifests are normal states: they never throw and never
 * produce a spoken "update available" prompt.
 */

import { useEffect, useRef } from "react";
import { invoke } from "@tauri-apps/api/core";
import type { ClientMessage, ServerMessage } from "./websocket";

export interface UpdateInfo {
  available: boolean;
  version: string | null;
  notes: string | null;
  currentVersion: string;
  error: string | null;
}

export interface InstallResult {
  ok: boolean;
  error?: string;
}

export async function checkForUpdates(): Promise<UpdateInfo> {
  try {
    const result = await invoke<UpdateInfo | null>("check_for_updates");
    if (!result || typeof result.available !== "boolean") {
      return {
        available: false,
        version: null,
        notes: null,
        currentVersion: "",
        error: "Unexpected response from the updater",
      };
    }
    return result;
  } catch (error) {
    return {
      available: false,
      version: null,
      notes: null,
      currentVersion: "",
      error: String(error),
    };
  }
}

export async function installUpdate(): Promise<InstallResult> {
  try {
    await invoke("install_update");
    return { ok: true };
  } catch (error) {
    return { ok: false, error: String(error) };
  }
}

function relayCheck(
  info: UpdateInfo,
  send: (message: ClientMessage) => void,
  lastNotified: { current: string | null },
): void {
  if (!info || typeof info.available !== "boolean") return;
  if (info.available && info.version) {
    if (lastNotified.current === info.version) return;
    lastNotified.current = info.version;
    send({
      type: "update_available",
      version: info.version,
      notes: info.notes ?? undefined,
    });
  } else if (info.error) {
    send({ type: "update_status", detail: `Update check unavailable: ${info.error}` });
  }
}

/** Wire startup checks, voice requests, Tauri events and confirmed installs. */
export function useAutoUpdater(
  send: (message: ClientMessage) => void,
  lastMessage: ServerMessage | null,
): void {
  const lastNotified = useRef<string | null>(null);
  const handled = useRef<ServerMessage | null>(null);

  useEffect(() => {
    let cancelled = false;
    void checkForUpdates().then((info) => {
      if (!cancelled) relayCheck(info, send, lastNotified);
    });
    return () => {
      cancelled = true;
    };
  }, [send]);

  useEffect(() => {
    if (handled.current === lastMessage) return;
    handled.current = lastMessage;
    if (!lastMessage) return;
    if (lastMessage.type === "update_check_request") {
      void checkForUpdates().then((info) => relayCheck(info, send, lastNotified));
    } else if (lastMessage.type === "update_install") {
      void installUpdate();
    }
  }, [lastMessage, send]);

  // The Rust command also emits an event; listen so a notification is not
  // lost when the WebSocket connects after the startup check completed.
  useEffect(() => {
    let unlisten: (() => void) | undefined;
    let disposed = false;
    (async () => {
      try {
        const { listen } = await import("@tauri-apps/api/event");
        unlisten = await listen<UpdateInfo>("murmur://update-available", (event) => {
          if (!disposed) relayCheck(event.payload, send, lastNotified);
        });
      } catch {
        // Browser dev / no Tauri runtime: the startup check above still works.
      }
    })();
    return () => {
      disposed = true;
      unlisten?.();
    };
  }, [send]);
}
