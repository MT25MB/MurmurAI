# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Murmur AI backend sidecar.

Produces a single standalone (onefile) binary named with Tauri's target-triple
convention, then copies it into src-tauri/binaries/ so `externalBin` can bundle
it into the final app installers.

Target triple comes from TAURI_TARGET_TRIPLE (set in CI) with a per-OS fallback:
  - Windows:  murmur-backend-x86_64-pc-windows-msvc.exe
  - macOS:    murmur-backend-aarch64-apple-darwin
  - Linux:    murmur-backend-x86_64-unknown-linux-gnu
"""

import os
import platform
import shutil

from PyInstaller.utils.hooks import collect_all, collect_submodules

# ---- resolve Tauri target triple -> output name ----
triple = os.environ.get("TAURI_TARGET_TRIPLE", "").strip()
if not triple:
    system = platform.system()
    machine = platform.machine().lower()
    arch = "aarch64" if machine in ("arm64", "aarch64") else "x86_64"
    if system == "Windows":
        triple = "x86_64-pc-windows-msvc"
    elif system == "Darwin":
        triple = f"{arch}-apple-darwin"
    else:
        triple = f"{arch}-unknown-linux-gnu"

binary_name = f"murmur-backend-{triple}"
if platform.system() == "Windows":
    binary_name += ".exe"

# PyInstaller spec globals like SCRIPT are not available in every version/OS.
# The release workflow runs pyinstaller from backend/, so cwd is reliable.
src_dir = os.getcwd()

# ---- collect heavy optional dependencies into the bundle ----
datas = []
binaries = []
hiddenimports = [
    "uvicorn", "uvicorn.protocols", "fastapi", "starlette", "pydantic",
    "httpx", "websockets", "dotenv",
]

for package in (
    "faster_whisper",
    "kokoro",
    "cv2",
    "mss",
    "pyautogui",
    "sounddevice",
    "webrtcvad",
    "pyttsx3",
    "PIL",
    "numpy",
    "onnxruntime",
):
    try:
        # collect_all returns (datas, binaries, hiddenimports) — order matters.
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
        datas.extend(pkg_datas)
        binaries.extend(pkg_binaries)
        hiddenimports.extend(pkg_hidden)
    except Exception:
        # Optional dependency not installed on this runner — include imports anyway.
        hiddenimports.extend(collect_submodules(package))

# Local Python packages used by main.py.
hiddenimports.extend([
    "agent", "agent.brain", "agent.state", "agent.vision_agent",
    "agent.som_overlay", "agent.app_knowledge",
    "audio", "audio.listener", "audio.speaker",
    "tools", "tools.os_tools", "tools.safety", "tools.installer_tool",
    "tools.event_bus", "setup",
])

a = Analysis(
    [os.path.join(src_dir, "main.py")],
    pathex=[src_dir],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "torch", "tensorflow"],
    noarchive=False,
)

pyz = PYZ(a.pure)

# Onefile: embed binaries/datas into a single executable.
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=binary_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,           # GUI app — no console window on Windows/macOS
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# Copy the onefile binary from dist/ into src-tauri/binaries/ for Tauri bundling.
binaries_dir = os.path.normpath(os.path.join(src_dir, "..", "src-tauri", "binaries"))
os.makedirs(binaries_dir, exist_ok=True)
source_exe = os.path.join("dist", binary_name)
dest_exe = os.path.join(binaries_dir, binary_name)
if os.path.exists(source_exe):
    shutil.copy2(source_exe, dest_exe)
    print(f"[Murmur AI] sidecar copied to {dest_exe}")
