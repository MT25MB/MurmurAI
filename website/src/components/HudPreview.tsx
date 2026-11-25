/**
 * The design anchor: an oscilloscope-style HUD that cycles through the real
 * agent states. Waveform is drawn on a canvas with requestAnimationFrame;
 * amplitude and color are driven by the active state. Reduced-motion users
 * get a static waveform.
 */

import { useEffect, useRef, useState } from "react";

type Phase = "LISTENING" | "THINKING" | "EXECUTING";

const phases: Record<Phase, { label: string; color: string; line: string; sub: string }> = {
  LISTENING: {
    label: "LISTENING",
    color: "var(--color-blue)",
    line: "“open blender and smooth the mesh”",
    sub: "capturing audio · 16 kHz mono",
  },
  THINKING: {
    label: "THINKING",
    color: "var(--color-muted)",
    line: "resolving intent → tool plan → qwen2.5:7b",
    sub: "local inference · 0 ms to cloud",
  },
  EXECUTING: {
    label: "EXECUTING",
    color: "var(--color-red)",
    line: "pyautogui.hotkey('shift','a')  ✓  done",
    sub: "set-of-marks grounding · verified",
  },
};

const order: Phase[] = ["LISTENING", "THINKING", "EXECUTING"];
const BARS = 40;

export default function HudPreview() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const phaseRef = useRef<Phase>("LISTENING");
  const [phase, setPhase] = useState<Phase>("LISTENING");

  useEffect(() => {
    phaseRef.current = phase;
  }, [phase]);

  // State machine: advance every 2.6s.
  useEffect(() => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) return;
    const id = window.setInterval(() => {
      setPhase((p) => order[(order.indexOf(p) + 1) % order.length]);
    }, 2600);
    return () => window.clearInterval(id);
  }, []);

  // Waveform renderer.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    let raf = 0;
    let t = 0;
    const style = getComputedStyle(document.documentElement);

    const draw = () => {
      const dpr = window.devicePixelRatio || 1;
      const w = canvas.clientWidth;
      const h = canvas.clientHeight;
      if (canvas.width !== Math.floor(w * dpr) || canvas.height !== Math.floor(h * dpr)) {
        canvas.width = Math.floor(w * dpr);
        canvas.height = Math.floor(h * dpr);
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);

      const p = phaseRef.current;
      const accent = style.getPropertyValue(
        p === "LISTENING" ? "--color-blue" : p === "EXECUTING" ? "--color-red" : "--color-muted",
      ).trim() || "#5598F9";
      const energy = p === "LISTENING" ? 1 : p === "EXECUTING" ? 0.72 : 0.34;

      const gap = 3;
      const bw = (w - gap * (BARS - 1)) / BARS;
      for (let i = 0; i < BARS; i++) {
        const x = i * (bw + gap);
        // Deterministic pseudo-wave: layered sines + a moving envelope.
        const wave =
          Math.sin(i * 0.55 + t * 2.1) * 0.5 +
          Math.sin(i * 0.21 - t * 1.3) * 0.32 +
          Math.sin(i * 1.1 + t * 3.4) * 0.18;
        const envelope = 0.45 + 0.55 * Math.sin((i / BARS) * Math.PI);
        const amp = Math.min(1, Math.abs(wave) * envelope * energy + 0.05);
        const bh = Math.max(3, amp * (h - 6));
        ctx.fillStyle = accent;
        ctx.globalAlpha = 0.35 + amp * 0.65;
        ctx.fillRect(x, (h - bh) / 2, bw, bh);
      }
      ctx.globalAlpha = 1;

      if (!reduce) {
        t += 0.03;
        raf = requestAnimationFrame(draw);
      }
    };

    draw();
    return () => cancelAnimationFrame(raf);
  }, []);

  const meta = phases[phase];

  return (
    <div className="panel scanlines relative w-full max-w-xl overflow-hidden shadow-2xl shadow-black/60">
      {/* top chrome */}
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="h-2 w-2 rounded-full" style={{ background: meta.color }} />
          <span className="mono-label !text-ink">murmur / agent</span>
        </div>
        <span className="mono-label">v1.2.19 · local</span>
      </div>

      {/* waveform */}
      <div className="relative px-4 pt-6">
        <div className="absolute inset-0 grid-field opacity-30" aria-hidden="true" />
        <canvas
          ref={canvasRef}
          className="relative h-28 w-full"
          role="img"
          aria-label={`Audio waveform for the ${phase} state`}
        />
      </div>

      {/* state readout */}
      <div className="relative border-t border-border px-4 py-4">
        <div className="flex items-center justify-between gap-3">
          <span
            className="mono-label shrink-0 !text-xs !font-bold"
            style={{ color: meta.color }}
            aria-live="polite"
          >
            {meta.label}
          </span>
          <span className="mono-label min-w-0 truncate">{meta.sub}</span>
        </div>
        <p className="mt-2 truncate font-mono text-sm text-ink/90">
          <span className="text-blue">›</span> {meta.line}
          <span className="caret text-blue">_</span>
        </p>
      </div>

      {/* state track */}
      <div className="flex gap-1 border-t border-border p-3">
        {order.map((p) => (
          <div
            key={p}
            className="h-1 flex-1 rounded-full transition-colors duration-500"
            style={{ background: p === phase ? phases[p].color : "var(--color-border)" }}
            aria-hidden="true"
          />
        ))}
      </div>
    </div>
  );
}
