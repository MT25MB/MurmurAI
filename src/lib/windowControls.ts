/** Native window helpers for the borderless HUD (no-ops in a plain browser). */

export async function setHudSize(width: number, height: number): Promise<void> {
  try {
    const [{ getCurrentWindow }, { LogicalSize }] = await Promise.all([
      import("@tauri-apps/api/window"),
      import("@tauri-apps/api/dpi"),
    ]);
    await getCurrentWindow().setSize(new LogicalSize(width, height));
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
