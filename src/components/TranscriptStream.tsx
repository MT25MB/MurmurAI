import { useEffect, useRef, useState } from "react";
import type { ServerMessage } from "../lib/websocket";

interface TranscriptStreamProps {
  lastMessage: ServerMessage | null;
  maxTurns?: number;
  /** Show the log visually in the expanded HUD; otherwise screen-reader only. */
  visible?: boolean;
  /** Shared history supplied by HudPill so both views show the same turns. */
  turns?: Turn[];
}

export interface Turn {
  id: number;
  role: "assistant" | "system";
  text: string;
}

/**
 * Owns the transcript history. HudPill calls this once and passes `turns` to
 * both the compact and expanded views, so collapsing/restoring the window
 * never loses the conversation.
 */
export function useTranscriptTurns(
  lastMessage: ServerMessage | null,
  maxTurns = 50,
): Turn[] {
  const [turns, setTurns] = useState<Turn[]>([]);
  const nextId = useRef(1);

  useEffect(() => {
    if (!lastMessage || lastMessage.type !== "transcript") return;
    const text = (lastMessage.text ?? "").replace(/\s+/g, " ").trim();
    if (!text) return;
    setTurns((previous) => {
      const updated = [...previous, {
        id: nextId.current++,
        role: lastMessage.role ?? "assistant",
        text,
      }];
      return updated.slice(-Math.max(1, maxTurns));
    });
  }, [lastMessage, maxTurns]);

  return turns;
}

/**
 * Screen-reader and refreshable-Braille friendly transcript log.
 *
 * Every Murmur response/action summary is emitted as a plain-text WS message.
 * There is no markdown, decoration or visual clutter here: the region is
 * visually hidden but exposed as a polite live log so assistive tech can read
 * each turn in order.
 */
export default function TranscriptStream({
  lastMessage,
  maxTurns = 50,
  visible = false,
  turns: controlledTurns,
}: TranscriptStreamProps) {
  const internalTurns = useTranscriptTurns(lastMessage, maxTurns);
  const turns = controlledTurns ?? internalTurns;

  return (
    <div
      role="log"
      aria-label="Murmur AI transcript"
      aria-live="polite"
      aria-relevant="additions"
      aria-atomic="false"
      className={
        visible
          ? "space-y-2 rounded-lg border border-border bg-obsidian/80 p-3 text-xs leading-relaxed text-ink"
          : "sr-only"
      }
    >
      {turns.length === 0 && visible ? (
        <p className="text-muted">Nothing said yet. Speak, or type a command below.</p>
      ) : null}
      {turns.map((turn) => (
        <p key={turn.id} data-role={turn.role} className={turn.role === "system" ? "text-muted" : "text-ink"}>
          {turn.role === "system" ? `Status: ${turn.text}` : turn.text}
        </p>
      ))}
    </div>
  );
}
