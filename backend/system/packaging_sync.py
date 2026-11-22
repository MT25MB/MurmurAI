"""Update package manifests with release versions and SHA256 checksums.

Called from the release workflow after all platform installers have been built.
Missing artifact types leave their placeholders untouched so templates stay
valid and the job remains auditable.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

RELEASE_BASE = "https://github.com/MT25MB/MurmurAI/releases/download/v{version}/{name}"

ARTIFACT_KINDS = {
    "msi": ".msi",
    "exe": ".exe",
    "dmg": ".dmg",
    "appimage": ".appimage",
    "deb": ".deb",
    "rpm": ".rpm",
}
SKIP_SUFFIXES = {".sig", ".json", ".txt", ".xml", ".yaml", ".yml", ".sha256"}


@dataclass
class Artifact:
    path: Path
    sha256: str
    url: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _kind_for(name: str) -> Optional[str]:
    lowered = name.lower()
    if lowered.endswith(".sig") or lowered in ("sha256sums.txt", "latest.json"):
        return None
    for kind, suffix in ARTIFACT_KINDS.items():
        if lowered.endswith(suffix):
            return kind
    return None


def collect_artifacts(assets_dir: Path, version: str) -> dict[str, Artifact]:
    """Map artifact kind -> Artifact for installers found in ``assets_dir``."""
    result: dict[str, Artifact] = {}
    if not assets_dir.is_dir():
        return result
    for path in sorted(assets_dir.iterdir()):
        if not path.is_file():
            continue
        kind = _kind_for(path.name)
        if kind is None:
            continue
        # Prefer .msi over a raw .exe when both exist, and don't overwrite it.
        if kind in result:
            continue
        result[kind] = Artifact(
            path=path,
            sha256=sha256_file(path),
            url=RELEASE_BASE.format(version=version, name=path.name),
        )
    return result


def token_map(version: str, date: str, artifacts: dict[str, Artifact]) -> dict[str, str]:
    tokens = {"{{VERSION}}": version, "{{DATE}}": date}
    for kind, artifact in artifacts.items():
        tokens[f"{{{{{kind.upper()}_URL}}}}"] = artifact.url
        tokens[f"{{{{{kind.upper()}_SHA256}}}}"] = artifact.sha256.upper()
    return tokens


def replace_tokens(text: str, tokens: dict[str, str]) -> str:
    for token, value in tokens.items():
        text = text.replace(token, value)
    return text


def sync_manifests(
    packaging_dir: Path, version: str, artifacts: dict[str, Artifact],
    date: Optional[str] = None,
) -> list[Path]:
    """Rewrite every template in-place and return the list of changed files."""
    date = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    tokens = token_map(version, date, artifacts)
    targets = [
        packaging_dir / "winget" / "MurmurAI.yaml",
        packaging_dir / "homebrew" / "murmur-ai.rb",
        packaging_dir / "linux" / "murmur-ai.desktop",
        packaging_dir / "linux" / "com.murmurai.MurmurAI.metainfo.xml",
    ]
    changed = []
    for path in targets:
        if not path.exists():
            continue
        original = path.read_text(encoding="utf-8")
        updated = replace_tokens(original, tokens)
        if updated != original:
            path.write_text(updated, encoding="utf-8")
            changed.append(path)
    return changed


def write_sha256sums(artifacts: dict[str, Artifact], output: Path) -> Path:
    lines = [
        f"{artifact.sha256}  {artifact.path.name}"
        for artifact in sorted(artifacts.values(), key=lambda item: item.path.name)
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output
