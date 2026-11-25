import { useEffect, useRef, useState } from "react";
import { WS_URL, type ServerMessage } from "../lib/websocket";

interface Marker {
  x: number;
  y: number;
  kind: string;
}

/**
 * Click-through, always-on-top overlay. It only reacts to real cursor events
 * emitted by the backend immediately before an automated click or drag.
 */
export default function CursorOverlay() {
  const [marker, setMarker] = useState<Marker | null>(null);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => {
    let socket: WebSocket | undefined;
    let disposed = false;

    (async () => {
      try {
        const [{ getCurrentWindow }, { LogicalSize, LogicalPosition }] = await Promise.all([
          import("@tauri-apps/api/window"),
          import("@tauri-apps/api/dpi"),
        ]);
        const win = getCurrentWindow();
        await win.setSize(new LogicalSize(window.screen.width, window.screen.height));
        await win.setPosition(new LogicalPosition(0, 0));
      } catch {
        // Browser dev mode: the overlay still works inside the viewport.
      }

      if (disposed) return;
      socket = new WebSocket(WS_URL);
      socket.onmessage = (event: MessageEvent<string>) => {
        try {
          const msg = JSON.parse(event.data) as ServerMessage;
          if (msg.type !== "cursor") return;
          const scale = window.devicePixelRatio || 1;
          setMarker({ x: msg.x / scale, y: msg.y / scale, kind: msg.kind ?? "click" });
          window.clearTimeout(timer.current);
          timer.current = window.setTimeout(() => setMarker(null), 1400);
        } catch {
          // Ignore malformed frames; the overlay is purely informational.
        }
      };
    })();

    return () => {
      disposed = true;
      socket?.close();
      window.clearTimeout(timer.current);
    };
  }, []);

  if (!marker) return null;

  const color = marker.kind === "drag" ? "var(--color-red)" : "var(--color-blue)";
  return (
    <div
      aria-hidden="true"
      className="pointer-events-none fixed z-[9999] h-10 w-10 -translate-x-1/2 -translate-y-1/2"
      style={{ left: marker.x, top: marker.y, borderColor: color }}
    >
      <div
        className="absolute inset-0 animate-ping rounded-full border-2 opacity-70"
        style={{ borderColor: color }}
      />
      <div
        className="absolute inset-[6px] rounded-full border-2"
        style={{ borderColor: color, background: "color-mix(in srgb, var(--color-blue) 15%, transparent)" }}
      />
    </div>
  );
}
