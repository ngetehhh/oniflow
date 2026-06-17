#!/usr/bin/env python3
"""Owner-only desktop utility for creating Oniflow offline licenses."""

from __future__ import annotations

import re
import subprocess
import tkinter as tk
from argparse import Namespace
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from offline_license_admin import DEFAULT_PRIVATE_KEY, create_license


ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "generated-licenses"
DEVICE_ID_RE = re.compile(r"^[0-9A-F]{8}(?:-[0-9A-F]{8}){3}$")


def safe_filename(name: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_-]", "-", name.strip()).strip("-")
    return value or "user"


def validate_device_id(value: str) -> str:
    device_id = value.strip().upper()
    if not DEVICE_ID_RE.fullmatch(device_id):
        raise ValueError("Device ID tidak valid. Gunakan Device ID lengkap yang ditampilkan Oniflow.")
    return device_id


def create_owner_license(device_id: str, name: str, days: int, output: Path) -> Path:
    if days < 0:
        raise ValueError("Masa berlaku tidak boleh negatif.")
    if not DEFAULT_PRIVATE_KEY.is_file():
        raise FileNotFoundError(
            "Private key tidak ditemukan. Jalankan buat_kunci_offline_license.ps1 satu kali."
        )
    args = Namespace(
        private_key=DEFAULT_PRIVATE_KEY,
        device_id=validate_device_id(device_id),
        name=name.strip() or "Oniflow User",
        days=days,
        output=output,
    )
    return create_license(args)


class LicenseMaker:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("Oniflow License Maker")
        root.geometry("620x430")
        root.resizable(False, False)

        self.device_id = tk.StringVar()
        self.name = tk.StringVar(value="Oniflow User")
        self.validity = tk.StringVar(value="Permanent")
        self.custom_days = tk.StringVar(value="30")
        self.output = tk.StringVar()
        self.status = tk.StringVar(value="Siap membuat lisensi.")

        frame = ttk.Frame(root, padding=24)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="ONIFLOW LICENSE MAKER", font=("Segoe UI", 17, "bold")).pack(anchor="w")
        ttk.Label(
            frame,
            text="Alat khusus pemilik. Private key tidak akan dimasukkan ke installer publik.",
        ).pack(anchor="w", pady=(2, 18))

        self._field(frame, "Device ID", self.device_id)
        self._field(frame, "Nama pengguna", self.name)

        validity_row = ttk.Frame(frame)
        validity_row.pack(fill="x", pady=(0, 12))
        ttk.Label(validity_row, text="Masa berlaku", width=18).pack(side="left")
        validity_box = ttk.Combobox(
            validity_row,
            textvariable=self.validity,
            values=["Permanent", "7 days", "30 days", "90 days", "365 days", "Custom"],
            state="readonly",
            width=20,
        )
        validity_box.pack(side="left", fill="x", expand=True)
        validity_box.bind("<<ComboboxSelected>>", lambda _event: self._toggle_custom_days())
        self.days_entry = ttk.Entry(validity_row, textvariable=self.custom_days, width=8, state="disabled")
        self.days_entry.pack(side="left", padx=(8, 0))

        output_row = ttk.Frame(frame)
        output_row.pack(fill="x", pady=(0, 18))
        ttk.Label(output_row, text="Simpan sebagai", width=18).pack(side="left")
        ttk.Entry(output_row, textvariable=self.output).pack(side="left", fill="x", expand=True)
        ttk.Button(output_row, text="Pilih...", command=self._choose_output).pack(side="left", padx=(8, 0))

        actions = ttk.Frame(frame)
        actions.pack(fill="x")
        ttk.Button(actions, text="Buka Folder Lisensi", command=self._open_output_dir).pack(side="left")
        ttk.Button(actions, text="Buat Lisensi", command=self._create).pack(side="right")
        ttk.Label(frame, textvariable=self.status, foreground="#2457a6").pack(anchor="w", pady=(18, 0))

    @staticmethod
    def _field(parent: ttk.Frame, label: str, variable: tk.StringVar) -> None:
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=(0, 12))
        ttk.Label(row, text=label, width=18).pack(side="left")
        ttk.Entry(row, textvariable=variable).pack(side="left", fill="x", expand=True)

    def _toggle_custom_days(self) -> None:
        self.days_entry.configure(state="normal" if self.validity.get() == "Custom" else "disabled")

    def _days(self) -> int:
        presets = {"Permanent": 0, "7 days": 7, "30 days": 30, "90 days": 90, "365 days": 365}
        if self.validity.get() in presets:
            return presets[self.validity.get()]
        return int(self.custom_days.get())

    def _default_output(self) -> Path:
        return OUTPUT_DIR / f"{safe_filename(self.name.get())}-oniflow-license.json"

    def _choose_output(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Simpan Lisensi Oniflow",
            initialdir=OUTPUT_DIR,
            initialfile=self._default_output().name,
            defaultextension=".json",
            filetypes=[("JSON license", "*.json")],
        )
        if path:
            self.output.set(path)

    @staticmethod
    def _open_output_dir() -> None:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["explorer.exe", str(OUTPUT_DIR)])

    def _create(self) -> None:
        try:
            output = Path(self.output.get().strip()) if self.output.get().strip() else self._default_output()
            result = create_owner_license(self.device_id.get(), self.name.get(), self._days(), output)
        except (ValueError, OSError) as exc:
            messagebox.showerror("Gagal Membuat Lisensi", str(exc))
            self.status.set(f"Gagal: {exc}")
            return
        self.output.set(str(result.resolve()))
        self.status.set(f"Lisensi berhasil dibuat: {result.name}")
        messagebox.showinfo("Lisensi Berhasil Dibuat", f"Kirim hanya file ini kepada pengguna:\n\n{result.resolve()}")


def main() -> None:
    root = tk.Tk()
    LicenseMaker(root)
    root.mainloop()


if __name__ == "__main__":
    main()
