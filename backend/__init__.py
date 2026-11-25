"""Murmur AI local backend sidecar.

Single source of truth for the backend version, kept in sync with the app and
the website. Bump this together with package.json, tauri.conf.json, Cargo.toml
and the lockfiles when cutting a release.
"""

__version__ = "1.2.26"

__all__ = ["__version__"]
