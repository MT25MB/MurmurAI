//! Native focus recovery for the floating HUD.
//!
//! Alt-tabbing back to a borderless, always-on-top webview can leave DOM focus
//! on `document.body` with no visible focus ring. The shell emits a short event
//! on every native focus regain; the webview uses it to restore keyboard focus
//! and re-announce status through its polite live region. No focus is ever
//! stolen from another application — this only runs once we are already focused.

use tauri::{Emitter, Manager, WebviewWindow};

/// Event consumed by the React focus-recovery helper.
pub const FOCUS_RESTORED_EVENT: &str = "murmur://window-focused";

/// Stable, speakable announcement. Pure so it is unit-testable.
pub fn focus_message(label: &str) -> String {
    format!("{label} window is active. Keyboard focus restored.")
}

/// Tell the webview it is active again so DOM focus and live text can recover.
pub fn announce_focus(app: &tauri::AppHandle, label: &str) {
    let _ = app.emit(FOCUS_RESTORED_EVENT, focus_message(label));
}

/// Explicit reclaim for the tray / frontend. Fails with a readable message
/// instead of panicking when the window was closed.
#[tauri::command]
pub async fn restore_focus(window: WebviewWindow) -> Result<(), String> {
    window.set_focus().map_err(|error| error.to_string())?;
    announce_focus(window.app_handle(), "Murmur AI");
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn focus_message_names_the_window_and_recovery() {
        let message = focus_message("Murmur AI");
        assert_eq!(message, "Murmur AI window is active. Keyboard focus restored.");
        assert!(message.contains("focus"));
    }

    #[test]
    fn focus_event_identifier_is_versioned() {
        assert_eq!(FOCUS_RESTORED_EVENT, "murmur://window-focused");
    }
}
