#!/usr/bin/env python3
"""Owner-only utility for creating signed Oniflow offline licenses."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from offline_license import SHA256_DIGEST_INFO_PREFIX, canonical_payload


ROOT = Path(__file__).resolve().parent
DEFAULT_PRIVATE_KEY = ROOT / "private" / "offline-license-private.json"


def decode_integer(value: str) -> int:
    return int.from_bytes(base64.b64decode(value), "big")


def sign(message: bytes, private_key: dict[str, object]) -> bytes:
    modulus = decode_integer(str(private_key["modulus"]))
    private_exponent = decode_integer(str(private_key["private_exponent"]))
    size = (modulus.bit_length() + 7) // 8
    digest_info = SHA256_DIGEST_INFO_PREFIX + hashlib.sha256(message).digest()
    encoded = b"\x00\x01" + (b"\xff" * (size - len(digest_info) - 3)) + b"\x00" + digest_info
    return pow(int.from_bytes(encoded, "big"), private_exponent, modulus).to_bytes(size, "big")


def create_license(args: argparse.Namespace) -> Path:
    private_key = json.loads(args.private_key.read_text(encoding="utf-8"))
    issued_at = datetime.now(timezone.utc)
    expires_at = "" if args.days == 0 else (issued_at + timedelta(days=args.days)).isoformat()
    payload: dict[str, object] = {
        "product": "Oniflow",
        "license_id": secrets.token_hex(12).upper(),
        "licensed_to": args.name.strip() or "Oniflow User",
        "device_id": args.device_id.strip().upper(),
        "issued_at": issued_at.isoformat(),
        "expires_at": expires_at,
    }
    document = {
        "payload": payload,
        "signature": base64.b64encode(sign(canonical_payload(payload), private_key)).decode("ascii"),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return args.output


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a signed Oniflow offline license.")
    parser.add_argument("--device-id", required=True)
    parser.add_argument("--name", default="Oniflow User")
    parser.add_argument("--days", type=int, default=0, help="Validity in days. Use 0 for no expiry.")
    parser.add_argument("--output", type=Path, default=ROOT / "generated-licenses" / "oniflow-license.json")
    parser.add_argument("--private-key", type=Path, default=DEFAULT_PRIVATE_KEY)
    args = parser.parse_args()
    if args.days < 0:
        parser.error("--days cannot be negative")
    print(create_license(args).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

