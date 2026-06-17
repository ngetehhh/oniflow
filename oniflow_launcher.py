#!/usr/bin/env python3
"""Launch the Oniflow GUI through the bundled standalone Python runtime."""

from __future__ import annotations

import os
import subprocess
import sys
import ctypes
from pathlib import Path

from runtime_security import verify_integrity


def main() -> int:
    packaged = getattr(sys, "frozen", False) or "__compiled__" in globals()
    root = Path(sys.argv[0]).resolve().parent if packaged else Path(__file__).resolve().parent
    pythonw = root / "work" / "python-runtime" / "pythonw.exe"
    gui = root / "anime_vfi_gui.pyc"
    if not pythonw.is_file() or not gui.is_file():
        raise RuntimeError("Oniflow portable runtime is incomplete. Extract the full Oniflow folder before running.")
    integrity_ok, integrity_message = verify_integrity(root, require_manifest=packaged)
    if not integrity_ok:
        raise RuntimeError(integrity_message)
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    subprocess.Popen(
        [str(pythonw), str(gui)],
        cwd=root,
        env=environment,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        if sys.platform == "win32":
            ctypes.windll.user32.MessageBoxW(0, str(exc), "Oniflow Launcher Error", 0x10)
        raise
