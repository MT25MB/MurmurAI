/** Tauri launch-at-login bridge. The OS state is the source of truth. */

import { invoke } from "@tauri-apps/api/core";

export async function fetchAutostartEnabled(): Promise<boolean> {
  try {
    return await invoke<boolean>("autostart_enabled");
  } catch {
    return false;
  }
}

export async function setAutostartEnabled(enabled: boolean): Promise<boolean> {
  try {
    const result = await invoke<boolean | unknown>("set_autostart", { enabled });
    return typeof result === "boolean" ? result : enabled;
  } catch {
    return enabled;
  }
}
