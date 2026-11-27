use tauri::menu::{Menu, MenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{Emitter, Manager, Position, WebviewWindow};
use tauri_plugin_shell::process::CommandChild;
use tauri_plugin_shell::ShellExt;
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};
use tauri_plugin_autostart::ManagerExt as AutostartManagerExt;
use tauri_plugin_updater::UpdaterExt;
use serde::Serialize;

mod focus;
mod permissions;

/// Turn a command failure into a short, speakable message for the HUD.
/// A blank or whitespace-only error still yields a useful announcement.
fn command_error_message(command: &str, error: &str) -> String {
    let detail = error.trim();
    if detail.is_empty() {
        format!("{command} is unavailable.")
    } else {
        format!("{command} failed: {detail}")
    }
}

/// Result of a local update check. Serde names are camelCase for the HUD.
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct UpdateInfo {
    pub available: bool,
    pub version: Option<String>,
    pub notes: Option<String>,
    pub current_version: String,
    /// Present when GitHub is unreachable or the manifest cannot be verified.
    pub error: Option<String>,
}

/// Check GitHub for a newer release. Never fails the command on network errors:
/// offline is a normal state and is reported through `error` for a graceful HUD.
#[tauri::command]
async fn check_for_updates(app: tauri::AppHandle) -> Result<UpdateInfo, String> {
    let current = app.package_info().version.to_string();
    let unavailable = |error: Option<String>| UpdateInfo {
        available: false,
        version: None,
        notes: None,
        current_version: current.clone(),
        error,
    };

    let updater = match app.updater() {
        Ok(updater) => updater,
        Err(error) => {
            return Ok(unavailable(Some(command_error_message(
                "Update check",
                &error.to_string(),
            ))))
        }
    };

    match updater.check().await {
        Ok(Some(update)) => {
            let info = UpdateInfo {
                available: true,
                version: Some(update.version.clone()),
                notes: update.body.clone(),
                current_version: current,
                error: None,
            };
            let _ = app.emit("murmur://update-available", &info);
            Ok(info)
        }
        Ok(None) => Ok(unavailable(None)),
        Err(error) => Ok(unavailable(Some(command_error_message(
            "Update check",
            &error.to_string(),
        )))),
    }
}

/// Download progress for the Settings update button.
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct UpdateProgress {
    pub received: u64,
    pub total: Option<u64>,
}

/// Download and install the pending update, then restart the app.
#[tauri::command]
async fn install_update(app: tauri::AppHandle) -> Result<(), String> {
    let _ = app.emit("murmur://update-status", "Downloading the update…");
    let updater = app
        .updater()
        .map_err(|error| command_error_message("Update install", &error.to_string()))?;
    let update = updater
        .check()
        .await
        .map_err(|error| command_error_message("Update check", &error.to_string()))?
        .ok_or_else(|| "No update is available".to_string())?;

    let progress_app = app.clone();
    let mut received = 0u64;
    update
        .download_and_install(
            |chunk, total| {
                received = received.saturating_add(chunk as u64);
                let _ = progress_app.emit(
                    "murmur://update-progress",
                    UpdateProgress { received, total },
                );
            },
            || {},
        )
        .await
        .map_err(|error| command_error_message("Update install", &error.to_string()))?;
    let _ = app.emit("murmur://update-status", "Update installed. Restarting…");
    // Stop the sidecar cleanly so PyInstaller removes its extraction dir before
    // the installer replaces the app files. restart() diverges: it is the tail.
    kill_backend();
    app.restart()
}

/// Read the OS launch-at-login state (source of truth is the OS, not config.json).
#[tauri::command]
async fn autostart_enabled(app: tauri::AppHandle) -> Result<bool, String> {
    app.autolaunch()
        .is_enabled()
        .map_err(|error| command_error_message("Autostart check", &error.to_string()))
}

/// Enable or disable launch-at-login. Idempotent on Windows.
#[tauri::command]
async fn set_autostart(app: tauri::AppHandle, enabled: bool) -> Result<bool, String> {
    let manager = app.autolaunch();
    let result = if enabled {
        manager.enable()
    } else {
        manager.disable()
    };
    result.map_err(|error| command_error_message("Autostart change", &error.to_string()))?;
    let _ = app.emit("murmur://autostart-changed", enabled);
    app.autolaunch()
        .is_enabled()
        .map_err(|error| command_error_message("Autostart check", &error.to_string()))
}

