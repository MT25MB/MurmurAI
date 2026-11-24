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
    // 400x84, so expanding must re-enable resizing before changing the size.
    if (resizable !== undefined) await window.setResizable(resizable);
    await window.setSize(new LogicalSize(width, height));
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
    const { getCurrentWindow } = await import("@tauri-apps/api/window");
    await getCurrentWindow().close();
  } catch {
    // Browser dev mode.
  }
}
