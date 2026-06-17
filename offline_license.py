#!/usr/bin/env python3
"""Create and verify signed, device-bound Oniflow offline licenses."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path


SHA256_DIGEST_INFO_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")
EXPECTED_PUBLIC_KEY_SHA256 = "3AE81D506CEF716F5FDF252DA582121D845616304F340801C46F55384160B345"


def canonical_payload(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _windows_machine_guid() -> str:
    if os.name != "nt":
        return ""
    try:
        result = subprocess.run(
            [
                "reg",
                "query",
                r"HKLM\SOFTWARE\Microsoft\Cryptography",
                "/v",
                "MachineGuid",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if "MachineGuid" in line:
                    return line.split()[-1].strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return ""


def device_id() -> str:
    identity = _windows_machine_guid() or f"{uuid.getnode():012x}"
    digest = hashlib.sha256(f"ONIFLOW|{identity}".encode("utf-8")).hexdigest().upper()
    return "-".join(digest[index:index + 8] for index in range(0, 32, 8))


def _decode_integer(value: str) -> int:
    return int.from_bytes(base64.b64decode(value), "big")


def _rsa_verify(message: bytes, signature: bytes, public_key: dict[str, object]) -> bool:
    modulus = _decode_integer(str(public_key["modulus"]))
    exponent = _decode_integer(str(public_key["exponent"]))
    size = (modulus.bit_length() + 7) // 8
    if len(signature) != size:
        return False
    decoded = pow(int.from_bytes(signature, "big"), exponent, modulus).to_bytes(size, "big")
    digest_info = SHA256_DIGEST_INFO_PREFIX + hashlib.sha256(message).digest()
    expected = b"\x00\x01" + (b"\xff" * (size - len(digest_info) - 3)) + b"\x00" + digest_info
    return decoded == expected


def public_key_is_trusted(public_key_path: Path) -> bool:
    try:
        return hashlib.sha256(public_key_path.read_bytes()).hexdigest().upper() == EXPECTED_PUBLIC_KEY_SHA256
    except OSError:
        return False


def verify_license(
    license_path: Path,
    public_key_path: Path,
    expected_device_id: str | None = None,
    now: datetime | None = None,
) -> tuple[bool, str, dict[str, object]]:
    try:
        if not public_key_is_trusted(public_key_path):
            return False, "The Oniflow public key is missing or has been modified.", {}
        license_data = json.loads(license_path.read_text(encoding="utf-8"))
        public_key = json.loads(public_key_path.read_text(encoding="utf-8"))
        payload = license_data["payload"]
        signature = base64.b64decode(license_data["signature"], validate=True)
        if not isinstance(payload, dict) or not _rsa_verify(canonical_payload(payload), signature, public_key):
            return False, "The license signature is invalid.", {}
        if payload.get("product") != "Oniflow":
            return False, "This license is not valid for Oniflow.", payload
        if str(payload.get("device_id", "")).upper() != (expected_device_id or device_id()).upper():
            return False, "This license belongs to a different computer.", payload
        expires_at = str(payload.get("expires_at", "")).strip()
        if expires_at:
            expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            if (now or datetime.now(timezone.utc)) >= expiry:
                return False, "This license has expired.", payload
        return True, "License is valid.", payload
    except FileNotFoundError:
        return False, "No offline license is installed.", {}
    except (KeyError, ValueError, TypeError, json.JSONDecodeError, OSError):
        return False, "The offline license file is invalid.", {}
