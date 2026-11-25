/** Native window helpers for the borderless HUD (no-ops in a plain browser). */

export async function setHudSize(
  width: number,
  height: number,
  resizable?: boolean,
): Promise<void> {
  try {
    const [{ getCurrentWindow }, { LogicalSize }] = await Promise.all([
      import("@tauri-apps/api/window"),
      import("@tauri-apps/api/dpi"),
    ]);
    const window = getCurrentWindow();
    // Windows ignores setSize on a non-resizable window. The pill is locked at
    // 440x120, so every resize must briefly re-enable resizing.
    await window.setResizable(true);
    await window.setSize(new LogicalSize(width, height));
    if (!resizable) await window.setResizable(false);
    // Growing from the pill's top-left can push the panel off the bottom of the
    // screen; keep the expanded window fully visible.
    if (resizable) await window.center();
  } catch {
    // Browser dev mode: no native window to resize.
  }
}

export async function minimizeHud(): Promise<void> {
  try {
    const { getCurrentWindow } = await import("@tauri-apps/api/window");
    await getCurrentWindow().minimize();
  } catch {
    // Browser dev mode.
  }
}

export async function closeHud(): Promise<void> {
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    // Closing only the main window would leave the cursor overlay alive and
    // the backend already dead; ask Rust to stop the sidecar and exit cleanly.
    await invoke("quit_app");
  } catch {
    // Browser dev mode.
  }
}
