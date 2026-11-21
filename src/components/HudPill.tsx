import { useCallback, useEffect, useRef, useState } from "react";
import { useMurmurSocket } from "../lib/websocket";
import { Waveform } from "./Waveform";
import logoUrl from "../assets/logo-blue.png";

type Phase = "IDLE" | "LISTENING" | "THINKING" | "SPEAKING" | "CONFIRMATION_REQUIRED";

/** State -> (label, token color). Blue = active sense, red = action/alert. */
const stateStyle: Record<Phase, { label: string; color: string; fill: string }> = {
  IDLE: { label: "Listening", color: "var(--color-blue)", fill: "bg-blue-fill" },
  LISTENING: { label: "Listening…", color: "var(--color-blue)", fill: "bg-blue-fill" },
  THINKING: { label: "Thinking", color: "var(--color-muted)", fill: "bg-surface-2" },
  SPEAKING: { label: "Speaking", color: "var(--color-red)", fill: "bg-red-fill" },
  CONFIRMATION_REQUIRED: { label: "Confirm action", color: "var(--color-red)", fill: "bg-red-fill" },
};

export default function HudPill() {
  const { lastMessage, send } = useMurmurSocket();
  const [status, setStatus] = useState<Phase>("IDLE");
  const [transcript, setTranscript] = useState("");
  const [muted, setMuted] = useState(false);
  const [progress, setProgress] = useState<{ text: string; percent?: number } | null>(null);
  const [confirmation, setConfirmation] = useState<{
    request_id: string;
    description: string;
    command: string;
  } | null>(null);
  const amplitudeRef = useRef(0);

  useEffect(() => {
    if (!lastMessage) return;
    if (lastMessage.type === "state") {
      setStatus((lastMessage.status as Phase) || "IDLE");
      if (typeof lastMessage.amplitude === "number") amplitudeRef.current = lastMessage.amplitude;
    }
    if (lastMessage.type === "text_output") {
      setTranscript(lastMessage.text);
      setProgress(null);
    }
    if (lastMessage.type === "confirmation_required") {
      setConfirmation({
        request_id: lastMessage.request_id,
        description: lastMessage.description,
        command: lastMessage.command,
      });
      setStatus("CONFIRMATION_REQUIRED");
    }
    if (lastMessage.type === "progress") {
      setProgress({ text: lastMessage.text, percent: lastMessage.percent });
      setStatus("THINKING");
    }
  }, [lastMessage]);

  const answer = useCallback(
    (approved: boolean) => {
      if (!confirmation) return;
      send({ type: "confirm", request_id: confirmation.request_id, approved });
      setConfirmation(null);
      setStatus("IDLE");
    },
    [confirmation, send],
  );

  const meta = stateStyle[status] || stateStyle.IDLE;

  return (
    <section
      className="fixed bottom-[8vh] left-1/2 z-[9999] w-[360px] -translate-x-1/2 select-none rounded-[1.75rem] border border-border bg-obsidian/92 px-4 py-3 shadow-2xl shadow-black/70 ring-1 ring-white/5 backdrop-blur-xl"
      aria-label="Murmur AI voice assistant"
    >
      <div className="flex items-center gap-2.5">
        <img
          src={logoUrl}
          alt=""
          aria-hidden="true"
          className="h-7 w-7 shrink-0 object-contain"
        />
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline gap-2">
            <p className="text-xs font-semibold tracking-tight text-ink">MURMUR<span className="text-blue">/AI</span></p>
            <p className="mono-label !text-[10px]" style={{ color: meta.color }}>{meta.label}</p>
          </div>
          {transcript && (
            <p className="truncate text-[11px] leading-snug text-muted" title={transcript}>
              {transcript}
            </p>
          )}
        </div>
        <button
          type="button"
          className="app-region-no-drag flex h-7 w-7 items-center justify-center rounded-lg border border-border bg-surface text-ink transition-colors hover:border-blue focus:outline-none"
          onClick={() => setMuted((m) => !m)}
          aria-pressed={muted}
          aria-label={muted ? "Unmute microphone" : "Mute microphone"}
          title={muted ? "Unmute" : "Mute"}
        >
          <svg viewBox="0 0 20 20" className="h-3.5 w-3.5 fill-current" aria-hidden="true">
            {muted ? (
              <path d="M3 3l14 14-1.4 1.4-2.2-2.2A7 7 0 0 1 10 17a7 7 0 0 1-7-7 6.9 6.9 0 0 1 1.2-3.9L1.6 2.4 3 1l16 16-1.4 1.4M5 5.1A5 5 0 0 0 3 9a5 5 0 0 0 6 4.9V10l-4-4.9ZM13 5V3a3 3 0 0 0-6 0v2.2l6 6V5Z" />
            ) : (
              <path d="M10 15a4 4 0 0 0 4-4V6a4 4 0 1 0-8 0v5a4 4 0 0 0 4 4ZM3 10a7 7 0 0 0 6 6.9V19h2v-2.1A7 7 0 0 0 17 10h-2a5 5 0 0 1-10 0H3Z" />
            )}
          </svg>
        </button>
      </div>

      <div className="my-2.5 flex w-full items-end justify-center">
        <Waveform amplitude={amplitudeRef.current} active={status === "LISTENING" || status === "SPEAKING"} />
      </div>

      {progress && (
        <div className="app-region-no-drag mt-2 rounded-lg border border-blue/30 bg-blue-deep/20 p-2.5">
          <p className="truncate text-[11px] text-blue" title={progress.text}>{progress.text}</p>
          {typeof progress.percent === "number" && (
            <div className="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-border">
              <div className="h-full rounded-full bg-blue-fill transition-all duration-300" style={{ width: `${progress.percent}%` }} />
            </div>
          )}
        </div>
      )}

      {confirmation && (
        <div className="app-region-no-drag mt-2 rounded-lg border border-red/35 bg-red-deep/25 p-2.5">
          <p className="mono-label !text-red">Approval needed</p>
          <p className="mt-0.5 break-words text-[11px] leading-snug text-ink">{confirmation.description}</p>
          <code className="mt-1 block break-all rounded bg-obsidian p-2 font-mono text-[10px] text-muted">
            {confirmation.command}
          </code>
          <div className="mt-2 flex gap-1.5">
            <button
              type="button"
              onClick={() => answer(true)}
              className="flex-1 rounded-md bg-blue-fill px-2 py-1.5 text-[10px] font-bold text-white hover:brightness-110"
            >
              Yes, run it
            </button>
            <button
              type="button"
              onClick={() => answer(false)}
              className="flex-1 rounded-md border border-border bg-surface px-2 py-1.5 text-[10px] font-bold text-ink hover:border-red"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
