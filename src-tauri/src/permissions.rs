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

#[cfg(windows)]
fn consent(key: &str) -> PermissionState {
    use std::process::Command;
    let output = Command::new("reg")
        .args(["query", key, "/v", "Value"])
        .output();
    match output {
        Ok(out) if out.status.success() => {
            let text = String::from_utf8_lossy(&out.stdout).to_lowercase();
            if text.contains("denied") {
                PermissionState::Denied
            } else if text.contains("allow") {
                PermissionState::Granted
            } else {
                PermissionState::Unknown
            }
        }
        _ => PermissionState::Unknown,
    }
}

#[cfg(windows)]
pub fn check_permissions() -> PermissionReport {
    let base = r"HKCU\Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore";
    let mic = consent(&format!(r"{}\microphone", base));
    let screen = PermissionState::Unknown;
    let accessibility = PermissionState::Unknown;
    build(mic, screen, accessibility)
}

#[cfg(target_os = "macos")]
pub fn check_permissions() -> PermissionReport {
    // TCC cannot be read without extra entitlements; report plainly.
    build(PermissionState::Unknown, PermissionState::Unknown, PermissionState::Unknown)
}

#[cfg(target_os = "linux")]
pub fn check_permissions() -> PermissionReport {
    let mic = if std::env::var_os("MURMUR_NO_AUDIO").is_some() {
        PermissionState::NotNeeded
    } else {
        PermissionState::Unknown
    };
    build(mic, PermissionState::NotNeeded, PermissionState::Unknown)
}

#[cfg(not(any(windows, target_os = "macos", target_os = "linux")))]
pub fn check_permissions() -> PermissionReport {
    build(PermissionState::Unknown, PermissionState::Unknown, PermissionState::Unknown)
}

#[tauri::command]
pub fn check_os_permissions() -> PermissionReport {
    check_permissions()
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
}