/// Global handle to the Python backend child process so we can kill it on exit.
static BACKEND_CHILD: once_cell::sync::Lazy<std::sync::Mutex<Option<CommandChild>>> =
    once_cell::sync::Lazy::new(|| std::sync::Mutex::new(None));

/// Hide or show the floating HUD pill.
fn toggle_window(window: &WebviewWindow) {
    match window.is_visible() {
        Ok(true) => {
            let _ = window.hide();
        }
        Ok(false) => {
            let _ = window.show();
            let _ = window.set_focus();
            focus::announce_focus(window.app_handle(), "Murmur AI");
        }
        Err(err) => eprintln!("[Murmur AI] failed to read window visibility: {err}"),
    }
}

fn backend_is_listening() -> bool {
    std::net::TcpStream::connect_timeout(
        &"127.0.0.1:8765".parse().unwrap(),
        std::time::Duration::from_millis(200),
    )
    .is_ok()
}

/// Ask the sidecar to stop through its local HTTP endpoint. A clean uvicorn
/// exit lets the PyInstaller onefile bootloader delete its _MEI* extraction
/// directory; a hard kill leaves ~744 MB behind on every quit.
fn request_backend_shutdown() {
    if !backend_is_listening() {
        return;
    }
    use std::io::{Read, Write};
    if let Ok(mut stream) = std::net::TcpStream::connect_timeout(
        &"127.0.0.1:8765".parse().unwrap(),
        std::time::Duration::from_millis(300),
    ) {
        let _ = stream.set_read_timeout(Some(std::time::Duration::from_millis(400)));
        let request = b"POST /shutdown HTTP/1.1\r\nHost: 127.0.0.1:8765\r\nConnection: close\r\nContent-Length: 0\r\n\r\n";
        let _ = stream.write_all(request);
        let _ = stream.flush();
        let mut reply = [0u8; 128];
        let _ = stream.read(&mut reply);
    }
    // Bound the wait: uvicorn normally closes the listener in well under a second.
    for _ in 0..15 {
        if !backend_is_listening() {
            return;
        }
        std::thread::sleep(std::time::Duration::from_millis(100));
    }
    eprintln!("[Murmur AI] sidecar did not stop gracefully within 1.5s");
}

/// Remove orphaned onefile extraction dirs from earlier hard kills. Only dirs
/// carrying our bundled marker and older than ten minutes are touched, so
/// unrelated applications' _MEI* dirs are left alone.
fn cleanup_stale_sidecar_temp() {
    let temp = std::env::temp_dir();
    let entries = match std::fs::read_dir(temp) {
        Ok(entries) => entries,
        Err(err) => {
            eprintln!("[Murmur AI] cannot read temp dir for sidecar cleanup: {err}");
            return;
        }
    };
    let cutoff = std::time::SystemTime::now().checked_sub(std::time::Duration::from_secs(600));
    for entry in entries.flatten() {
        let path = entry.path();
        let name = entry.file_name().to_string_lossy().into_owned();
        if !name.starts_with("_MEI") || !path.join("sidecar.marker").is_file() {
            continue;
        }
        if let (Some(cutoff), Ok(metadata)) = (cutoff, std::fs::metadata(&path)) {
            if let Ok(modified) = metadata.modified() {
                if modified > cutoff {
                    continue;
                }
            }
        }
        match std::fs::remove_dir_all(&path) {
            Ok(()) => eprintln!("[Murmur AI] removed stale sidecar extraction dir {name}"),
            Err(err) => eprintln!("[Murmur AI] could not remove {name}: {err}"),
        }
    }
}

