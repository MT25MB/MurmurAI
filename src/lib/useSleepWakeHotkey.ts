import { useEffect } from "react";

/** Listen for the Tauri global sleep/wake hotkey and toggle listening mode. */
export function useSleepWakeHotkey(
  mode: "active" | "sleep",
  setMode: (m: "active" | "sleep") => void,
) {
  useEffect(() => {
    let unlisten: (() => void) | undefined;

    (async () => {
      try {
        const { listen } = await import("@tauri-apps/api/event");
        unlisten = await listen("toggle-sleep-wake", () => {
          setMode(mode === "active" ? "sleep" : "active");
        });
      } catch {
        // Not running inside Tauri (browser dev). Ignore; voice/UI still works.
      }
    })();

    return () => {
      unlisten?.();
    };
  }, [mode, setMode]);
}
