/**
 * Audio-reactive waveform visualizer.
 * Driven by the amplitude stream (0..1) coming over the WebSocket.
 * Uses requestAnimationFrame for smooth 60fps motion; no layout thrashing.
 */

import { useCallback, useEffect, useRef, useState } from "react";

const BAR_COUNT = 24;
const BAR_WIDTH = 4;
const BAR_GAP = 6;
const SMOOTHING = 0.35; // lower = smoother/sliver, higher = snappier

export function Waveform({
  amplitude,
  active,
}: {
  amplitude: number;
  active: boolean;
}) {
  const barsRef = useRef<Array<number>>(Array(BAR_COUNT).fill(0));
  const rafRef = useRef<number | null>(null);
  const [values, setValues] = useState<Array<number>>(
    Array(BAR_COUNT).fill(0.1)
  );

  const tick = useCallback(() => {
    const target = active ? Math.max(amplitude, 0.05) : 0.05;
    const next = barsRef.current.map((v) => {
      // Each bar drifts toward the target with a bit of per-bar random jitter
      // so the waveform looks alive rather than a flat rectangle.
      const jitter = active ? 0.15 * (Math.random() - 0.5) : 0;
      const smoothed = v + (target + jitter - v) * SMOOTHING;
      return Math.max(0.02, Math.min(1, smoothed));
    });
    barsRef.current = next;
    setValues([...next]);
    rafRef.current = requestAnimationFrame(tick);
  }, [amplitude, active]);

  useEffect(() => {
    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
    };
  }, [tick]);

  const totalWidth = BAR_COUNT * BAR_WIDTH + (BAR_COUNT - 1) * BAR_GAP;

  return (
    <svg
      className="app-region-no-drag"
      width={totalWidth}
      height={32}
      viewBox={`0 0 ${totalWidth} 32`}
      role="meter"
      aria-label="Audio level"
    >
      {values.map((v, i) => {
        const height = Math.max(2, v * 22);
        const cy = 16;
        return (
          <rect
            key={i}
            x={i * (BAR_WIDTH + BAR_GAP)}
            y={cy - height / 2}
            width={BAR_WIDTH}
            height={height}
            rx={2}
            fill={active ? "#5598f9" : "#2d333e"}
            opacity={active ? 0.9 : 0.45}
          />
        );
      })}
    </svg>
  );
}
