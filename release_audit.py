#!/usr/bin/env python3
"""Reject unsafe or private files before an Oniflow release is distributed."""

from __future__ import annotations

import re
import sys
import os
from pathlib import Path


FORBIDDEN_NAMES = {
    ".git",
    "__pycache__",
    "logs",
    "outputs",
    "user_settings.json",
    "runtime-config.json",
    "private",
    "generated-licenses",
    "license.json",
    "offline_license_admin.py",
    "integrity_admin.py",
    "buat_offline_license.ps1",
    "buat_kunci_offline_license.ps1",
}
FORBIDDEN_SUFFIXES = {".log", ".pyo", ".mp4", ".mkv", ".mov", ".avi", ".webm", ".ts"}
TEXT_SUFFIXES = {".cfg", ".ini", ".json", ".md", ".py", ".ps1", ".txt", ".xml", ".yaml", ".yml"}
FORBIDDEN_RELEASE_FILES = {
    Path("anime_vfi.py"),
    Path("anime_vfi_gui.py"),
    Path("offline_license.py"),
    Path("runtime_security.py"),
}
REQUIRED_RELEASE_FILES = {
    Path("Oniflow.exe"),
    Path("anime_vfi.pyc"),
    Path("anime_vfi_gui.pyc"),
    Path("offline_license.pyc"),
    Path("runtime_security.pyc"),
    Path("integrity-manifest.json"),
    Path("assets/offline-license-public.json"),
}
SECRET_PATTERNS = {
    "private key": re.compile(r"BEGIN (?:RSA |OPENSSH )?PRIVATE KEY"),
    "GitHub token": re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "OpenAI-style secret": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
}
WINDOWS_USER = os.environ.get("USERNAME", "")
PRIVATE_PATH_PATTERN = (
    re.compile(rf"[A-Za-z]:\\Users\\{re.escape(WINDOWS_USER)}\\", re.IGNORECASE)
    if WINDOWS_USER
    else None
)


def audit(root: Path) -> list[str]:
    findings: list[str] = []
    for required in REQUIRED_RELEASE_FILES:
        if not (root / required).is_file():
            findings.append(f"required protected release file missing: {required}")
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if relative in FORBIDDEN_RELEASE_FILES:
            findings.append(f"unprotected application source: {relative}")
            continue
        if any(part in FORBIDDEN_NAMES for part in relative.parts):
            findings.append(f"forbidden path: {relative}")
            continue
        if not path.is_file():
            continue
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            findings.append(f"forbidden release file: {relative}")
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES or path.stat().st_size > 5_000_000:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if PRIVATE_PATH_PATTERN and PRIVATE_PATH_PATTERN.search(text):
            findings.append(f"private Windows user path: {relative}")
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                findings.append(f"{label}: {relative}")
    return findings


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "dist/Oniflow").resolve()
    if not root.is_dir():
        print(f"Release directory does not exist: {root}")
        return 1
    findings = audit(root)
    if findings:
        print("Release audit failed:")
        for finding in findings:
            print(f"- {finding}")
        return 1
    print("Release audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
