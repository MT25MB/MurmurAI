//! Best-effort OS permission diagnostics for the local agent.
//!
//! All probes are read-only and side-effect free. A probe may not be able to
//! determine a state on every platform; `unknown` is reported plainly rather
//! than assumed to be granted.

use serde::Serialize;

#[allow(dead_code)] // platform-specific variants are not used on every OS
#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub enum PermissionState {
    Granted,
    Denied,
    Unknown,
    NotNeeded,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PermissionReport {
    pub microphone: PermissionState,
    pub screen: PermissionState,
    pub accessibility: PermissionState,
    pub recovery: Vec<String>,
    pub summary: String,
}

fn build(mic: PermissionState, screen: PermissionState, accessibility: PermissionState) -> PermissionReport {
    let mut recovery = Vec::new();
    if mic == PermissionState::Denied {
        recovery.push("Allow microphone access in your system privacy settings.".into());
    }
    if screen == PermissionState::Denied {
        recovery.push("Allow screen recording for Murmur AI in your system privacy settings.".into());
    }
    if accessibility == PermissionState::Denied {
        recovery.push("Allow accessibility access so Murmur can read and click named controls.".into());
    }
    let summary = if recovery.is_empty() {
        "No permission problems detected.".into()
    } else {
        format!("Permissions need attention: {}", recovery.join(" "))
    };
    PermissionReport { microphone: mic, screen, accessibility, recovery, summary }
}

/// Map a registry probe to a state. Pure so every failure path is testable.
pub(crate) fn state_from_reg_output(text: &str, succeeded: bool) -> PermissionState {
    if !succeeded {
        return PermissionState::Unknown;
    }
    let lowered = text.to_lowercase();
    if lowered.contains("denied") {
        PermissionState::Denied
    } else if lowered.contains("allow") {
        PermissionState::Granted
    } else {
        PermissionState::Unknown
    }
}

#[cfg(windows)]
fn probe_reg(key: &str) -> (bool, String) {
    use std::process::Command;
    match Command::new("reg").args(["query", key, "/v", "Value"]).output() {
        Ok(out) if out.status.success() => {
            (true, String::from_utf8_lossy(&out.stdout).into_owned())
        }
        // A failed or unreadable probe is "unknown", never an app error.
        _ => (false, String::new()),
    }
}

#[cfg(windows)]
async fn consent(key: &str) -> PermissionState {
    let key = key.to_string();
    // `reg.exe` is blocking process I/O. Run it on Tokio's blocking pool so the
    // command handler never stalls the UI thread, tray, or other commands.
    let (succeeded, text) = tauri::async_runtime::spawn_blocking(move || probe_reg(&key))
        .await
        .unwrap_or((false, String::new()));
    state_from_reg_output(&text, succeeded)
}

#[cfg(windows)]
pub async fn check_permissions() -> PermissionReport {
    let base = r"HKCU\Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore";
    let mic = consent(&format!(r"{}\microphone", base)).await;
    let screen = PermissionState::Unknown;
    let accessibility = PermissionState::Unknown;
    build(mic, screen, accessibility)
}

#[cfg(target_os = "macos")]
pub async fn check_permissions() -> PermissionReport {
    // TCC cannot be read without extra entitlements; report plainly.
    build(PermissionState::Unknown, PermissionState::Unknown, PermissionState::Unknown)
}

#[cfg(target_os = "linux")]
pub async fn check_permissions() -> PermissionReport {
    let mic = if std::env::var_os("MURMUR_NO_AUDIO").is_some() {
        PermissionState::NotNeeded
    } else {
        PermissionState::Unknown
    };
    build(mic, PermissionState::NotNeeded, PermissionState::Unknown)
}

#[cfg(not(any(windows, target_os = "macos", target_os = "linux")))]
pub async fn check_permissions() -> PermissionReport {
    build(PermissionState::Unknown, PermissionState::Unknown, PermissionState::Unknown)
}

/// Read-only diagnostic probe. Never fails the IPC call: an unavailable probe is
/// reported as `unknown` so the HUD can speak recovery steps instead of freezing.
#[tauri::command]
pub async fn check_os_permissions() -> PermissionReport {
    check_permissions().await
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn denied_permission_gets_recovery_text() {
        let report = build(PermissionState::Denied, PermissionState::Granted, PermissionState::NotNeeded);
        assert_eq!(report.recovery.len(), 1);
        assert!(report.summary.contains("microphone"));
    }

    #[test]
    fn all_granted_has_no_recovery() {
        let report = build(PermissionState::Granted, PermissionState::Granted, PermissionState::Granted);
        assert!(report.recovery.is_empty());
    }

    #[test]
    fn reg_probe_maps_denied_allowed_and_unreadable_output() {
        assert_eq!(state_from_reg_output("Value    REG_DWORD    0x0\nDenied", true), PermissionState::Denied);
        assert_eq!(state_from_reg_output("Value    REG_DWORD    0x1\nAllow", true), PermissionState::Granted);
        assert_eq!(state_from_reg_output("unexpected output", true), PermissionState::Unknown);
        // Command failed / registry key absent must degrade to unknown, not error.
        assert_eq!(state_from_reg_output("ignored", false), PermissionState::Unknown);
        assert_eq!(state_from_reg_output("Allow", false), PermissionState::Unknown);
    }

    #[test]
    fn failed_probe_produces_no_false_recovery_claim() {
        let report = build(
            state_from_reg_output("reg.exe not found", false),
            PermissionState::Unknown,
            PermissionState::Unknown,
        );
        assert!(report.recovery.is_empty());
        assert_eq!(report.microphone, PermissionState::Unknown);
        assert_eq!(report.summary, "No permission problems detected.");
    }
}
