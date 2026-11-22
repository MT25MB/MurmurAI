/** OS permission diagnostics from the Tauri shell (never a substitute for TCC). */

export interface PermissionReport {
  microphone: "granted" | "denied" | "unknown" | "notNeeded";
  screen: "granted" | "denied" | "unknown" | "notNeeded";
  accessibility: "granted" | "denied" | "unknown" | "notNeeded";
  recovery: string[];
  summary: string;
}

export async function checkOsPermissions(): Promise<PermissionReport | null> {
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    return await invoke<PermissionReport>("check_os_permissions");
  } catch {
    return null;
  }
}