/// A previous app version can leave its sidecar holding port 8765 after an
/// in-place update. Stop it so the freshly installed code actually serves.
fn stop_stale_sidecar() {
    if std::net::TcpStream::connect("127.0.0.1:8765").is_err() {
        return;
    }
    eprintln!("[Murmur AI] stale backend on 127.0.0.1:8765; stopping it");
    request_backend_shutdown();
    if !backend_is_listening() {
        return;
    }
    // PyInstaller names the sidecar with the Tauri target triple, not the
    // bare "murmur-backend.exe". Match only that sidecar family.
    #[cfg(windows)]
    let _ = std::process::Command::new("taskkill")
        .args(["/F", "/IM", "murmur-backend-*.exe"])
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .status();
    #[cfg(not(windows))]
    let _ = std::process::Command::new("pkill")
        .args(["-f", "murmur-backend-[a-z0-9_]+-unknown-linux-gnu"])
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .status();
    let _ = std::process::Command::new("pkill")
        .args(["-f", "murmur-backend-[a-z0-9_]+-apple-darwin"])
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .status();
    std::thread::sleep(std::time::Duration::from_millis(600));
}

/// HUD Quit: stop the sidecar and exit the whole app, including the overlay.
#[tauri::command]
async fn quit_app(app: tauri::AppHandle) {
    kill_backend();
    app.exit(0);
}

/// Spawn the backend sidecar via tauri-plugin-shell.
///
/// Production: launch the bundled PyInstaller binary (externalBin).
/// Development: fall back to `python main.py` from the backend source folder.
fn spawn_backend(app: &tauri::AppHandle) {
    // Already running?
    if let Ok(guard) = BACKEND_CHILD.lock() {
        if guard.is_some() {
            return;
        }
    }

    use tauri_plugin_shell::process::Command;

    // Build the command: in debug/dev builds always use the Python source
    // entrypoint; in release builds use the bundled PyInstaller sidecar.
    let command: Command = if !cfg!(debug_assertions) {
        match app.shell().sidecar("murmur-backend") {
            Ok(sidecar) => {
                eprintln!("[Murmur AI] using bundled backend sidecar");
                sidecar
            }
            Err(err) => {
                // Sidecar missing at runtime, so surface a clear error.
                eprintln!("[Murmur AI] bundled backend sidecar not found: {err}");
                return;
            }
        }
    } else {
            // Dev fallback: locate backend/main.py.
            let mut candidates: Vec<std::path::PathBuf> = Vec::new();
            if let Ok(exe) = std::env::current_exe() {
                if let Some(parent) = exe.parent() {
                    candidates.push(parent.join("..").join("backend"));
                    candidates.push(parent.join("backend"));
                    candidates.push(parent.join("..").join("..").join("backend"));
                }
            }
            candidates.push(std::path::PathBuf::from("../backend"));
            candidates.push(std::path::PathBuf::from("backend"));
            let backend_dir = candidates.iter().find(|c| c.join("main.py").exists()).cloned();
            let backend_dir = match backend_dir {
                Some(d) => d,
                None => {
                    eprintln!("[Murmur AI] could not locate backend/main.py or bundled sidecar (tried {:?})", candidates);
                    return;
                }
            };
            let python = if cfg!(windows) { "python" } else { "python3" };
            eprintln!("[Murmur AI] dev mode: using {python} main.py from {:?}", backend_dir);
            app.shell()
                .command(python)
                .args(["main.py"])
                .current_dir(backend_dir)
                .env("PYTHONUNBUFFERED", "1")
    };

    let result = command.spawn();

    match result {
        Ok((mut rx, child)) => {
            if let Ok(mut guard) = BACKEND_CHILD.lock() {
                *guard = Some(child);
            }
            tauri::async_runtime::spawn(async move {
                use tauri_plugin_shell::process::CommandEvent;
                while let Some(event) = rx.recv().await {
                    match event {
                        CommandEvent::Stdout(bytes) | CommandEvent::Stderr(bytes) => {
                            if let Ok(text) = String::from_utf8(bytes) {
                                eprintln!("[backend] {text}");
                            }
                        }
                        CommandEvent::Terminated(payload) => {
                            eprintln!("[backend] terminated: {payload:?}");
                            if let Ok(mut guard) = BACKEND_CHILD.lock() {
                                *guard = None;
                            }
                            break;
                        }
                        _ => {}
                    }
                }
            });
            eprintln!("[Murmur AI] backend sidecar spawned");
        }
        Err(err) => eprintln!("[Murmur AI] failed to spawn backend sidecar: {err}"),
    }
}

