import { useEffect, useRef, useState } from "react";
import type { ServerMessage } from "../lib/websocket";

interface TranscriptStreamProps {
  lastMessage: ServerMessage | null;
  maxTurns?: number;
}

interface Turn {
  id: number;
  role: "assistant" | "system";
  text: string;
}

/**
 * Screen-reader and refreshable-Braille friendly transcript log.
 *
 * Every Murmur response/action summary is emitted as a plain-text WS message.
 * There is no markdown, decoration or visual clutter here: the region is
 * visually hidden but exposed as a polite live log so assistive tech can read
 * each turn in order.
 */
export default function TranscriptStream({ lastMessage, maxTurns = 50 }: TranscriptStreamProps) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const nextId = useRef(1);

  useEffect(() => {
    if (!lastMessage || lastMessage.type !== "transcript") return;
    const text = (lastMessage.text ?? "").replace(/\s+/g, " ").trim();
    if (!text) return;
    setTurns((previous) => {
      const updated = [...previous, { id: nextId.current++, role: lastMessage.role ?? "assistant", text }];
      return updated.slice(-Math.max(1, maxTurns));
    });
  }, [lastMessage, maxTurns]);

  return (
    <div
      role="log"
      aria-label="Murmur AI transcript"
      aria-live="polite"
      aria-relevant="additions"
      aria-atomic="false"
      className="sr-only"
    >
      {turns.map((turn) => (
        <p key={turn.id} data-role={turn.role}>
          {turn.role === "system" ? `Status: ${turn.text}` : turn.text}
        </p>
      ))}
    </div>
  );
}
