use tauri::menu::{Menu, MenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{Emitter, Manager, Position, WebviewWindow};
use tauri_plugin_shell::process::CommandChild;
use tauri_plugin_shell::ShellExt;
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut};
use tauri_plugin_updater::UpdaterExt;
use serde::Serialize;

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
        Err(error) => return Ok(unavailable(Some(error.to_string()))),
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
        Err(error) => Ok(unavailable(Some(error.to_string()))),
    }
}

/// Download and install the pending update, then restart the app.
#[tauri::command]
async fn install_update(app: tauri::AppHandle) -> Result<(), String> {
    let _ = app.emit("murmur://update-status", "Downloading the update…");
    let updater = app.updater().map_err(|error| error.to_string())?;
    let update = updater
        .check()
        .await
        .map_err(|error| error.to_string())?
        .ok_or_else(|| "No update is available".to_string())?;

    update
        .download_and_install(|_, _| {}, || {})
        .await
        .map_err(|error| error.to_string())?;
    let _ = app.emit("murmur://update-status", "Update installed. Restarting…");
    // restart() diverges (the app process is replaced), so it is the tail.
    app.restart()
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
        }
        Err(err) => eprintln!("[Murmur AI] failed to read window visibility: {err}"),
    }
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
                // Sidecar missing at runtime — surface a clear error.
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

/// Kill the Python backend sidecar.
fn kill_backend() {
    if let Ok(mut guard) = BACKEND_CHILD.lock() {
        if let Some(child) = guard.take() {
            if let Err(err) = child.kill() {
                eprintln!("[Murmur AI] failed to kill backend sidecar: {err}");
            } else {
                eprintln!("[Murmur AI] backend sidecar killed");
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

            // Spawn the Python backend sidecar automatically on startup.
            spawn_backend(app.handle());

            let toggle = MenuItem::with_id(app, "toggle", "Show / Hide HUD", true, None::<&str>)?;
            let start = MenuItem::with_id(app, "start", "Start Listening", true, None::<&str>)?;
            let pause = MenuItem::with_id(app, "pause", "Pause Listening", true, None::<&str>)?;
            let model = MenuItem::with_id(app, "model", "Select Ollama Model", true, None::<&str>)?;
            let settings =
                MenuItem::with_id(app, "settings", "Settings…", true, None::<&str>)?;
            let autostart =
                MenuItem::with_id(app, "autostart", "Launch at Startup", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "Quit Murmur AI", true, None::<&str>)?;
            let menu = Menu::with_items(
                app,
                &[&toggle, &start, &pause, &model, &settings, &autostart, &quit],
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
                .tooltip("Murmur AI — local voice agent")
                .show_menu_on_left_click(false)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "toggle" => {
                        if let Some(window) = app.get_webview_window("main") {
                            toggle_window(&window);
                        }
                    }
                    "start" => {
                        let _ = app.emit("backend:start-listening", ());
                    }
                    "pause" => {
                        let _ = app.emit("backend:pause-listening", ());
                    }
                    "model" => {
                        let _ = app.emit("backend:select-model", ());
                    }
                    "settings" => {
                        let _ = app.emit("backend:open-settings", ());
                    }
                    "autostart" => {
                        let _ = app.emit("backend:toggle-autostart", ());
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
                    move |_app, _shortcut, _event| {
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
                    move |_app, _shortcut, _event| {
                        let _ = handle.emit("backend:be-quiet", ());
                    },
                ) {
                    eprintln!("[Murmur AI] failed to attach be-quiet handler: {}", e);
                }
            }

            Ok(())
        })
        .on_window_event(|_window, event| {
            if matches!(
                event,
                tauri::WindowEvent::Destroyed | tauri::WindowEvent::CloseRequested { .. }
            ) {
                kill_backend();
            }
        })
        .invoke_handler(tauri::generate_handler![check_for_updates, install_update])
        .run(tauri::generate_context!())
        .expect("error while running Murmur AI");
}
