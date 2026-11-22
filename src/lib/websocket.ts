/**
 * Typed WebSocket control-plane client for the Murmur AI backend sidecar.
 * Protocol models mirror `backend/agent/state.py`.
 */

export const WS_URL = "ws://127.0.0.1:8765/ws";

export type ConnectionStatus = "connecting" | "connected" | "disconnected" | "error";

/** Messages the HUD may send to the backend. */
export type ClientMessage =
  | { type: "ping" }
  | { type: "state" }
  | { type: "text_input"; text: string }
  | { type: "audio_chunk"; data: string }
  | { type: "confirm"; request_id: string; approved: boolean }
  | { type: "guidance_response"; request_id: string; text: string }
  | { type: "abort_automation"; text?: string }
  | { type: "set_listening_mode"; mode: "active" | "sleep" }
  | { type: "update_available"; version?: string; notes?: string }
  | { type: "update_confirm"; request_id: string; approved: boolean }
  | { type: "update_status"; detail?: string }
  | { type: "permission_status"; permissions?: unknown }
  | { type: "be_quiet" };

/** Messages the backend may send to the HUD. */
export type ServerMessage =
  | { type: "pong"; ts: number }
  | { type: "state"; status: string; uptime_s: number; amplitude?: number }
  | { type: "text_output"; text: string }
  | { type: "audio_ack"; chunks: number }
  | {
      type: "confirmation_required";
      request_id: string;
      description: string;
      command: string;
    }
  | { type: "guidance_required"; request_id: string; text: string }
  | { type: "automation_stopped"; text: string }
  | { type: "progress"; text: string; percent?: number }
  | { type: "error"; detail: string }
  | { type: "info"; text: string }
  | {
      type: "update_available";
      request_id: string;
      version: string;
      notes: string;
      text: string;
    }
  | { type: "update_install"; request_id: string; version: string; text: string }
  | { type: "update_check_request"; text: string }
  | { type: "transcript"; text: string; role?: "assistant" | "system" };

export interface MurmurSocket {
  status: ConnectionStatus;
  lastMessage: ServerMessage | null;
  send: (message: ClientMessage) => void;
}

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Connect to the local sidecar with bounded exponential-backoff reconnection.
 * All local state is ephemeral; nothing is persisted or transmitted off-machine.
 */
export function useMurmurSocket(url: string = WS_URL): MurmurSocket {
  const [status, setStatus] = useState<ConnectionStatus>("connecting");
  const [lastMessage, setLastMessage] = useState<ServerMessage | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const attemptsRef = useRef(0);

  useEffect(() => {
    let disposed = false;

    const connect = () => {
      if (disposed) return;
      setStatus("connecting");
      const ws = new WebSocket(url);
      socketRef.current = ws;

      ws.onopen = () => {
        attemptsRef.current = 0;
        setStatus("connected");
        ws.send(JSON.stringify({ type: "ping" } satisfies ClientMessage));
      };

      ws.onmessage = (event: MessageEvent<string>) => {
        try {
          const parsed = JSON.parse(event.data) as ServerMessage;
          setLastMessage(parsed);
        } catch {
          setLastMessage({ type: "error", detail: "Malformed message from backend" });
        }
      };

      ws.onerror = () => setStatus("error");

      ws.onclose = () => {
        if (disposed) return;
        setStatus("disconnected");
        const delay = Math.min(1000 * 2 ** attemptsRef.current, 8000);
        attemptsRef.current += 1;
        reconnectRef.current = setTimeout(connect, delay);
      };
    };

    connect();

    return () => {
      disposed = true;
      if (reconnectRef.current) clearTimeout(reconnectRef.current);
      socketRef.current?.close();
      socketRef.current = null;
    };
  }, [url]);

  const send = useCallback((message: ClientMessage) => {
    const ws = socketRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(message));
    }
  }, []);

  return { status, lastMessage, send };
}
