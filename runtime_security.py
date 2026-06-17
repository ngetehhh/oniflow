#!/usr/bin/env python3
"""Runtime integrity and license enforcement for Oniflow releases."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path

from offline_license import _rsa_verify, canonical_payload, device_id, public_key_is_trusted, verify_license


def verify_integrity(root: Path, require_manifest: bool = False) -> tuple[bool, str]:
    manifest_path = root / "integrity-manifest.json"
    public_key_path = root / "assets" / "offline-license-public.json"
    if not manifest_path.is_file():
        return (False, "The signed integrity manifest is missing.") if require_manifest else (True, "Development mode.")
    try:
        if not public_key_is_trusted(public_key_path):
            return False, "The Oniflow public key has been modified."
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload = document["payload"]
        signature = base64.b64decode(document["signature"], validate=True)
        public_key = json.loads(public_key_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not _rsa_verify(canonical_payload(payload), signature, public_key):
            return False, "The integrity manifest signature is invalid."
        if payload.get("product") != "Oniflow":
            return False, "The integrity manifest belongs to another product."
        files = payload.get("files")
        if not isinstance(files, dict):
            return False, "The integrity manifest file list is invalid."
        for relative, expected_hash in files.items():
            path = root / str(relative)
            if not path.is_file():
                return False, f"A protected application file is missing: {relative}"
            actual_hash = hashlib.sha256(path.read_bytes()).hexdigest().upper()
            if actual_hash != str(expected_hash).upper():
                return False, f"A protected application file has been modified: {relative}"
        return True, "Application integrity verified."
    except (KeyError, ValueError, TypeError, json.JSONDecodeError, OSError):
        return False, "The signed integrity manifest is invalid."


def verify_runtime_access(root: Path, require_manifest: bool = False) -> tuple[bool, str]:
    integrity_ok, integrity_message = verify_integrity(root, require_manifest)
    if not integrity_ok:
        return False, integrity_message
    app_data = Path(os.environ.get("LOCALAPPDATA", root)) / "Oniflow"
    license_ok, license_message, _ = verify_license(
        app_data / "license.json",
        root / "assets" / "offline-license-public.json",
        device_id(),
    )
    if not license_ok:
        return False, license_message
    return True, "Runtime access verified."


def require_runtime_access(root: Path, require_manifest: bool = False) -> None:
    valid, message = verify_runtime_access(root, require_manifest)
    if not valid:
        raise RuntimeError(message)