/// Stop the Python backend sidecar, preferring a clean HTTP shutdown so the
/// onefile bootloader cleans up its extraction directory.
fn kill_backend() {
    request_backend_shutdown();
    let still_running = backend_is_listening();
    if let Ok(mut guard) = BACKEND_CHILD.lock() {
        if let Some(child) = guard.take() {
            if still_running {
                if let Err(err) = child.kill() {
                    eprintln!("[Murmur AI] failed to kill backend sidecar: {err}");
                } else {
                    eprintln!("[Murmur AI] backend sidecar killed after graceful shutdown failed");
                }
            } else {
                eprintln!("[Murmur AI] backend sidecar exited cleanly");
            }
        }
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .plugin(tauri_plugin_autostart::init(
            tauri_plugin_autostart::MacosLauncher::LaunchAgent,
            Some(vec![]),
        ))
        // A second launch focuses the existing HUD and asks it to speak a cue,
        // instead of spawning a competing Python sidecar on port 8765.
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.show();
                let _ = window.set_focus();
                focus::announce_focus(app, "Murmur AI is already running");
            }
            let _ = app.emit("murmur://already-running", ());
        }))
        .setup(|app| {
            // Position the main window at bottom-center of the primary screen.
            if let Some(window) = app.get_webview_window("main") {
                if let Ok(size) = window.inner_size() {
                    if let Ok(Some(monitor)) = app.primary_monitor() {
                        let screen = monitor.size();
                        let scale = monitor.scale_factor();
                        let x = (screen.width as f64 - size.width as f64) / 2.0 / scale;
                        let y = (screen.height as f64 - size.height as f64) / scale - 60.0;
                        let _ = window.set_position(Position::Logical(tauri::LogicalPosition::new(x, y)));
                        let _ = window.set_skip_taskbar(true);
                    }
                }
            }

            // Spawn the Python backend sidecar automatically on startup. The
            // stale-sidecar probe does process I/O, so run it on Tokio's
            // blocking pool: setup returns immediately and the tray stays
            // responsive while the backend starts.
            let backend_handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                if !cfg!(debug_assertions) {
                    let _ = tauri::async_runtime::spawn_blocking(|| {
                        stop_stale_sidecar();
                        cleanup_stale_sidecar_temp();
                    })
                    .await;
                }
                spawn_backend(&backend_handle);
            });

            // Accessible tray actions map to the same WS command router as voice.
            let toggle_hud = MenuItem::with_id(app, "toggle", "Show / Hide HUD", true, None::<&str>)?;
            let toggle_listening = MenuItem::with_id(
                app, "toggle-listening", "Toggle Listening / Sleep", true, None::<&str>
            )?;
            let describe = MenuItem::with_id(app, "describe", "Describe Screen", true, None::<&str>)?;
            let diagnostics = MenuItem::with_id(app, "diagnostics", "Run Diagnostics", true, None::<&str>)?;
            let settings =
                MenuItem::with_id(app, "settings", "Settings…", true, None::<&str>)?;
            let autostart =
                MenuItem::with_id(app, "autostart", "Launch at Login (toggle)", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "Quit Murmur AI", true, None::<&str>)?;
            let menu = Menu::with_items(
                app,
                &[
                    &toggle_hud, &toggle_listening, &describe, &diagnostics,
                    &settings, &autostart, &quit,
                ],
            )?;

            let icon = match app.default_window_icon() {
                Some(icon) => icon.clone(),
                None => {
                    eprintln!("[Murmur AI] no default window icon configured");
                    return Ok(());
                }
            };

            let _tray = TrayIconBuilder::with_id("tray")
                .icon(icon)
                .menu(&menu)
                .tooltip("Murmur AI: local voice agent")
                .show_menu_on_left_click(false)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "toggle" => {
                        if let Some(window) = app.get_webview_window("main") {
                            toggle_window(&window);
                        }
                    }
                    "toggle-listening" => {
                        let _ = app.emit("backend:toggle-listening", ());
                    }
                    "describe" => {
                        let _ = app.emit("backend:describe-screen", ());
                    }
                    "diagnostics" => {
                        let _ = app.emit("backend:run-diagnostics", ());
                    }
                    "settings" => {
                        let _ = app.emit("backend:open-settings", ());
                    }
                    "autostart" => {
                        // Toggle the OS state directly; the frontend mirrors the
                        // new value into ~/.murmur-ai/config.json.
                        match app.autolaunch().is_enabled() {
                            Ok(true) => {
                                let _ = app.autolaunch().disable();
                                let _ = app.emit("murmur://autostart-changed", false);
                            }
                            _ => {
                                let _ = app.autolaunch().enable();
                                let _ = app.emit("murmur://autostart-changed", true);
                            }
                        }
                    }
                    "quit" => {
                        kill_backend();
                        app.exit(0);
                    }
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        if let Some(window) = tray.app_handle().get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.set_focus();
                            focus::announce_focus(tray.app_handle(), "Murmur AI");
                        }
                    }
                })
                .build(app)?;

            // Global hotkey: Ctrl/Cmd+Shift+Space toggles sleep/wake standby.
            // The backend announces the state change aloud for screen-reader
            // and keyboard users, so this is a tactile override.
            let shortcut = Shortcut::new(
                Some(Modifiers::CONTROL | Modifiers::SHIFT),
                Code::Space,
            );
            if let Err(e) = app.global_shortcut().register(shortcut) {
                eprintln!("[Murmur AI] failed to register sleep/wake hotkey: {}", e);
            } else {
                let handle = app.handle().clone();
                if let Err(e) = app.global_shortcut().on_shortcut(
                    shortcut,
                    move |_app, _shortcut, event| {
                        if event.state != ShortcutState::Pressed {
                            return;
                        }
                        // Ask the frontend (which owns the WS connection) to
                        // toggle mode. The backend speaks the announcement.
                        let _ = handle.emit("toggle-sleep-wake", ());
                    },
                ) {
                    eprintln!("[Murmur AI] failed to attach sleep/wake hotkey handler: {}", e);
                }
            }

            // Global hotkey: Ctrl/Cmd+Shift+Q stops spoken output immediately.
            let quiet_shortcut = Shortcut::new(
                Some(Modifiers::CONTROL | Modifiers::SHIFT),
                Code::KeyQ,
            );
            if let Err(e) = app.global_shortcut().register(quiet_shortcut) {
                eprintln!("[Murmur AI] failed to register be-quiet hotkey: {}", e);
            } else {
                let handle = app.handle().clone();
                if let Err(e) = app.global_shortcut().on_shortcut(
                    quiet_shortcut,
                    move |_app, _shortcut, event| {
                        if event.state != ShortcutState::Pressed {
                            return;
                        }
                        let _ = handle.emit("backend:be-quiet", ());
                    },
                ) {
                    eprintln!("[Murmur AI] failed to attach be-quiet handler: {}", e);
                }
            }

            Ok(())
        })
        .on_window_event(|window, event| match event {
            // Only the main HUD owns the sidecar. Closing the click-through
            // cursor overlay must never kill the backend or leave a zombie app.
            tauri::WindowEvent::Destroyed | tauri::WindowEvent::CloseRequested { .. }
                if window.label() == "main" =>
            {
                kill_backend();
            }
            // Native alt-tab / tray return: let the webview restore DOM focus
            // and re-announce status without stealing focus from other apps.
            tauri::WindowEvent::Focused(true) => {
                focus::announce_focus(window.app_handle(), "Murmur AI");
            }
            _ => {}
        })
        .invoke_handler(tauri::generate_handler![
            check_for_updates,
            install_update,
            permissions::check_os_permissions,
            focus::restore_focus,
            autostart_enabled,
            set_autostart,
            quit_app
        ])
        .run(tauri::generate_context!())
        .expect("error while running Murmur AI");
}

#[cfg(test)]
mod tests {
    use super::command_error_message;

    #[test]
    fn command_errors_are_speakable_and_never_empty() {
        assert_eq!(
            command_error_message("Update check", "network unreachable"),
            "Update check failed: network unreachable"
        );
        assert_eq!(
            command_error_message("Update check", "  \n "),
            "Update check is unavailable."
        );
        assert_eq!(command_error_message("Update check", ""), "Update check is unavailable.");
    }
}
