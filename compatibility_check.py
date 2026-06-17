#!/usr/bin/env python3
"""Run local Oniflow release compatibility checks."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def main() -> int:
    tools = {name: shutil.which(name) for name in ("ffmpeg", "ffprobe", "nvidia-smi")}
    documents = {
        name: (ROOT / name).is_file()
        for name in (
            "VERSION",
            "HELP.md",
            "EULA.md",
            "PRIVACY.md",
            "THIRD_PARTY_NOTICES.md",
            "UPDATE_POLICY.md",
            "DISTRIBUTION_SECURITY.md",
            "RELEASE_CHECKLIST.md",
        )
    }
    result: dict[str, object] = {"tools": tools, "documents": documents}
    if tools["ffmpeg"]:
        encoders = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True, check=False
        ).stdout
        result["nvenc"] = {codec: codec in encoders for codec in ("av1_nvenc", "hevc_nvenc", "h264_nvenc")}
    if tools["nvidia-smi"]:
        result["gpu"] = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"],
            capture_output=True, text=True, check=False
        ).stdout.strip()
    print(json.dumps(result, indent=2))
    return 0 if all(tools.values()) and all(documents.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
