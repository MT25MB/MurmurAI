/** Native window helpers for the borderless HUD (no-ops in a plain browser). */

const EDGE_MARGIN = 16;

/**
 * Work area in logical pixels. Tauri reports physical pixels plus a scale
 * factor; using `screen.availWidth` from WebView2 was unreliable on Windows
 * DPI scaling and put the expanded panel partly above the screen.
 */
async function workArea(): Promise<{ x: number; y: number; width: number; height: number } | null> {
  try {
    const { currentMonitor } = await import("@tauri-apps/api/window");
    const monitor = await currentMonitor();
    if (!monitor) return null;
    const position = monitor.workArea.position.toLogical(monitor.scaleFactor);
    const size = monitor.workArea.size.toLogical(monitor.scaleFactor);
    if (size.width <= 0 || size.height <= 0) return null;
    return { x: position.x, y: position.y, width: size.width, height: size.height };
  } catch {
    return null;
  }
}

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
    const area = await workArea();
    const availWidth = area?.width ?? width;
    const availHeight = area?.height ?? height;

    // Never let the panel exceed the usable area, including the taskbar.
    // Without a monitor (browser dev mode) keep the requested size as-is.
    const targetWidth = area
      ? Math.max(240, Math.min(width, availWidth - EDGE_MARGIN * 2))
      : width;
    const targetHeight = area && resizable
      ? Math.max(240, Math.min(height, availHeight - EDGE_MARGIN * 2))
      : height;

    // Windows ignores setSize on a non-resizable window. Every resize must
    // briefly re-enable resizing.
    await win.setResizable(true);
    await win.setSize(new LogicalSize(targetWidth, targetHeight));
    if (!resizable) await win.setResizable(false);

    if (area) {
      // Both compact and expanded states are explicitly placed inside the work
      // area so a stale position from the previous state cannot crop the top.
      const x = area.x + Math.max(EDGE_MARGIN, Math.floor((area.width - targetWidth) / 2));
      const y = resizable
        ? area.y + Math.max(EDGE_MARGIN, Math.floor((area.height - targetHeight) / 2))
        : area.y + Math.max(EDGE_MARGIN, area.height - targetHeight - 48);
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
