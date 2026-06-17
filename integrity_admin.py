#!/usr/bin/env python3
"""Owner-only utility for creating a signed Oniflow integrity manifest."""

from __future__ import annotations

import base64
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from offline_license import canonical_payload
from offline_license_admin import DEFAULT_PRIVATE_KEY, sign


PROTECTED_FILES = (
    "Oniflow.exe",
    "anime_vfi.pyc",
    "anime_vfi_gui.pyc",
    "offline_license.pyc",
    "runtime_security.pyc",
    "config.json",
    "assets/offline-license-public.json",
    "work/GMFSS_Fortuna/inference_video.py",
    "work/GMFSS_Fortuna/model/GMFSS_infer_b.py",
    "work/GMFSS_Fortuna/model/GMFSS_infer_u.py",
)


def create_manifest(release_root: Path, private_key_path: Path = DEFAULT_PRIVATE_KEY) -> Path:
    files: dict[str, str] = {}
    for relative in PROTECTED_FILES:
        path = release_root / relative
        if not path.is_file():
            raise FileNotFoundError(f"Protected release file is missing: {relative}")
        files[relative] = hashlib.sha256(path.read_bytes()).hexdigest().upper()
    payload: dict[str, object] = {
        "product": "Oniflow",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files": files,
    }
    private_key = json.loads(private_key_path.read_text(encoding="utf-8"))
    document = {
        "payload": payload,
        "signature": base64.b64encode(sign(canonical_payload(payload), private_key)).decode("ascii"),
    }
    output = release_root / "integrity-manifest.json"
    output.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return output


if __name__ == "__main__":
    print(create_manifest(Path(sys.argv[1] if len(sys.argv) > 1 else "release/Oniflow").resolve()))
