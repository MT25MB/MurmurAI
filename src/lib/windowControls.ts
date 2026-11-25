/** Native window helpers for the borderless HUD (no-ops in a plain browser). */

export async function setHudSize(
  width: number,
  height: number,
  resizable?: boolean,
): Promise<void> {
  try {
    const [{ getCurrentWindow }, { LogicalSize, LogicalPosition }] = await Promise.all([
      import("@tauri-apps/api/window"),
      import("@tauri-apps/api/dpi"),
    ]);
    const win = getCurrentWindow();
    // Keep the expanded panel inside the usable screen area. `center()` uses
    // the monitor size, not the work area, and can leave the bottom cropped.
    const dpr = globalThis.devicePixelRatio || 1;
    let availWidth = globalThis.screen?.availWidth || globalThis.screen?.width || width;
    let availHeight = globalThis.screen?.availHeight || globalThis.screen?.height || height;
    // Some WebView2 builds report physical pixels here; Tauri LogicalSize/Position
    // use CSS pixels, so convert when the numbers look physical.
    if (availWidth > 2000 && dpr >= 1.5) {
      availWidth /= dpr;
      availHeight /= dpr;
    }
    const targetHeight = resizable
      ? Math.min(height, Math.max(240, availHeight - 24))
      : height;

    // Windows ignores setSize on a non-resizable window. The pill is locked at
    // 440x120, so every resize must briefly re-enable resizing.
    await win.setResizable(true);
    await win.setSize(new LogicalSize(width, targetHeight));
    if (!resizable) await win.setResizable(false);
    if (resizable) {
      const x = Math.max(0, Math.floor((availWidth - width) / 2));
      const y = Math.max(0, Math.floor((availHeight - targetHeight) / 2));
      await win.setPosition(new LogicalPosition(x, y));
    }
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
