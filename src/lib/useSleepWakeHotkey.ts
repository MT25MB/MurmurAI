import { useEffect, useRef } from "react";

/** Listen for the Tauri global sleep/wake hotkey and toggle listening mode. */
export function useSleepWakeHotkey(
  mode: "active" | "sleep",
  setMode: (m: "active" | "sleep") => void,
) {
  // Keep the latest mode without re-subscribing: a pending listen() could
  // otherwise leave two listeners attached after a fast mode change.
  const modeRef = useRef(mode);
  modeRef.current = mode;
  const setModeRef = useRef(setMode);
  setModeRef.current = setMode;

  useEffect(() => {
    let unlisten: (() => void) | undefined;
    let disposed = false;

    (async () => {
      try {
        const { listen } = await import("@tauri-apps/api/event");
        const stop = await listen("toggle-sleep-wake", () => {
          setModeRef.current(modeRef.current === "active" ? "sleep" : "active");
        });
        if (disposed) stop();
        else unlisten = stop;
      } catch {
        // Not running inside Tauri (browser dev). Ignore; voice/UI still works.
      }
    })();

    return () => {
      disposed = true;
      unlisten?.();
    };
  }, []);
}
