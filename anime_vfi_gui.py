#!/usr/bin/env python3
"""Commercial-style desktop interface for Oniflow."""

from __future__ import annotations

import queue
import re
import json
import os
import ctypes
import hashlib
import shutil
import subprocess
import sys
import threading
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import webbrowser
import zipfile
from datetime import date, datetime, timedelta, timezone
from dataclasses import dataclass
from pathlib import Path
from tkinter import PhotoImage, filedialog, messagebox

import customtkinter as ctk
from PIL import Image
from tkinterdnd2 import DND_FILES, TkinterDnD

from anime_vfi import PipelineError, available_backends, backend_label, load_config, probe_video
from offline_license import device_id as offline_device_id, verify_license
from runtime_security import verify_integrity, verify_runtime_access


ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
APP_DATA_ROOT = Path(os.environ.get("LOCALAPPDATA", ROOT)) / "Oniflow"
SETTINGS_PATH = APP_DATA_ROOT / "user_settings.json"
ACCESS_PATH = APP_DATA_ROOT / "access.json"
ACTIVATION_CONFIG_PATH = ROOT / "activation_config.json"
UPDATE_CONFIG_PATH = ROOT / "update_config.json"
OFFLINE_LICENSE_PATH = APP_DATA_ROOT / "license.json"
OFFLINE_PUBLIC_KEY_PATH = ROOT / "assets" / "offline-license-public.json"
LEGACY_SETTINGS_PATH = ROOT / "user_settings.json"
BASE_CONFIG_PATH = ROOT / "config.json"
VIDEO_EXTENSIONS = {".avi", ".m2ts", ".m4v", ".mkv", ".mov", ".mp4", ".ts", ".webm"}
PROGRESS_RE = re.compile(r"VFI_PROGRESS\s+(\d+)\s+(\d+)")
PATCH_ASSET_RE = re.compile(r"^Oniflow-Patch-(?P<from>.+)-to-(?P<to>.+)\.zip$", re.IGNORECASE)
OUTPUT_FORMATS = ["MP4", "MKV", "MOV", "MOV with Alpha"]
DEFAULT_SETTINGS = {
    "video_codec": "AV1",
    "quality_value": "Balanced (CQ 18)",
    "bit_depth": "10-bit",
    "audio_mode": "Keep Audio",
    "preserve_metadata": True,
    "preserve_subtitles": True,
    "scene_protection": True,
    "held_frame_protection": True,
    "scene_threshold": 0.32,
    "static_threshold": 0.002,
    "temp_dir": "",
    "delete_cache": True,
    "mixed_precision": True,
    "uhd_mode": "Auto (Recommended)",
    "open_output": False,
    "notify_complete": True,
    "confirm_exit": True,
    "save_logs": True,
    "auto_check_updates": True,
    "update_check_interval_hours": 24,
    "last_update_check": "",
    "gpu_usage_limit": "100%",
    "default_profile": "Anime",
    "default_backend": "GMFSS",
    "default_multiplier": "2x",
    "default_interpolation_quality": "Normal",
    "default_output_format": "MP4",
    "default_slow_motion": "Off",
}
APP_VERSION = "0.9.11-beta"
UPDATE_REQUEST_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "User-Agent": f"Oniflow/{APP_VERSION}",
}
ACCESS_FEATURE_ENABLED = False
OFFLINE_LICENSE_REQUIRED = True
FREE_DAILY_CLIP_LIMIT = 15
REDEEM_CODE_DAYS = {
    "ONIFLOW-BETA-30D": 30,
}


def version_key(value: str) -> tuple[int, ...]:
    main = value.strip().lower().removeprefix("v").split("-", 1)[0]
    return tuple(int(part) for part in main.split(".") if part.isdigit())


def update_is_newer(latest: str, current: str = APP_VERSION) -> bool:
    return version_key(latest) > version_key(current)


def parse_iso_datetime(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def load_update_config(path: Path = UPDATE_CONFIG_PATH) -> dict[str, str]:
    if not path.is_file():
        return {"manifest_url": "", "release_api_url": "", "channel": "beta"}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        "manifest_url": str(data.get("manifest_url", "")).strip(),
        "release_api_url": str(data.get("release_api_url", "")).strip(),
        "channel": str(data.get("channel", "beta")).strip() or "beta",
    }


def fetch_update_manifest(manifest_url: str, timeout: int = 12) -> dict[str, str]:
    request = urllib.request.Request(manifest_url, headers=UPDATE_REQUEST_HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8-sig"))
    update = {
        "latest_version": str(data["latest_version"]).strip(),
        "download_url": str(data["download_url"]).strip(),
        "sha256": str(data["sha256"]).strip().upper(),
        "release_notes": str(data.get("release_notes", "")).strip(),
    }
    patch = data.get("patch") if isinstance(data.get("patch"), dict) else {}
    if patch:
        update.update({
            "patch_from_version": str(patch.get("from_version", "")).strip(),
            "patch_url": str(patch.get("download_url", "")).strip(),
            "patch_sha256": str(patch.get("sha256", "")).strip().upper(),
        })
        if update["patch_from_version"] == APP_VERSION and update["patch_url"] and update["patch_sha256"]:
            update["update_kind"] = "patch"
    return update


def fetch_github_release_update(release_api_url: str, channel: str = "beta", timeout: int = 12) -> dict[str, str]:
    request = urllib.request.Request(release_api_url, headers=UPDATE_REQUEST_HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        releases = json.loads(response.read().decode("utf-8"))
    allow_prerelease = channel.lower() == "beta"
    for release in releases:
        if release.get("draft"):
            continue
        if release.get("prerelease") and not allow_prerelease:
            continue
        tag = str(release.get("tag_name", "")).strip()
        version = tag.removeprefix("v")
        assets = release.get("assets") or []
        installer = next(
            (
                asset for asset in assets
                if str(asset.get("name", "")).lower().startswith("oniflow-setup-")
                and str(asset.get("name", "")).lower().endswith(".exe")
            ),
            None,
        )
        if not version or not installer:
            continue
        digest = str(installer.get("digest", "")).strip()
        if not digest.lower().startswith("sha256:"):
            continue
        update = {
            "latest_version": version,
            "download_url": str(installer["browser_download_url"]).strip(),
            "sha256": digest.split(":", 1)[1].strip().upper(),
            "release_notes": str(release.get("body", "")).strip(),
        }
        patch = compatible_patch_asset(assets, APP_VERSION, version)
        if patch:
            patch_digest = str(patch.get("digest", "")).strip()
            if patch_digest.lower().startswith("sha256:"):
                update.update({
                    "update_kind": "patch",
                    "patch_from_version": APP_VERSION,
                    "patch_url": str(patch["browser_download_url"]).strip(),
                    "patch_sha256": patch_digest.split(":", 1)[1].strip().upper(),
                })
        return update
    raise RuntimeError("No compatible Oniflow update release was found.")


def compatible_patch_asset(assets: list[dict[str, object]], current_version: str, latest_version: str) -> dict[str, object] | None:
    for asset in assets:
        name = str(asset.get("name", "")).strip()
        match = PATCH_ASSET_RE.match(name)
        if not match:
            continue
        if match.group("from").lower() == current_version.lower() and match.group("to").lower() == latest_version.lower():
            return asset
    return None


def friendly_update_error(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError) and exc.code == 429:
        return (
            "GitHub is temporarily limiting update checks. "
            "Please wait a few minutes, then try Check for Updates again."
        )
    return str(exc)


def download_update_installer(update: dict[str, str], output_dir: Path, progress_callback=None) -> Path:
    return download_update_file(update["download_url"], update["sha256"], output_dir, "Oniflow-Update.exe", progress_callback)


def download_update_patch(update: dict[str, str], output_dir: Path, progress_callback=None) -> Path:
    target = download_update_file(
        update["patch_url"], update["patch_sha256"], output_dir, "Oniflow-Patch.zip", progress_callback
    )
    validate_update_zip(target)
    return target


def download_update_file(
    download_url: str,
    expected_sha256: str,
    output_dir: Path,
    fallback_filename: str,
    progress_callback=None,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = Path(urllib.parse.urlparse(download_url).path).name or fallback_filename
    target = output_dir / filename
    digest = hashlib.sha256()
    with urllib.request.urlopen(download_url, timeout=30) as response, target.open("wb") as handle:
        total = int(response.headers.get("Content-Length") or 0)
        downloaded = 0
        last_report = 0.0
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            handle.write(chunk)
            downloaded += len(chunk)
            now = time.monotonic()
            if progress_callback and (now - last_report >= 0.5 or (total and downloaded >= total)):
                progress_callback(downloaded, total)
                last_report = now
    actual = digest.hexdigest().upper()
    expected = expected_sha256.upper()
    if actual != expected:
        target.unlink(missing_ok=True)
        raise ValueError(f"Downloaded update checksum mismatch. Expected {expected}, got {actual}.")
    return target


def validate_update_zip(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        for member in archive.infolist():
            name = member.filename.replace("\\", "/")
            if not name or name.startswith("/") or name.startswith("../") or "/../" in name:
                raise ValueError(f"Update patch contains an unsafe path: {member.filename}")


def normalize_access_state(state: dict[str, object] | None = None) -> dict[str, object]:
    today = date.today().isoformat()
    normalized = {
        "usage_date": today,
        "clips_used": 0,
        "pro_until": "",
        "redeemed_codes": [],
        "server_token": "",
    }
    if state:
        normalized.update(state)
    if normalized["usage_date"] != today:
        normalized["usage_date"] = today
        normalized["clips_used"] = 0
    normalized["clips_used"] = max(0, int(normalized["clips_used"]))
    normalized["redeemed_codes"] = list(normalized.get("redeemed_codes", []))
    return normalized


def pro_expiry(state: dict[str, object]) -> datetime | None:
    value = str(state.get("pro_until", "")).strip()
    if not value:
        return None
    try:
        expiry = datetime.fromisoformat(value)
        return expiry if expiry.tzinfo else expiry.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def is_pro_access(state: dict[str, object]) -> bool:
    expiry = pro_expiry(state)
    return bool(expiry and expiry > datetime.now(timezone.utc))


def redeem_access_code(state: dict[str, object], code: str) -> tuple[dict[str, object], str]:
    normalized_code = code.strip().upper()
    days = REDEEM_CODE_DAYS.get(normalized_code)
    if not days:
        raise ValueError("The access code is invalid.")
    code_hash = hashlib.sha256(normalized_code.encode("utf-8")).hexdigest()
    redeemed = list(state.get("redeemed_codes", []))
    if code_hash in redeemed:
        raise ValueError("This access code has already been redeemed on this computer.")
    now = datetime.now(timezone.utc)
    current_expiry = pro_expiry(state)
    start = current_expiry if current_expiry and current_expiry > now else now
    expiry = start + timedelta(days=days)
    updated = normalize_access_state(state)
    updated["pro_until"] = expiry.isoformat()
    updated["redeemed_codes"] = [*redeemed, code_hash]
    return updated, expiry.astimezone().strftime("%B %d, %Y")


@dataclass
class QueueItem:
    path: Path
    status: str = "Queued"


def format_output_fps(fps: float) -> str:
    rounded = round(fps)
    if abs(fps - rounded) < 0.001:
        return str(rounded)
    return f"{fps:.3f}".rstrip("0").rstrip(".")


def output_extension(output_format: str) -> str:
    if output_format in {"MOV", "MOV with Alpha"}:
        return "mov"
    return output_format.lower()


def build_output_filename(
    stem: str,
    extension: str,
    input_fps: float,
    multiplier: int,
    slow_motion_factor: int = 1,
) -> str:
    output_fps = input_fps * multiplier / slow_motion_factor
    slow_motion_suffix = "(slowmo)" if slow_motion_factor != 1 else ""
    return f"{stem}_oniflow_{multiplier}x-{format_output_fps(output_fps)}fps{slow_motion_suffix}.{extension}"


class CTkDnD(ctk.CTk, TkinterDnD.DnDWrapper):
    def __init__(self) -> None:
        ctk.CTk.__init__(self)
        TkinterDnD.DnDWrapper.__init__(self)
        self.TkdndVersion = TkinterDnD._require(self)


class AnimeVfiPro:
    def __init__(self, root: CTkDnD) -> None:
        self.root = root
        self.root.title("Oniflow")
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        window_width = min(1180, max(800, screen_width - 40))
        window_height = min(820, max(620, screen_height - 80))
        self.compact_layout = window_height < 760
        self.root.geometry(f"{window_width}x{window_height}")
        self.root.minsize(min(980, window_width), min(680, window_height))
        self.root.configure(bg="#090d18")
        self._apply_window_icon(self.root)
        self.settings = self._load_settings()
        self.access_state = self._load_access_state()
        self.items: list[QueueItem] = []
        self.process_status: list[QueueItem] = []
        self.status_window: ctk.CTkToplevel | None = None
        self.access_window: ctk.CTkToplevel | None = None
        self.license_window: ctk.CTkToplevel | None = None
        self.status_box: ctk.CTkScrollableFrame | None = None
        self.status_total = ctk.StringVar(value="0 videos total")
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.process: subprocess.Popen[str] | None = None
        self.cancelled = False
        self.started_at = 0.0
        self.paused = False
        self.device_caps: dict[str, object] = {}
        self.available_backend_ids = available_backends(load_config(BASE_CONFIG_PATH))
        self.backend_labels = {backend: backend_label(backend) for backend in self.available_backend_ids}
        default_backend_label = str(self.settings.get("default_backend", self.backend_labels[self.available_backend_ids[0]]))
        if default_backend_label not in self.backend_labels.values():
            default_backend_label = self.backend_labels[self.available_backend_ids[0]]
        log_dir = APP_DATA_ROOT / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = log_dir / f"oniflow-{time.strftime('%Y%m%d-%H%M%S')}.log"

        self.mode = ctk.StringVar(value=str(self.settings["default_profile"]))
        self.model_name = ctk.StringVar(value=default_backend_label)
        self.multiplier = ctk.StringVar(value=str(self.settings["default_multiplier"]))
        self.output_dir = ctk.StringVar(value="")
        self.quality = ctk.StringVar(value=str(self.settings["default_interpolation_quality"]))
        self.slow_motion = ctk.StringVar(value=str(self.settings["default_slow_motion"]))
        self.output_format = ctk.StringVar(value=str(self.settings["default_output_format"]))
        self.status = ctk.StringVar(value="Ready for video")
        self.gpu = ctk.StringVar(value="Detecting GPU...")
        self.progress_text = ctk.StringVar(value="0%")
        self.eta_text = ctk.StringVar(value="ETA --:--")
        self.access_summary = ctk.StringVar(value="")
        if ACCESS_FEATURE_ENABLED:
            self._update_access_summary()
        self._build()
        self.root.after(300, self._ensure_offline_license)
        self.root.after(50, self._register_main_drop_targets)
        self.root.after(250, lambda: threading.Thread(target=self._startup_device_check, daemon=True).start())
        self.root.after(200, self._lock_window_resize)
        self.mode.trace_add("write", self._mode_changed)
        self.model_name.trace_add("write", self._mode_changed)
        self.root.after(100, self._poll_events)
        self.root.after(1000, self._start_gpu_update)
        self.root.after(6000, self._maybe_auto_check_for_updates)
        self.root.protocol("WM_DELETE_WINDOW", self._close)

    def _ensure_offline_license(self) -> None:
        if not OFFLINE_LICENSE_REQUIRED:
            return
        integrity_ok, integrity_message = verify_integrity(
            ROOT, require_manifest=(ROOT / "integrity-manifest.json").is_file()
        )
        if not integrity_ok:
            self._log(f"Security check failed: {integrity_message}")
            self._open_offline_license_window(integrity_message)
            return
        valid, message, payload = verify_license(
            OFFLINE_LICENSE_PATH,
            OFFLINE_PUBLIC_KEY_PATH,
            offline_device_id(),
        )
        if valid:
            licensed_to = str(payload.get("licensed_to", "Oniflow User"))
            self._log(f"Offline license verified for {licensed_to}.")
            return
        self._log(f"Offline license required: {message}")
        self._open_offline_license_window(message)

    def _open_offline_license_window(self, reason: str) -> None:
        if self.license_window and self.license_window.winfo_exists():
            self.license_window.focus_force()
            return
        window = ctk.CTkToplevel(self.root)
        self.license_window = window
        window.title("Oniflow Offline License")
        self._apply_window_icon(window)
        window.geometry("620x440")
        window.resizable(False, False)
        window.configure(fg_color="#090d18")
        window.transient(self.root)
        window.grab_set()
        window.protocol("WM_DELETE_WINDOW", self.root.destroy)

        card = ctk.CTkFrame(window, fg_color="#101728", corner_radius=14, border_width=1, border_color="#263552")
        card.pack(fill="both", expand=True, padx=22, pady=22)
        ctk.CTkLabel(
            card, text="OFFLINE LICENSE REQUIRED", font=("Segoe UI", 20, "bold"), text_color="#f8fafc"
        ).pack(anchor="w", padx=22, pady=(22, 4))
        ctk.CTkLabel(
            card,
            text="Send this Device ID to the Oniflow owner. Import the license file created for this computer.",
            font=("Segoe UI", 11),
            text_color="#94a3b8",
            justify="left",
            wraplength=530,
        ).pack(anchor="w", padx=22, pady=(0, 18))
        ctk.CTkLabel(card, text="DEVICE ID", font=("Segoe UI", 11, "bold"), text_color="#64748b").pack(
            anchor="w", padx=22
        )
        device_value = ctk.StringVar(value=offline_device_id())
        ctk.CTkEntry(
            card,
            textvariable=device_value,
            state="readonly",
            fg_color="#162238",
            border_color="#263552",
            text_color="#e2e8f0",
            height=38,
        ).pack(fill="x", padx=22, pady=(5, 10))
        ctk.CTkButton(
            card,
            text="Copy Device ID",
            width=130,
            fg_color="#273449",
            hover_color="#334155",
            command=lambda: self._copy_device_id(device_value.get()),
        ).pack(anchor="w", padx=22)
        ctk.CTkLabel(
            card,
            text=reason,
            font=("Segoe UI", 11),
            text_color="#f87171",
            justify="left",
            wraplength=530,
        ).pack(anchor="w", padx=22, pady=(20, 12))
        actions = ctk.CTkFrame(card, fg_color="transparent")
        actions.pack(fill="x", padx=22, pady=(0, 20))
        ctk.CTkButton(
            actions, text="Exit", width=100, fg_color="#7f1d1d", hover_color="#991b1b", command=self.root.destroy
        ).pack(side="right")
        ctk.CTkButton(
            actions, text="Import License", width=150, command=lambda: self._import_offline_license(window)
        ).pack(side="right", padx=(0, 10))

    def _copy_device_id(self, value: str) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(value)
        self.root.update()

    def _import_offline_license(self, window: ctk.CTkToplevel) -> None:
        selected = filedialog.askopenfilename(
            title="Import Oniflow Offline License",
            filetypes=[("Oniflow License", "*.json"), ("All Files", "*.*")],
            parent=window,
        )
        if not selected:
            return
        valid, message, payload = verify_license(Path(selected), OFFLINE_PUBLIC_KEY_PATH, offline_device_id())
        if not valid:
            messagebox.showerror("Offline License", message, parent=window)
            return
        APP_DATA_ROOT.mkdir(parents=True, exist_ok=True)
        temporary = OFFLINE_LICENSE_PATH.with_suffix(".tmp")
        shutil.copyfile(selected, temporary)
        temporary.replace(OFFLINE_LICENSE_PATH)
        self._log(f"Offline license imported for {payload.get('licensed_to', 'Oniflow User')}.")
        messagebox.showinfo("Offline License", "License activated successfully.", parent=window)
        window.grab_release()
        window.destroy()
        self.license_window = None

    @staticmethod
    def _apply_window_icon(window: ctk.CTk | ctk.CTkToplevel) -> None:
        logo_path = ROOT / "assets" / "oniflow-logo.png"
        icon_path = ROOT / "assets" / "oniflow.ico"
        icon_refs = getattr(window, "_oniflow_icon_refs", [])
        window._oniflow_icon_refs = icon_refs  # type: ignore[attr-defined]

        def apply_icon() -> None:
            if icon_path.is_file():
                try:
                    window.iconbitmap(str(icon_path))
                except Exception:
                    pass
            if logo_path.is_file():
                try:
                    # Apply per window and as the default for child dialogs.
                    icon = PhotoImage(file=str(logo_path))
                    window.iconphoto(False, icon)
                    window.iconphoto(True, icon)
                    icon_refs.append(icon)
                except Exception:
                    pass

        apply_icon()
        window.after(50, apply_icon)
        window.after(250, apply_icon)

    def _register_main_drop_targets(self) -> None:
        """Allow video and folder drops anywhere in the main window."""
        pending = [self.root]
        while pending:
            widget = pending.pop()
            pending.extend(widget.winfo_children())
            try:
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<Drop>>", self.handle_drop)
            except Exception:
                continue

    @staticmethod
    def _save_settings_file(settings: dict[str, object]) -> None:
        APP_DATA_ROOT.mkdir(parents=True, exist_ok=True)
        temporary = SETTINGS_PATH.with_suffix(".tmp")
        temporary.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        temporary.replace(SETTINGS_PATH)

    def _lock_window_resize(self) -> None:
        """Disable drag-resizing on Windows while keeping minimize and maximize."""
        if sys.platform != "win32":
            return
        try:
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            get_style = ctypes.windll.user32.GetWindowLongW
            set_style = ctypes.windll.user32.SetWindowLongW
            style = get_style(hwnd, -16)
            ws_thickframe = 0x00040000
            ws_minimizebox = 0x00020000
            ws_maximizebox = 0x00010000
            style = (style & ~ws_thickframe) | ws_minimizebox | ws_maximizebox
            set_style(hwnd, -16, style)
            ctypes.windll.user32.SetWindowPos(
                hwnd, 0, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004 | 0x0020
            )
        except Exception as exc:
            self._log(f"Window resize lock unavailable: {exc}")

    def _build(self) -> None:
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        shell = ctk.CTkFrame(self.root, fg_color="#090d18", corner_radius=0)
        shell.pack(fill="both", expand=True)
        shell.grid_columnconfigure(0, weight=1)
        shell.grid_rowconfigure(1, weight=1)

        header_height = 70 if self.compact_layout else 82
        header = ctk.CTkFrame(shell, fg_color="#101728", corner_radius=0, height=header_height)
        header.grid(row=0, column=0, sticky="ew")
        header.pack_propagate(False)
        logo_path = ROOT / "assets" / "oniflow-logo.png"
        if logo_path.is_file():
            self.brand_logo = ctk.CTkImage(Image.open(logo_path), size=(52, 52))
            ctk.CTkLabel(header, text="", image=self.brand_logo).pack(
                side="left", padx=(24, 8), pady=14
            )
        ctk.CTkLabel(header, text="ONIFLOW", font=("Segoe UI", 25, "bold"), text_color="#f8fafc").pack(
            side="left", padx=(0, 8) if logo_path.is_file() else (26, 8), pady=20
        )
        ctk.CTkLabel(
            header, text=f"v{APP_VERSION}", font=("Segoe UI", 11, "bold"), text_color="#64748b"
        ).pack(
            side="left", padx=(0, 22), pady=27
        )
        ctk.CTkLabel(
            header, text="AI VIDEO INTERPOLATION", font=("Segoe UI", 11, "bold"), text_color="#38bdf8"
        ).pack(side="left", pady=27)
        creator_link = ctk.CTkLabel(
            header, text="by Oniven", font=("Segoe UI", 11, "bold"), text_color="#94a3b8", cursor="hand2"
        )
        creator_link.pack(side="left", padx=(12, 0), pady=27)
        creator_link.bind("<Button-1>", lambda _event: webbrowser.open("https://www.instagram.com/oniven.tt/"))
        ctk.CTkLabel(header, textvariable=self.gpu, font=("Segoe UI", 12), text_color="#94a3b8").pack(
            side="right", padx=26
        )
        ctk.CTkButton(
            header, text="Settings", width=92, fg_color="#273449", hover_color="#334155", command=self.open_settings
        ).pack(side="right")
        if ACCESS_FEATURE_ENABLED:
            ctk.CTkButton(
                header,
                textvariable=self.access_summary,
                width=112,
                fg_color="#7f1d1d",
                hover_color="#991b1b",
                border_width=1,
                border_color="#ef4444",
                command=self.open_access,
            ).pack(side="right", padx=(0, 8))

        body = ctk.CTkFrame(shell, fg_color="#090d18", corner_radius=0)
        body.grid(row=1, column=0, sticky="nsew", padx=20, pady=14)
        self.body = body
        body.grid_columnconfigure(0, weight=7)
        body.grid_columnconfigure(1, weight=3)
        body.grid_rowconfigure(1, weight=3, minsize=220 if self.compact_layout else 270)
        body.grid_rowconfigure(2, weight=1, minsize=95 if self.compact_layout else 105)

        drop_height = 72 if self.compact_layout else 92
        self.drop = ctk.CTkFrame(
            body, fg_color="#111a2e", border_color="#2563eb", border_width=1, height=drop_height
        )
        self.drop.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 14))
        self.drop.grid_propagate(False)
        drop_label = ctk.CTkLabel(
            self.drop,
            text="DROP VIDEO OR FOLDER HERE",
            font=("Segoe UI", 18, "bold"),
            text_color="#e2e8f0",
        )
        drop_label.pack(pady=(7 if self.compact_layout else 14, 2))
        ctk.CTkLabel(
            self.drop,
            text="Supports MKV, MP4, MOV, WebM, AVI, TS",
            font=("Segoe UI", 12),
            text_color="#64748b",
        ).pack()
        for widget in (self.drop, drop_label):
            widget.bind("<Button-1>", lambda _event: self.choose_files())
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self.handle_drop)

        self.log_panel = ctk.CTkFrame(
            body, fg_color="#0e1525", corner_radius=12, border_width=1, border_color="#18243a"
        )
        self.log_panel.grid(row=1, column=0, sticky="nsew", padx=(0, 12))
        log_header = ctk.CTkFrame(self.log_panel, fg_color="transparent")
        log_header.pack(fill="x", padx=12, pady=(10, 5))
        ctk.CTkLabel(
            log_header, text="PROCESS LOG", font=("Segoe UI", 13, "bold"), text_color="#cbd5e1"
        ).pack(side="left", padx=4)
        ctk.CTkButton(
            log_header, text="Open Logs", width=78, height=26, fg_color="#273449", hover_color="#334155",
            command=lambda: os.startfile(APP_DATA_ROOT / "logs"),
        ).pack(side="right")
        self.log = ctk.CTkTextbox(
            self.log_panel, fg_color="#070b14", text_color="#94a3b8", font=("Consolas", 10)
        )
        self.log.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        right = ctk.CTkFrame(body, fg_color="#0e1525", corner_radius=12, border_width=1, border_color="#18243a")
        right.grid(row=1, column=1, sticky="nsew")
        self._settings(right)

        queue_panel = ctk.CTkFrame(body, fg_color="#0e1525", corner_radius=12, border_width=1, border_color="#18243a")
        queue_panel.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(12, 0))
        queue_header = ctk.CTkFrame(queue_panel, fg_color="transparent", height=42)
        queue_header.pack(fill="x", padx=14, pady=(3, 3))
        queue_header.pack_propagate(False)
        queue_header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            queue_header, text="PROCESS QUEUE", font=("Segoe UI", 12, "bold"), text_color="#cbd5e1"
        ).grid(row=0, column=0, sticky="w")
        queue_actions = ctk.CTkFrame(queue_header, fg_color="transparent")
        queue_actions.grid(row=0, column=1, sticky="e")
        queue_button_height = 34
        ctk.CTkButton(
            queue_actions,
            text="Clear Queue",
            width=100,
            height=queue_button_height,
            fg_color="#273449",
            hover_color="#334155",
            command=self.clear_files,
        ).pack(side="left")
        ctk.CTkButton(
            queue_actions,
            text="Process Status",
            width=110,
            height=queue_button_height,
            fg_color="#273449",
            hover_color="#334155",
            command=self.open_process_status,
        ).pack(side="left", padx=(8, 0))
        ctk.CTkButton(
            queue_actions,
            text="Add Video",
            width=100,
            height=queue_button_height,
            command=self.choose_files,
        ).pack(side="left", padx=(8, 0))
        self.queue_box = ctk.CTkScrollableFrame(
            queue_panel,
            fg_color="#0b1120",
            height=32,
            orientation="horizontal",
            scrollbar_fg_color="#0b1120",
            scrollbar_button_color="#1d5f8c",
            scrollbar_button_hover_color="#38bdf8",
        )
        self.queue_box.pack(fill="both", expand=True, padx=12, pady=(0, 5))
        self._log("Oniflow is ready.")

        bottom = ctk.CTkFrame(shell, fg_color="#101728", corner_radius=0, height=95 if self.compact_layout else 105)
        bottom.grid(row=2, column=0, sticky="ew")
        bottom.pack_propagate(False)
        self.progress = ctk.CTkProgressBar(
            bottom,
            height=12,
            corner_radius=6,
            fg_color="#162238",
            progress_color="#38bdf8",
            border_width=1,
            border_color="#263552",
        )
        self.progress.set(0)
        self.progress.pack(fill="x", padx=22, pady=(14, 5))
        info = ctk.CTkFrame(bottom, fg_color="transparent")
        info.pack(fill="x", padx=22)
        ctk.CTkLabel(info, textvariable=self.status, text_color="#cbd5e1").pack(side="left")
        ctk.CTkLabel(info, textvariable=self.eta_text, text_color="#94a3b8").pack(side="right", padx=12)
        ctk.CTkLabel(info, textvariable=self.progress_text, text_color="#38bdf8", font=("Segoe UI", 12, "bold")).pack(
            side="right"
        )
        controls = ctk.CTkFrame(bottom, fg_color="transparent")
        controls.pack(fill="x", padx=22, pady=(7, 14))
        self.cancel_button = ctk.CTkButton(
            controls, text="Stop", width=110, fg_color="#7f1d1d", hover_color="#991b1b", command=self.cancel, state="disabled"
        )
        self.cancel_button.pack(side="right")
        self.pause_button = ctk.CTkButton(
            controls, text="Pause", width=90, fg_color="#92400e", hover_color="#b45309",
            command=self.toggle_pause, state="disabled",
        )
        self.pause_button.pack(side="right", padx=(0, 8))
        self.start_button = ctk.CTkButton(
            controls, text="START INTERPOLATION", width=210, fg_color="#2563eb", hover_color="#1d4ed8", command=self.start
        )
        self.start_button.pack(side="right", padx=8)

    def _settings(self, parent: ctk.CTkFrame) -> None:
        ctk.CTkLabel(parent, text="JOB CONFIGURATION", font=("Segoe UI", 14, "bold"), text_color="#f8fafc").pack(
            anchor="w", padx=16, pady=(12, 8)
        )
        profile_card = ctk.CTkFrame(parent, fg_color="#111a2e", corner_radius=9)
        profile_card.pack(fill="x", padx=12, pady=(0, 6))
        ctk.CTkLabel(profile_card, text="INTERPOLATION PROFILE", font=("Segoe UI", 11, "bold"), text_color="#64748b").pack(
            anchor="w", padx=12, pady=(7, 4)
        )
        tabs = ctk.CTkSegmentedButton(
            profile_card,
            values=["Anime", "Human"],
            variable=self.mode,
            height=28,
            fg_color="#1b2940",
            selected_color="#287bb5",
            selected_hover_color="#3292d0",
            unselected_color="#1b2940",
            unselected_hover_color="#273b59",
        )
        tabs.pack(fill="x", padx=12, pady=(0, 3))
        self._field(profile_card, "Model", variable=self.model_name, options=list(self.backend_labels.values()), compact=True)

        interpolation_row = ctk.CTkFrame(profile_card, fg_color="transparent")
        interpolation_row.pack(fill="x", padx=8, pady=(0, 6))
        interpolation_row.grid_columnconfigure((0, 1), weight=1, uniform="interpolation_fields")
        multiplier_field = ctk.CTkFrame(interpolation_row, fg_color="transparent")
        multiplier_field.grid(row=0, column=0, sticky="ew")
        quality_field = ctk.CTkFrame(interpolation_row, fg_color="transparent")
        quality_field.grid(row=0, column=1, sticky="ew")
        self._field(
            multiplier_field, "FPS Multiplier", variable=self.multiplier,
            options=["2x", "4x", "6x", "8x", "10x"], compact=True,
        )
        self._field(
            quality_field, "Interpolation Quality", variable=self.quality,
            options=["Fast", "Normal", "Quality"], compact=True,
        )

        output_card = ctk.CTkFrame(parent, fg_color="#111a2e", corner_radius=9)
        output_card.pack(fill="x", padx=12, pady=(0, 6))
        output_grid = ctk.CTkFrame(output_card, fg_color="transparent")
        output_grid.pack(fill="x", padx=8, pady=(0, 5))
        output_grid.grid_columnconfigure(0, weight=1, uniform="output_fields")
        output_grid.grid_columnconfigure(1, weight=1, uniform="output_fields")
        output_grid.grid_columnconfigure(2, weight=3, uniform="output_fields")

        format_field = ctk.CTkFrame(output_grid, fg_color="transparent")
        format_field.grid(row=0, column=0, sticky="ew")
        self._field(format_field, "Output Format", variable=self.output_format, options=OUTPUT_FORMATS, compact=True)

        playback_field = ctk.CTkFrame(output_grid, fg_color="transparent")
        playback_field.grid(row=0, column=1, sticky="ew")
        self._field(
            playback_field,
            "Slow Motion",
            variable=self.slow_motion,
            options=["Off", "2x", "4x", "6x", "8x", "10x"],
            compact=True,
        )

        directory_field = ctk.CTkFrame(output_grid, fg_color="transparent")
        directory_field.grid(row=0, column=2, sticky="ew")
        ctk.CTkLabel(directory_field, text="OUTPUT DIRECTORY", font=("Segoe UI", 11, "bold"), text_color="#64748b").pack(
            anchor="w", padx=8, pady=(4, 2)
        )
        output_row = ctk.CTkFrame(directory_field, fg_color="transparent")
        output_row.pack(fill="x", padx=8)
        ctk.CTkEntry(
            output_row,
            textvariable=self.output_dir,
            fg_color="#162238",
            border_color="#263552",
            text_color="#e2e8f0",
        ).pack(side="left", fill="x", expand=True)
        ctk.CTkButton(output_row, text="...", width=38, command=self.choose_output).pack(side="left", padx=(7, 0))

    def open_settings(self) -> None:
        window = ctk.CTkToplevel(self.root)
        window.title("Oniflow Settings")
        self._apply_window_icon(window)
        window.geometry("820x700")
        window.minsize(720, 600)
        window.configure(fg_color="#090d18")
        window.transient(self.root)
        window.grab_set()
        settings_header = ctk.CTkFrame(window, fg_color="#101728", corner_radius=12, height=76)
        settings_header.pack(fill="x", padx=16, pady=(16, 0))
        settings_header.pack_propagate(False)
        ctk.CTkLabel(
            settings_header, text="SETTINGS", font=("Segoe UI", 20, "bold"), text_color="#f8fafc"
        ).pack(anchor="w", padx=18, pady=(14, 0))
        ctk.CTkLabel(
            settings_header, text="Configure output, interpolation protection, and application behavior.",
            font=("Segoe UI", 11), text_color="#64748b",
        ).pack(anchor="w", padx=18)
        tabs = ctk.CTkTabview(
            window,
            fg_color="#0e1525",
            border_width=1,
            border_color="#18243a",
            segmented_button_fg_color="#1b2940",
            segmented_button_selected_color="#287bb5",
            segmented_button_selected_hover_color="#3292d0",
            segmented_button_unselected_color="#1b2940",
            segmented_button_unselected_hover_color="#273b59",
            text_color="#e2e8f0",
        )
        tabs.pack(fill="both", expand=True, padx=16, pady=(12, 10))
        variables: dict[str, ctk.Variable] = {}
        tab_content: dict[str, ctk.CTkScrollableFrame] = {}

        def option(tab: str, key: str, label: str, values: list[str]) -> None:
            frame = tab_content[tab]
            ctk.CTkLabel(frame, text=label, anchor="w").pack(fill="x", padx=14, pady=(12, 4))
            var = ctk.StringVar(value=str(self.settings[key]))
            variables[key] = var
            ctk.CTkOptionMenu(
                frame,
                variable=var,
                values=values,
                fg_color="#287bb5",
                button_color="#1d5f8c",
                button_hover_color="#3292d0",
                dropdown_fg_color="#162238",
                dropdown_hover_color="#273b59",
                text_color="#f1f5f9",
            ).pack(fill="x", padx=14)

        def entry(tab: str, key: str, label: str) -> None:
            frame = tab_content[tab]
            ctk.CTkLabel(frame, text=label, anchor="w").pack(fill="x", padx=14, pady=(12, 4))
            var = ctk.StringVar(value=str(self.settings[key]))
            variables[key] = var
            ctk.CTkEntry(
                frame,
                textvariable=var,
                fg_color="#162238",
                border_color="#263552",
                text_color="#e2e8f0",
            ).pack(fill="x", padx=14)

        def toggle(tab: str, key: str, label: str) -> None:
            var = ctk.BooleanVar(value=bool(self.settings[key]))
            variables[key] = var
            ctk.CTkSwitch(
                tab_content[tab],
                text=label,
                variable=var,
                fg_color="#1b2940",
                progress_color="#287bb5",
                button_color="#dbeafe",
                button_hover_color="#ffffff",
            ).pack(anchor="w", padx=14, pady=9)

        def guide(tab: str, title: str, text: str) -> None:
            card = ctk.CTkFrame(tab_content[tab], fg_color="#111a2e", border_width=1, border_color="#263552")
            card.pack(fill="x", padx=14, pady=(12, 4))
            ctk.CTkLabel(card, text=title, font=("Segoe UI", 12, "bold"), text_color="#38bdf8").pack(
                anchor="w", padx=12, pady=(9, 2)
            )
            ctk.CTkLabel(card, text=text, text_color="#b6c2d2", wraplength=620, justify="left").pack(
                anchor="w", padx=12, pady=(0, 10)
            )

        for name in ("Job Defaults", "Video Output", "Interpolation", "Performance", "Application", "Advanced"):
            tabs.add(name)
            tabs.tab(name).configure(fg_color="#0e1525")
            content = ctk.CTkScrollableFrame(
                tabs.tab(name),
                fg_color="#0b1120",
                corner_radius=8,
                scrollbar_button_color="#334155",
                scrollbar_button_hover_color="#475569",
            )
            content.pack(fill="both", expand=True, padx=4, pady=4)
            tab_content[name] = content

        option("Job Defaults", "default_profile", "Default Profile", ["Anime", "Human"])
        option("Job Defaults", "default_backend", "Default Model", list(self.backend_labels.values()))
        option("Job Defaults", "default_multiplier", "Default FPS Multiplier", ["2x", "4x", "6x", "8x", "10x"])
        option(
            "Job Defaults",
            "default_interpolation_quality",
            "Default Interpolation Quality",
            ["Fast", "Normal", "Quality"],
        )
        option("Job Defaults", "default_output_format", "Default Output Format", OUTPUT_FORMATS)
        option(
            "Job Defaults",
            "default_slow_motion",
            "Default Slow Motion",
            ["Off", "2x", "4x", "6x", "8x", "10x"],
        )
        guide(
            "Job Defaults",
            "How job defaults work",
            "These values are loaded into Job Configuration when Oniflow starts. Saving changes also applies "
            "them to the current job. You can still change each value from the main window at any time. "
            "Output Directory remains automatic and follows the first added video or folder.",
        )

        option("Video Output", "video_codec", "Video Codec", ["AV1", "HEVC", "H.264"])
        option(
            "Video Output",
            "quality_value",
            "Encoding Quality",
            ["High Quality (CQ 14)", "Balanced (CQ 18)", "Small File (CQ 23)"],
        )
        option("Video Output", "bit_depth", "Bit Depth", ["8-bit", "10-bit"])
        option("Video Output", "audio_mode", "Audio", ["Keep Audio", "Mute Audio"])
        toggle("Video Output", "preserve_metadata", "Preserve metadata")
        toggle("Video Output", "preserve_subtitles", "Preserve subtitles for MKV")
        guide(
            "Video Output",
            "How output settings work",
            "Output Format selects the file container. Video Codec controls compatibility and compression. "
            "Encoding Quality controls output detail and file size. It does not change AI interpolation accuracy. "
            "MOV exports ProRes 422 HQ for editing workflows. MOV with Alpha exports ProRes 4444 for compositing workflows.",
        )
        guide(
            "Video Output",
            "Recommended combinations",
            "Best Quality: AV1 + High Quality (CQ 14) + 10-bit\n"
            "Recommended: AV1 + Balanced (CQ 18) + 10-bit\n"
            "Fast and Compatible: H.264 + Balanced (CQ 18) + 8-bit\n"
            "Small File: AV1 + Small File (CQ 23) + 10-bit",
        )
        guide(
            "Video Output",
            "Audio handling",
            "Keep Audio copies the original audio without quality loss. If the source audio is not compatible "
            "with MP4, Oniflow automatically converts it to AAC. Mute Audio removes audio completely.",
        )

        toggle("Interpolation", "scene_protection", "Enable scene-change protection")
        toggle("Interpolation", "held_frame_protection", "Enable held-frame protection")
        entry("Interpolation", "scene_threshold", "Scene-change threshold")
        entry("Interpolation", "static_threshold", "Held-frame threshold")
        guide(
            "Interpolation",
            "Interpolation Quality",
            "Fast is the quickest and uses less VRAM. Normal provides the best balance. "
            "Quality calculates motion at full scale for the highest accuracy.",
        )
        guide(
            "Interpolation",
            "Protection guide",
            "Keep Scene-Change Protection enabled to prevent mixed frames between cuts. "
            "Keep Held-Frame Protection enabled for anime and static shots. "
            "Only adjust thresholds when default protection incorrectly skips real motion.",
        )
        guide(
            "Interpolation",
            "Threshold reference",
            "Frame difference <= Held-Frame Threshold: repeat the original frame.\n"
            "Difference between both thresholds: run AI interpolation.\n"
            "Frame difference >= Scene-Change Threshold: protect the cut and do not blend frames.\n\n"
            "Lower Scene-Change Threshold: detects more cuts, but may skip fast motion.\n"
            "Higher Scene-Change Threshold: detects fewer cuts, but may blend scene changes.\n"
            "Higher Held-Frame Threshold: treats more subtle motion as static.\n"
            "Recommended defaults: Scene 0.32, Held Frame 0.002.",
        )
        performance_frame = tab_content["Performance"]
        ctk.CTkLabel(performance_frame, text="Temporary Cache Folder", anchor="w").pack(
            fill="x", padx=14, pady=(12, 4)
        )
        temp_var = ctk.StringVar(value=str(self.settings["temp_dir"]))
        variables["temp_dir"] = temp_var
        temp_row = ctk.CTkFrame(performance_frame, fg_color="transparent")
        temp_row.pack(fill="x", padx=14)
        ctk.CTkEntry(
            temp_row,
            textvariable=temp_var,
            state="disabled",
            fg_color="#162238",
            border_color="#263552",
            text_color="#e2e8f0",
        ).pack(side="left", fill="x", expand=True)

        def browse_temp() -> None:
            selected = filedialog.askdirectory(
                title="Select Temporary Cache Folder",
                initialdir=temp_var.get() or str(ROOT),
                parent=window,
            )
            if selected:
                temp_var.set(selected)

        ctk.CTkButton(temp_row, text="Browse", width=72, command=browse_temp).pack(side="left", padx=(7, 0))
        ctk.CTkButton(temp_row, text="Clear", width=58, fg_color="#475569", command=lambda: temp_var.set("")).pack(
            side="left", padx=(7, 0)
        )
        ctk.CTkLabel(
            performance_frame,
            text="Leave empty to use the automatic Windows temporary folder.",
            text_color="#94a3b8",
            anchor="w",
        ).pack(fill="x", padx=14, pady=(4, 2))
        toggle("Performance", "delete_cache", "Delete cache after completion")
        toggle("Performance", "mixed_precision", "Enable mixed precision acceleration")
        option(
            "Performance",
            "uhd_mode",
            "4K Processing Mode",
            ["Auto (Recommended)", "Full Resolution", "Memory Saver"],
        )
        option("Performance", "gpu_usage_limit", "GPU Usage Limit", ["100%", "80%", "60%", "40%"])
        ctk.CTkLabel(
            tab_content["Performance"],
            text="The active GPU is selected automatically. Queue items run one at a time to keep VRAM usage stable.",
            text_color="#94a3b8",
            wraplength=620,
            justify="left",
        ).pack(anchor="w", padx=14, pady=16)
        guide(
            "Performance",
            "Performance presets",
            "Use Fast on lower-VRAM GPUs. Use Normal for most RTX GPUs. Use Quality when output accuracy matters most.",
        )
        guide(
            "Performance",
            "Mixed precision acceleration",
            "Keep mixed precision enabled on RTX GPUs for faster interpolation and lower VRAM usage. "
            "Disable it only when an older GPU produces errors or corrupted frames.",
        )
        guide(
            "Performance",
            "4K processing",
            "Auto protects 4K jobs from VRAM errors while preserving full output resolution. "
            "Full Resolution calculates motion at the selected quality scale and requires more VRAM. "
            "Memory Saver uses a reduced motion scale for difficult videos. Output resolution does not change.",
        )
        guide(
            "Performance",
            "GPU usage limit",
            "Lower limits add a short delay between processed frames. This keeps the computer more responsive, "
            "but increases total processing time.",
        )

        toggle("Application", "open_output", "Open output folder after completion")
        toggle("Application", "notify_complete", "Show completion notification")
        toggle("Application", "confirm_exit", "Confirm before closing during processing")
        toggle("Application", "save_logs", "Save process logs")
        toggle("Application", "auto_check_updates", "Check for updates automatically")
        creator_card = ctk.CTkFrame(
            tab_content["Application"], fg_color="#111a2e", border_width=1, border_color="#263552"
        )
        creator_card.pack(fill="x", padx=14, pady=(18, 8))
        ctk.CTkLabel(
            creator_card, text="CREATOR", font=("Segoe UI", 12, "bold"), text_color="#38bdf8"
        ).pack(anchor="w", padx=14, pady=(12, 2))
        ctk.CTkLabel(
            creator_card,
            text="Created by Oniven. Follow the creator or send suggestions through email.",
            text_color="#b6c2d2",
            wraplength=620,
            justify="left",
        ).pack(anchor="w", padx=14, pady=(0, 10))
        creator_actions = ctk.CTkFrame(creator_card, fg_color="transparent")
        creator_actions.pack(fill="x", padx=14, pady=(0, 12))
        ctk.CTkButton(
            creator_actions,
            text="TikTok @oniven",
            command=lambda: webbrowser.open("https://www.tiktok.com/@oniven"),
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            creator_actions,
            text="Instagram @oniven.tt",
            command=lambda: webbrowser.open("https://www.instagram.com/oniven.tt/"),
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            creator_actions,
            text="Email Suggestions",
            fg_color="#475569",
            hover_color="#64748b",
            command=lambda: webbrowser.open("mailto:oniven1507@gmail.com?subject=Oniflow%20Suggestion"),
        ).pack(side="left")

        ctk.CTkLabel(
            tab_content["Advanced"],
            text=f"Oniflow {APP_VERSION}\nDevice compatibility is checked automatically at startup. "
            "Technical logs are stored in the logs folder.",
            text_color="#94a3b8",
            wraplength=620,
            justify="left",
        ).pack(anchor="w", padx=14, pady=18)
        ctk.CTkButton(
            tab_content["Advanced"], text="Open Help", command=lambda: os.startfile(ROOT / "HELP.md")
        ).pack(anchor="w", padx=14, pady=8)
        ctk.CTkButton(
            tab_content["Advanced"], text="Open Third-Party Notices",
            command=lambda: os.startfile(ROOT / "THIRD_PARTY_NOTICES.md"),
        ).pack(anchor="w", padx=14, pady=8)
        ctk.CTkButton(
            tab_content["Advanced"],
            text="Check for Updates",
            fg_color="#287bb5",
            hover_color="#3292d0",
            command=lambda: self.check_for_updates(window),
        ).pack(anchor="w", padx=14, pady=8)

        def save() -> None:
            try:
                updated = dict(self.settings)
                for key, var in variables.items():
                    value = var.get()
                    if key in {"scene_threshold", "static_threshold"}:
                        value = float(value)
                    updated[key] = value
                scene_threshold = float(updated["scene_threshold"])
                static_threshold = float(updated["static_threshold"])
                if not 0 < scene_threshold <= 1:
                    raise ValueError("Scene-change threshold must be greater than 0 and no higher than 1.")
                if not 0 <= static_threshold < scene_threshold:
                    raise ValueError("Held-frame threshold must be lower than the scene-change threshold.")
                self.settings = updated
                self._save_settings_file(self.settings)
                self._apply_job_defaults()
                self._log("Settings saved.")
                window.destroy()
            except ValueError as exc:
                messagebox.showerror("Settings", str(exc) or "Threshold values must be valid numbers.", parent=window)
            except OSError as exc:
                messagebox.showerror("Settings", f"Oniflow could not save the settings.\n\n{exc}", parent=window)

        actions = ctk.CTkFrame(window, fg_color="#101728", corner_radius=10)
        actions.pack(fill="x", padx=16, pady=(0, 16))
        ctk.CTkButton(actions, text="Save Changes", width=130, command=save).pack(side="right", padx=(8, 12), pady=10)
        ctk.CTkButton(
            actions, text="Reset", fg_color="#475569", command=lambda: self._reset_settings(window)
        ).pack(side="right", pady=10)

    def open_access(self) -> None:
        if not ACCESS_FEATURE_ENABLED:
            return
        if self.access_window and self.access_window.winfo_exists():
            self.access_window.focus()
            return
        try:
            self._sync_server_access()
        except (ValueError, OSError) as exc:
            self._log(f"Activation server status unavailable: {exc}")
        self.access_state = normalize_access_state(self.access_state)
        self._save_access_state()
        pro_active = is_pro_access(self.access_state)
        clips_used = int(self.access_state["clips_used"])
        clips_available = max(0, FREE_DAILY_CLIP_LIMIT - clips_used)
        expiry = pro_expiry(self.access_state)
        window = ctk.CTkToplevel(self.root)
        self.access_window = window
        window.title("Oniflow Access & Subscription")
        self._apply_window_icon(window)
        window.geometry("680x600")
        window.resizable(False, False)
        window.configure(fg_color="#090d18")
        window.transient(self.root)
        window.grab_set()

        header = ctk.CTkFrame(window, fg_color="#101728", corner_radius=12, height=88)
        header.pack(fill="x", padx=18, pady=(18, 12))
        header.pack_propagate(False)
        ctk.CTkLabel(
            header, text="ACCESS & SUBSCRIPTION", font=("Segoe UI", 20, "bold"), text_color="#f8fafc"
        ).pack(anchor="w", padx=18, pady=(14, 0))
        ctk.CTkLabel(
            header,
            text="Manage daily access and redeem Oniflow Pro codes.",
            font=("Segoe UI", 11),
            text_color="#94a3b8",
        ).pack(anchor="w", padx=18, pady=(2, 0))

        status_card = ctk.CTkFrame(window, fg_color="#111a2e", border_width=1, border_color="#263552")
        status_card.pack(fill="x", padx=18, pady=(0, 10))
        ctk.CTkLabel(
            status_card,
            text="ONIFLOW PRO" if pro_active else "FREE PLAN",
            font=("Segoe UI", 14, "bold"),
            text_color="#c4b5fd" if pro_active else "#38bdf8",
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(14, 2))
        ctk.CTkLabel(
            status_card,
            text=(
                "Unlimited clips available"
                if pro_active
                else f"{clips_available} of {FREE_DAILY_CLIP_LIMIT} clips available today"
            ),
            font=("Segoe UI", 13, "bold"),
            text_color="#e2e8f0",
        ).grid(row=1, column=0, sticky="w", padx=16)
        ctk.CTkLabel(
            status_card,
            text=(
                f"Pro access is active until {expiry.astimezone().strftime('%B %d, %Y')}."
                if pro_active and expiry
                else "Only successfully processed clips count toward the daily quota."
            ),
            text_color="#94a3b8",
        ).grid(row=2, column=0, sticky="w", padx=16, pady=(2, 14))
        ctk.CTkLabel(
            status_card,
            text="ACTIVE\nPRO" if pro_active else "RESETS\nDAILY",
            font=("Segoe UI", 12, "bold"),
            text_color="#c4b5fd" if pro_active else "#f59e0b",
        ).grid(row=0, column=1, rowspan=3, padx=20)
        status_card.grid_columnconfigure(0, weight=1)

        plans = ctk.CTkFrame(window, fg_color="transparent")
        plans.pack(fill="x", padx=18, pady=4)
        plans.grid_columnconfigure((0, 1), weight=1, uniform="plan")
        free_card = ctk.CTkFrame(plans, fg_color="#0e1525", border_width=1, border_color="#263552")
        free_card.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        pro_card = ctk.CTkFrame(plans, fg_color="#0e1525", border_width=1, border_color="#7c3aed")
        pro_card.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        ctk.CTkLabel(free_card, text="FREE", font=("Segoe UI", 15, "bold"), text_color="#e2e8f0").pack(
            anchor="w", padx=14, pady=(14, 4)
        )
        ctk.CTkLabel(
            free_card, text="15 clips per day\nWait for daily cooldown\nCore interpolation features",
            justify="left", text_color="#94a3b8",
        ).pack(anchor="w", padx=14, pady=(0, 14))
        ctk.CTkLabel(pro_card, text="ONIFLOW PRO", font=("Segoe UI", 15, "bold"), text_color="#c4b5fd").pack(
            anchor="w", padx=14, pady=(14, 4)
        )
        ctk.CTkLabel(
            pro_card, text="Unlimited clips\nNo cooldown\nPriority features",
            justify="left", text_color="#94a3b8",
        ).pack(anchor="w", padx=14, pady=(0, 8))
        ctk.CTkButton(
            pro_card,
            text="Subscribe (Coming Soon)",
            state="disabled",
            fg_color="#7c3aed",
        ).pack(fill="x", padx=14, pady=(0, 14))

        redeem = ctk.CTkFrame(window, fg_color="#111a2e", border_width=1, border_color="#263552")
        redeem.pack(fill="x", padx=18, pady=(10, 8))
        ctk.CTkLabel(
            redeem, text="REDEEM ACCESS CODE", font=("Segoe UI", 13, "bold"), text_color="#e2e8f0"
        ).pack(anchor="w", padx=14, pady=(12, 2))
        ctk.CTkLabel(
            redeem,
            text="Enter a valid access code to unlock Oniflow Pro for a limited period.",
            text_color="#94a3b8",
        ).pack(anchor="w", padx=14)
        code_row = ctk.CTkFrame(redeem, fg_color="transparent")
        code_row.pack(fill="x", padx=14, pady=(10, 14))
        code_entry = ctk.CTkEntry(
            code_row, placeholder_text="Enter access code", fg_color="#162238", border_color="#263552"
        )
        code_entry.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(
            code_row,
            text="Redeem Code",
            width=140,
            command=lambda: self._redeem_code(code_entry.get(), window),
        ).pack(side="left", padx=(8, 0))
        ctk.CTkLabel(
            window,
            text="Subscriptions through online payment are not available yet. Redeem codes are active.",
            text_color="#64748b",
            wraplength=620,
        ).pack(padx=18, pady=(6, 0))

    def _redeem_code(self, code: str, window: ctk.CTkToplevel) -> None:
        try:
            server_url = self._activation_server_url()
            if not server_url:
                raise ValueError("The activation server is not configured.")
            response = self._activation_request(
                "/activate",
                {
                    "code": code,
                    "device_id": self._device_id(),
                    "device_name": os.environ.get("COMPUTERNAME", "Windows PC"),
                },
            )
            self._apply_server_access(response)
            expiry = pro_expiry(self.access_state)
            expiry_text = expiry.astimezone().strftime("%B %d, %Y") if expiry else "unknown"
            self._log(f"Oniflow Pro access activated until {expiry_text}.")
            messagebox.showinfo("Access Code", f"Oniflow Pro is active until {expiry_text}.", parent=window)
            window.destroy()
            self.access_window = None
        except (ValueError, OSError) as exc:
            messagebox.showerror("Access Code", str(exc), parent=window)

    def _reset_settings(self, window: ctk.CTkToplevel) -> None:
        self.settings = dict(DEFAULT_SETTINGS)
        self._save_settings_file(self.settings)
        self._apply_job_defaults()
        window.destroy()
        self._log("Settings restored to defaults.")

    def _apply_job_defaults(self) -> None:
        self.mode.set(str(self.settings["default_profile"]))
        default_backend = str(self.settings.get("default_backend", self.backend_labels[self.available_backend_ids[0]]))
        if default_backend not in self.backend_labels.values():
            default_backend = self.backend_labels[self.available_backend_ids[0]]
        self.model_name.set(default_backend)
        self.multiplier.set(str(self.settings["default_multiplier"]))
        self.quality.set(str(self.settings["default_interpolation_quality"]))
        self.output_format.set(str(self.settings["default_output_format"]))
        self.slow_motion.set(str(self.settings["default_slow_motion"]))

    @staticmethod
    def _load_settings() -> dict[str, object]:
        settings = dict(DEFAULT_SETTINGS)
        source = SETTINGS_PATH if SETTINGS_PATH.exists() else LEGACY_SETTINGS_PATH
        if source.exists():
            try:
                settings.update(json.loads(source.read_text(encoding="utf-8")))
                if source == LEGACY_SETTINGS_PATH:
                    AnimeVfiPro._save_settings_file(settings)
            except (OSError, json.JSONDecodeError):
                pass
        return settings

    @staticmethod
    def _load_access_state() -> dict[str, object]:
        if ACCESS_PATH.exists():
            try:
                return normalize_access_state(json.loads(ACCESS_PATH.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                pass
        return normalize_access_state()

    def _save_access_state(self) -> None:
        APP_DATA_ROOT.mkdir(parents=True, exist_ok=True)
        temporary = ACCESS_PATH.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.access_state, indent=2), encoding="utf-8")
        temporary.replace(ACCESS_PATH)

    @staticmethod
    def _activation_server_url() -> str:
        if not ACTIVATION_CONFIG_PATH.exists():
            return ""
        try:
            config = json.loads(ACTIVATION_CONFIG_PATH.read_text(encoding="utf-8"))
            return str(config.get("server_url", "")).strip().rstrip("/")
        except (OSError, json.JSONDecodeError):
            return ""

    @staticmethod
    def _device_id() -> str:
        raw = f"{os.environ.get('COMPUTERNAME', '')}|{uuid.getnode()}"
        if sys.platform == "win32":
            try:
                import winreg

                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as key:
                    raw = str(winreg.QueryValueEx(key, "MachineGuid")[0])
            except OSError:
                pass
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @classmethod
    def _activation_request(cls, endpoint: str, payload: dict[str, object]) -> dict[str, object]:
        server_url = cls._activation_server_url()
        if not server_url:
            raise ValueError("The activation server is not configured.")
        request = urllib.request.Request(
            f"{server_url}{endpoint}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                result = json.loads(exc.read().decode("utf-8"))
                raise ValueError(str(result.get("error", "Activation request failed."))) from exc
            except json.JSONDecodeError:
                raise ValueError("Activation request failed.") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise OSError("The activation server is unavailable. Check your internet connection.") from exc
        if not result.get("ok"):
            raise ValueError(str(result.get("error", "Activation request failed.")))
        return result

    def _apply_server_access(self, response: dict[str, object]) -> None:
        self.access_state = normalize_access_state(self.access_state)
        if response.get("token"):
            self.access_state["server_token"] = str(response["token"])
        self.access_state["clips_used"] = int(response.get("clips_used", 0))
        self.access_state["pro_until"] = str(response.get("pro_until", ""))
        self._save_access_state()
        self._update_access_summary()

    def _sync_server_access(self) -> None:
        if not self._activation_server_url():
            return
        token = str(self.access_state.get("server_token", ""))
        if not token:
            response = self._activation_request(
                "/register",
                {
                    "device_id": self._device_id(),
                    "device_name": os.environ.get("COMPUTERNAME", "Windows PC"),
                },
            )
            self._apply_server_access(response)
            token = str(self.access_state["server_token"])
        response = self._activation_request(
            "/status", {"device_id": self._device_id(), "token": token}
        )
        self._apply_server_access(response)

    def _update_access_summary(self) -> None:
        self.access_state = normalize_access_state(self.access_state)
        if is_pro_access(self.access_state):
            expiry = pro_expiry(self.access_state)
            label = expiry.astimezone().strftime("%b %d") if expiry else "ACTIVE"
            self.access_summary.set(f"PRO  {label}")
            return
        available = max(0, FREE_DAILY_CLIP_LIMIT - int(self.access_state["clips_used"]))
        self.access_summary.set(f"FREE  {available}/{FREE_DAILY_CLIP_LIMIT}")

    def _record_successful_clip(self) -> None:
        if not ACCESS_FEATURE_ENABLED:
            return
        token = str(self.access_state.get("server_token", ""))
        if self._activation_server_url() and token:
            try:
                response = self._activation_request(
                    "/consume", {"device_id": self._device_id(), "token": token}
                )
                self._apply_server_access(response)
            except (ValueError, OSError) as exc:
                self._log(f"Access server update failed: {exc}")
            return
        self.access_state = normalize_access_state(self.access_state)
        if not is_pro_access(self.access_state):
            self.access_state["clips_used"] = int(self.access_state["clips_used"]) + 1
            self._save_access_state()
        self._update_access_summary()

    def _has_queue_access(self) -> bool:
        if not ACCESS_FEATURE_ENABLED:
            return True
        try:
            self._sync_server_access()
        except (ValueError, OSError) as exc:
            messagebox.showwarning("Activation Server", str(exc))
            return False
        self.access_state = normalize_access_state(self.access_state)
        self._save_access_state()
        self._update_access_summary()
        if is_pro_access(self.access_state):
            return True
        available = max(0, FREE_DAILY_CLIP_LIMIT - int(self.access_state["clips_used"]))
        if len(self.items) <= available:
            return True
        messagebox.showwarning(
            "Daily Clip Limit",
            f"This queue contains {len(self.items)} clips, but only {available} free clips remain today.\n\n"
            "Reduce the queue, wait for the daily reset, or redeem an Oniflow Pro access code.",
        )
        return False

    def _field(
        self,
        parent: ctk.CTkFrame,
        label: str,
        value: str | None = None,
        variable: ctk.StringVar | None = None,
        options: list[str] | None = None,
        compact: bool = False,
    ) -> None:
        horizontal_padding = 8 if compact else 16
        label_padding = (4, 2) if compact else (17, 5)
        ctk.CTkLabel(parent, text=label.upper(), font=("Segoe UI", 11, "bold"), text_color="#64748b").pack(
            anchor="w", padx=horizontal_padding, pady=label_padding
        )
        if options and variable:
            ctk.CTkOptionMenu(
                parent,
                values=options,
                variable=variable,
                fg_color="#287bb5",
                button_color="#1d5f8c",
                button_hover_color="#3292d0",
                dropdown_fg_color="#162238",
                dropdown_hover_color="#273b59",
                text_color="#f1f5f9",
                height=28 if compact else 32,
            ).pack(fill="x", padx=horizontal_padding)
        elif variable:
            ctk.CTkEntry(
                parent,
                textvariable=variable,
                state="disabled",
                fg_color="#162238",
                border_color="#263552",
                text_color="#e2e8f0",
                height=28 if compact else 32,
            ).pack(fill="x", padx=horizontal_padding)
        else:
            entry = ctk.CTkEntry(
                parent, fg_color="#162238", border_color="#263552", text_color="#e2e8f0"
            )
            entry.insert(0, value or "")
            entry.configure(state="disabled")
            entry.pack(fill="x", padx=horizontal_padding)

    def _mode_changed(self, *_args: object) -> None:
        selected_backend = self.model_name.get()
        if self.mode.get() == "Anime":
            self._log(f"Profile selected: Anime | Model: {selected_backend}")
        else:
            self._log(f"Profile selected: Human | Model: {selected_backend}")

    def choose_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Select Video",
            filetypes=[("Video", "*.mkv *.mp4 *.mov *.webm *.avi *.m4v *.ts *.m2ts"), ("All Files", "*.*")],
        )
        self.add_paths([Path(path) for path in paths])

    def choose_output(self) -> None:
        initial_dir = self.output_dir.get() or (str(self.items[0].path.parent) if self.items else str(ROOT))
        selected = filedialog.askdirectory(initialdir=initial_dir)
        if selected:
            self.output_dir.set(selected)

    def handle_drop(self, event: object) -> None:
        self.add_paths([Path(path) for path in self.root.tk.splitlist(event.data)])

    def add_paths(self, paths: list[Path]) -> None:
        if paths:
            first_path = paths[0].resolve()
            self.output_dir.set(str(first_path if first_path.is_dir() else first_path.parent))
        candidates: list[Path] = []
        for path in paths:
            candidates.extend(path.iterdir() if path.is_dir() else [path])
        known = {item.path for item in self.items}
        for path in candidates:
            resolved = path.resolve()
            if resolved.is_file() and resolved.suffix.lower() in VIDEO_EXTENSIONS and resolved not in known:
                item = QueueItem(resolved)
                self.items.append(item)
                self.process_status.append(item)
                known.add(resolved)
        self._render_queue()
        self._render_process_status()
        self.status.set(f"{len(self.items)} video(s) in queue")

    def _render_queue(self) -> None:
        for child in self.queue_box.winfo_children():
            child.destroy()
        if not self.items:
            ctk.CTkLabel(self.queue_box, text="No videos added", text_color="#475569").pack(side="left", padx=16)
            return
        for item in self.items:
            row = ctk.CTkFrame(self.queue_box, fg_color="#111a2e", width=280, height=48)
            row.pack(side="left", fill="y", padx=(0, 8))
            row.pack_propagate(False)
            ctk.CTkLabel(row, text=item.path.name, text_color="#e2e8f0", anchor="w").pack(
                side="left", fill="x", expand=True, padx=12
            )
            ctk.CTkButton(
                row,
                text="X",
                width=28,
                height=26,
                fg_color="#7f1d1d",
                hover_color="#991b1b",
                command=lambda current=item: self.remove_queue_item(current),
            ).pack(side="right", padx=(0, 6))

    def remove_queue_item(self, item: QueueItem) -> None:
        if self.start_button.cget("state") == "disabled":
            return
        if item in self.items:
            self.items.remove(item)
            if item in self.process_status:
                self.process_status.remove(item)
            self._render_queue()
            self._render_process_status()
            self.status.set(f"{len(self.items)} video(s) in queue")

    def open_process_status(self) -> None:
        if self.status_window and self.status_window.winfo_exists():
            self.status_window.focus()
            return
        window = ctk.CTkToplevel(self.root)
        self.status_window = window
        window.title("Oniflow Process Status")
        self._apply_window_icon(window)
        window.geometry("760x520")
        window.minsize(620, 420)
        window.configure(fg_color="#090d18")
        window.transient(self.root)
        header = ctk.CTkFrame(window, fg_color="#101728", corner_radius=12)
        header.pack(fill="x", padx=16, pady=(16, 10))
        ctk.CTkLabel(header, text="PROCESS STATUS", font=("Segoe UI", 18, "bold"), text_color="#f8fafc").pack(
            side="left", padx=16, pady=14
        )
        ctk.CTkLabel(
            header, textvariable=self.status_total, font=("Segoe UI", 10), text_color="#64748b"
        ).pack(side="left", pady=16)
        ctk.CTkButton(
            header, text="Clear Status", width=110, fg_color="#7f1d1d", hover_color="#991b1b",
            command=self.clear_process_status,
        ).pack(side="right", padx=14, pady=10)
        ctk.CTkButton(
            header,
            text="Clear Queue",
            width=110,
            fg_color="#273449",
            hover_color="#334155",
            command=self.clear_status_queue,
        ).pack(side="right", pady=10)
        self.status_box = ctk.CTkScrollableFrame(
            window, fg_color="#0b1120", border_width=1, border_color="#18243a"
        )
        self.status_box.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        self._render_process_status()

    def _render_process_status(self) -> None:
        self.status_total.set(f"{len(self.process_status)} video{'s' if len(self.process_status) != 1 else ''} total")
        if not self.status_box or not self.status_box.winfo_exists():
            return
        for child in self.status_box.winfo_children():
            child.destroy()
        if not self.process_status:
            ctk.CTkLabel(self.status_box, text="No recent processes", text_color="#64748b").pack(pady=30)
            return
        for item in self.process_status:
            row = ctk.CTkFrame(self.status_box, fg_color="#111a2e", height=66)
            row.pack(fill="x", padx=4, pady=4)
            row.pack_propagate(False)
            info = ctk.CTkFrame(row, fg_color="transparent")
            info.pack(side="left", fill="both", expand=True, padx=12, pady=6)
            ctk.CTkLabel(info, text=item.path.name, anchor="w", text_color="#e2e8f0").pack(fill="x")
            ctk.CTkLabel(info, text=str(item.path), anchor="w", text_color="#64748b", font=("Segoe UI", 10)).pack(
                fill="x"
            )
            color = (
                "#22c55e" if item.status == "Success"
                else "#38bdf8" if item.status == "Processing"
                else "#94a3b8" if item.status == "Queued"
                else "#f59e0b" if item.status == "Cancelled"
                else "#ef4444"
            )
            ctk.CTkLabel(row, text=item.status, text_color=color, width=85).pack(side="right", padx=8)
            ctk.CTkButton(
                row, text="X", width=30, height=28, fg_color="#7f1d1d", hover_color="#991b1b",
                command=lambda current=item: self.remove_process_status_item(current),
            ).pack(side="right", padx=(0, 8))

    def remove_process_status_item(self, item: QueueItem) -> None:
        if item in self.process_status and item.status != "Processing":
            self.process_status.remove(item)
            if item in self.items:
                self.items.remove(item)
                self._render_queue()
            self._render_process_status()

    def clear_process_status(self) -> None:
        self.process_status = [item for item in self.process_status if item.status in {"Queued", "Processing"}]
        self._render_process_status()

    def clear_status_queue(self) -> None:
        if self.start_button.cget("state") == "disabled":
            return
        queued_items = {id(item) for item in self.items}
        self.items.clear()
        self.process_status = [item for item in self.process_status if id(item) not in queued_items]
        self.output_dir.set("")
        self._render_queue()
        self._render_process_status()
        self.status.set("Queue is empty")

    def clear_files(self) -> None:
        if self.start_button.cget("state") == "disabled":
            return
        self.items.clear()
        self.process_status = [item for item in self.process_status if item.status in {"Success", "Failed", "Processing"}]
        self.output_dir.set("")
        self._render_queue()
        self._render_process_status()
        self.status.set("Queue is empty")

    def start(self) -> None:
        if not self.items:
            messagebox.showwarning("Empty Queue", "Add at least one video before starting.")
            return
        security_ok, security_message = verify_runtime_access(
            ROOT, require_manifest=(ROOT / "integrity-manifest.json").is_file()
        )
        if not security_ok:
            self._log(f"Security check failed: {security_message}")
            messagebox.showerror("Oniflow Security", security_message)
            return
        if not self._has_queue_access():
            return
        if not self.output_dir.get().strip():
            self.output_dir.set(str(self.items[0].path.parent))
        output = Path(self.output_dir.get())
        try:
            output.mkdir(parents=True, exist_ok=True)
            free_space = shutil.disk_usage(output).free
        except OSError as exc:
            messagebox.showerror("Output Directory", f"Oniflow cannot use the selected output directory.\n\n{exc}")
            return
        if free_space < 1024**3:
            messagebox.showerror("Storage", "Less than 1 GB of free space is available in the output directory.")
            return
        for item in self.items:
            try:
                info = probe_video(item.path)
            except (PipelineError, subprocess.CalledProcessError, OSError) as exc:
                messagebox.showerror("Invalid Video", f"{item.path.name}\n\n{exc}")
                return
            if info.width >= 3840 or info.height >= 2160:
                mode = str(self.settings["uhd_mode"])
                self._log(f"4K input detected: {item.path.name} | 4K Processing Mode: {mode}")
        try:
            self._log_job_estimate()
            runtime_config = self._write_runtime_config()
        except (OSError, KeyError, ValueError) as exc:
            message = f"Oniflow could not prepare the interpolation job.\n\n{exc}"
            self._log(f"ERROR: Job preparation failed: {exc}")
            messagebox.showerror("Cannot Start Processing", message)
            return
        self.cancelled = False
        self.paused = False
        self.started_at = time.monotonic()
        for item in self.items:
            item.status = "Queued"
        self._render_process_status()
        self.start_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.pause_button.configure(state="normal", text="Pause")
        job_config = {
            "backend": next(
                (backend for backend, label in self.backend_labels.items() if label == self.model_name.get()),
                self.available_backend_ids[0],
            ),
            "mode": "anime" if self.mode.get() == "Anime" else "live-action",
            "extension": output_extension(self.output_format.get()),
            "multiplier": self.multiplier.get().removesuffix("x"),
            "slow_motion_factor": (
                self.slow_motion.get().removesuffix("x") if self.slow_motion.get() != "Off" else "1"
            ),
            "scale": {"Fast": "0.5", "Normal": "0.75", "Quality": "1.0"}[self.quality.get()],
            "runtime_config": runtime_config,
        }
        threading.Thread(target=self._run_queue, args=(output, job_config), daemon=True).start()

    def _run_queue(self, output_dir: Path, job_config: dict[str, object]) -> None:
        failures = 0
        queue_snapshot = list(self.items)
        total_files = len(queue_snapshot)
        mode = str(job_config["mode"])
        backend = str(job_config["backend"])
        extension = str(job_config["extension"])
        multiplier = str(job_config["multiplier"])
        slow_motion_factor = str(job_config["slow_motion_factor"])
        runtime_config = Path(job_config["runtime_config"])
        try:
            if total_files > 1:
                batch_jobs: list[dict[str, str]] = []
                batch_outputs: list[tuple[QueueItem, Path]] = []
                manifest: Path | None = None
                for item in queue_snapshot:
                    input_info = probe_video(item.path)
                    output = self._unique_output(
                        output_dir
                        / build_output_filename(
                            item.path.stem,
                            extension,
                            input_info.fps,
                            int(multiplier),
                            int(slow_motion_factor),
                        )
                    )
                    batch_outputs.append((item, output))
                    batch_jobs.append({"input": str(item.path), "output": str(output)})
                try:
                    APP_DATA_ROOT.mkdir(parents=True, exist_ok=True)
                    manifest = APP_DATA_ROOT / f"batch-{uuid.uuid4().hex}.json"
                    manifest.write_text(json.dumps(batch_jobs, indent=2), encoding="utf-8")
                    pipeline = ROOT / ("anime_vfi.pyc" if (ROOT / "anime_vfi.pyc").is_file() else "anime_vfi.py")
                    command = [
                        str(self._pipeline_python()), str(pipeline), "batch", str(manifest),
                        "--backend", backend,
                        "--mode", mode, "--multiplier", multiplier,
                        "--scale", str(job_config["scale"]),
                        "--config", str(runtime_config),
                        "--uhd-mode",
                        {
                            "Auto (Recommended)": "auto",
                            "Full Resolution": "full",
                            "Memory Saver": "memory",
                        }[str(self.settings["uhd_mode"])],
                    ]
                    if slow_motion_factor != "1":
                        command.extend(["--slow-motion-factor", slow_motion_factor])
                    throttle_ms = {"100%": 0, "80%": 5, "60%": 15, "40%": 30}[str(self.settings["gpu_usage_limit"])]
                    if throttle_ms:
                        command.extend(["--throttle-ms", str(throttle_ms)])
                    if self.settings["scene_protection"]:
                        command.extend(["--scene-threshold", str(self.settings["scene_threshold"])])
                    else:
                        command.extend(["--scene-threshold", "2.0"])
                    if self.settings["held_frame_protection"]:
                        command.extend(["--static-threshold", str(self.settings["static_threshold"])])
                    else:
                        command.extend(["--static-threshold", "-1.0"])
                    if self.settings["temp_dir"]:
                        command.extend(["--temp-dir", str(self.settings["temp_dir"])])
                    if not self.settings["delete_cache"]:
                        command.append("--keep-temp")
                    self.events.put(("log", f"Starting GMFSS batch interpolation for {total_files} video(s)..."))
                    current_index = 0
                    queue_snapshot[0].status = "Processing"
                    self.events.put(("render", None))
                    self.events.put(("render_status", None))
                    self.process = subprocess.Popen(
                        command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        text=True, encoding="utf-8", errors="replace", bufsize=1,
                        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
                    )
                    assert self.process.stdout
                    for line in self.process.stdout:
                        clean = line.strip()
                        if clean:
                            friendly = self._friendly_error(clean)
                            self.events.put(("log", friendly))
                        batch_match = re.search(r"VFI_BATCH_ITEM\s+(\d+)\s+(\d+)", clean)
                        if batch_match:
                            current_index = max(0, int(batch_match.group(1)) - 1)
                            for previous in queue_snapshot[:current_index]:
                                if previous.status == "Processing":
                                    previous.status = "Queued"
                            queue_snapshot[current_index].status = "Processing"
                            self.events.put(("status", f"Processing {current_index + 1}/{total_files}: {queue_snapshot[current_index].path.name}"))
                            self.events.put(("render", None))
                            self.events.put(("render_status", None))
                        match = PROGRESS_RE.search(clean)
                        if match:
                            current, total = map(int, match.groups())
                            file_progress = min(current / max(total, 1), 1.0)
                            overall = (current_index + file_progress) / total_files
                            self.events.put(("progress", overall))
                    return_code = self.process.wait()
                    self.process = None
                    if self.cancelled:
                        for item in queue_snapshot:
                            if item.status in {"Queued", "Processing"}:
                                item.status = "Cancelled"
                    elif return_code == 0:
                        for item, output in batch_outputs:
                            item.status = "Success"
                            if ACCESS_FEATURE_ENABLED:
                                self.events.put(("access_success", None))
                            try:
                                result_info = probe_video(output)
                                elapsed = time.monotonic() - self.started_at
                                size_mb = output.stat().st_size / 1024**2
                                self.events.put((
                                    "log",
                                    f"Result: {output.name} | {result_info.width}x{result_info.height} | "
                                    f"{result_info.fps:.3f} FPS | {result_info.duration:.2f}s | {size_mb:.1f} MB | "
                                    f"elapsed {elapsed:.1f}s | {output}",
                                ))
                            except Exception as exc:
                                item.status = "Failed"
                                failures += 1
                                self.events.put(("log", f"Result verification failed: {exc}"))
                            self.events.put(("archive", item))
                    else:
                        failures = total_files
                        for item in queue_snapshot:
                            item.status = "Failed"
                            self.events.put(("archive", item))
                    self.events.put(("render", None))
                    self.events.put(("render_status", None))
                    return
                finally:
                    if manifest:
                        manifest.unlink(missing_ok=True)
            for index, item in enumerate(queue_snapshot):
                if self.cancelled:
                    break
                item.status = "Processing"
                self.events.put(("render", None))
                self.events.put(("render_status", None))
                input_info = probe_video(item.path)
                output = self._unique_output(
                    output_dir
                    / build_output_filename(
                        item.path.stem,
                        extension,
                        input_info.fps,
                        int(multiplier),
                        int(slow_motion_factor),
                    )
                )
                pipeline = ROOT / ("anime_vfi.pyc" if (ROOT / "anime_vfi.pyc").is_file() else "anime_vfi.py")
                command = [
                    str(self._pipeline_python()), str(pipeline), "run", str(item.path), str(output),
                    "--backend", backend,
                    "--mode", mode, "--multiplier", multiplier,
                    "--scale", str(job_config["scale"]),
                    "--config", str(runtime_config),
                    "--uhd-mode",
                    {
                        "Auto (Recommended)": "auto",
                        "Full Resolution": "full",
                        "Memory Saver": "memory",
                    }[str(self.settings["uhd_mode"])],
                ]
                if slow_motion_factor != "1":
                    command.extend(["--slow-motion-factor", slow_motion_factor])
                throttle_ms = {"100%": 0, "80%": 5, "60%": 15, "40%": 30}[str(self.settings["gpu_usage_limit"])]
                if throttle_ms:
                    command.extend(["--throttle-ms", str(throttle_ms)])
                if self.settings["scene_protection"]:
                    command.extend(["--scene-threshold", str(self.settings["scene_threshold"])])
                else:
                    command.extend(["--scene-threshold", "2.0"])
                if self.settings["held_frame_protection"]:
                    command.extend(["--static-threshold", str(self.settings["static_threshold"])])
                else:
                    command.extend(["--static-threshold", "-1.0"])
                if self.settings["temp_dir"]:
                    command.extend(["--temp-dir", str(self.settings["temp_dir"])])
                if not self.settings["delete_cache"]:
                    command.append("--keep-temp")
                self.events.put(("log", "Starting GMFSS interpolation..."))
                self.events.put(("status", f"Processing {index + 1}/{total_files}: {item.path.name}"))
                self.process = subprocess.Popen(
                    command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace", bufsize=1,
                    env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                    creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
                )
                assert self.process.stdout
                for line in self.process.stdout:
                    clean = line.strip()
                    if clean:
                        friendly = self._friendly_error(clean)
                        self.events.put(("log", friendly))
                    match = PROGRESS_RE.search(clean)
                    if match:
                        current, total = map(int, match.groups())
                        file_progress = min(current / max(total, 1), 1.0)
                        overall = (index + file_progress) / total_files
                        self.events.put(("progress", overall))
                return_code = self.process.wait()
                self.process = None
                if self.cancelled:
                    item.status = "Cancelled"
                elif return_code == 0:
                    item.status = "Success"
                    if ACCESS_FEATURE_ENABLED:
                        self.events.put(("access_success", None))
                    try:
                        result_info = probe_video(output)
                        elapsed = time.monotonic() - self.started_at
                        size_mb = output.stat().st_size / 1024**2
                        self.events.put((
                            "log",
                            f"Result: {output.name} | {result_info.width}x{result_info.height} | "
                            f"{result_info.fps:.3f} FPS | {result_info.duration:.2f}s | {size_mb:.1f} MB | "
                            f"elapsed {elapsed:.1f}s | {output}",
                        ))
                    except Exception as exc:
                        self.events.put(("log", f"Result created, but verification failed: {exc}"))
                else:
                    item.status = "Failed"
                    failures += 1
                self.events.put(("archive", item))
        except Exception as exc:
            failures += 1
            self.events.put(("log", f"ERROR: Queue worker stopped unexpectedly: {exc}"))
            for item in queue_snapshot:
                if item.status in {"Queued", "Processing"}:
                    item.status = "Failed"
            self.events.put(("render", None))
            self.events.put(("render_status", None))
        finally:
            self.process = None
            self.events.put(("done", failures))

    def _write_runtime_config(self) -> Path:
        config = json.loads(BASE_CONFIG_PATH.read_text(encoding="utf-8"))
        if not self.settings["mixed_precision"]:
            for backend in available_backends(config):
                for profile in (f"{backend}_anime", f"{backend}_live_action"):
                    if profile not in config:
                        continue
                    config[profile]["command"] = [
                        argument for argument in config[profile]["command"] if argument != "--amp"
                    ]
        codecs = {"AV1": "av1_nvenc", "HEVC": "hevc_nvenc", "H.264": "h264_nvenc"}
        quality_values = {"High Quality (CQ 14)": 14, "Balanced (CQ 18)": 18, "Small File (CQ 23)": 23}
        output_format_value = (
            self.output_format.get() if hasattr(self, "output_format") else str(self.settings["default_output_format"])
        )
        if output_format_value == "MOV with Alpha":
            config["encoder"] = {
                "codec": "prores_ks",
                "profile": "4444",
                "pixel_format": "yuva444p10le",
                "bits_per_mb": 8000,
            }
        elif output_format_value == "MOV":
            config["encoder"] = {
                "codec": "prores_ks",
                "profile": "3",
                "pixel_format": "yuv422p10le",
                "bits_per_mb": 8000,
            }
        else:
            selected_codec = str(self.settings["video_codec"])
            supported = self.device_caps.get("encoders", [])
            if supported and selected_codec not in supported:
                fallback = "H.264" if "H.264" in supported else str(supported[0])
                self._log(f"{selected_codec} is unsupported on this GPU. Using {fallback}.")
                selected_codec = fallback
            config["encoder"]["codec"] = codecs[selected_codec]
            config["encoder"]["cq"] = quality_values[str(self.settings["quality_value"])]
            config["encoder"]["pixel_format"] = "p010le" if self.settings["bit_depth"] == "10-bit" else "yuv420p"
        config["audio"] = {
            "mp4_fallback_codec": "aac",
            "copy_for_mkv": True,
            "mute": self.settings["audio_mode"] == "Mute Audio",
        }
        config["preserve_metadata"] = self.settings["preserve_metadata"]
        config["preserve_subtitles"] = self.settings["preserve_subtitles"]
        APP_DATA_ROOT.mkdir(parents=True, exist_ok=True)
        path = APP_DATA_ROOT / "runtime-config.json"
        path.write_text(json.dumps(config, indent=2), encoding="utf-8")
        return path

    def _maybe_auto_check_for_updates(self) -> None:
        if not self.settings.get("auto_check_updates", True):
            return
        last_check = parse_iso_datetime(self.settings.get("last_update_check"))
        interval_hours = max(1, int(self.settings.get("update_check_interval_hours", 24)))
        now = datetime.now(timezone.utc)
        if last_check and now - last_check < timedelta(hours=interval_hours):
            return
        self.check_for_updates(automatic=True)

    def _record_update_check(self) -> None:
        self.settings["last_update_check"] = datetime.now(timezone.utc).isoformat()
        self._save_settings_file(self.settings)

    def check_for_updates(self, parent: ctk.CTkToplevel | None = None, automatic: bool = False) -> None:
        self._log("Checking for updates..." if not automatic else "Checking for updates automatically...")
        threading.Thread(target=self._check_for_updates_worker, args=(parent, automatic), daemon=True).start()

    def _check_for_updates_worker(self, parent: ctk.CTkToplevel | None, automatic: bool = False) -> None:
        try:
            config = load_update_config()
            release_api_url = config["release_api_url"]
            manifest_url = config["manifest_url"]
            if release_api_url:
                try:
                    update = fetch_github_release_update(release_api_url, config["channel"])
                except Exception as exc:
                    if not manifest_url:
                        raise
                    self.events.put(("log", f"GitHub release update check failed, using manifest fallback: {exc}"))
                    update = fetch_update_manifest(manifest_url)
            else:
                if not manifest_url:
                    raise RuntimeError("Update source is not configured.")
                update = fetch_update_manifest(manifest_url)
            self._record_update_check()
            if not update_is_newer(update["latest_version"]):
                if not automatic:
                    self.root.after(0, lambda: messagebox.showinfo(
                        "Oniflow Update", f"Oniflow {APP_VERSION} is already up to date.", parent=parent
                    ))
                self.events.put(("log", "No update available."))
                return
            self.root.after(0, lambda: self._confirm_update(update, parent))
        except Exception as exc:
            self._record_update_check()
            message = friendly_update_error(exc)
            self.events.put(("log", f"Update check failed: {message}"))
            if not automatic:
                self.root.after(0, lambda: messagebox.showerror("Oniflow Update", message, parent=parent))

    def _confirm_update(self, update: dict[str, str], parent: ctk.CTkToplevel | None) -> None:
        notes = update.get("release_notes") or "No release notes were provided."
        update_label = "small patch update" if update.get("update_kind") == "patch" else "full installer update"
        message = (
            f"Oniflow {update['latest_version']} is available.\n\n"
            f"{notes}\n\n"
            f"This will use a {update_label}.\n\n"
            "Download and start the updater now?"
        )
        if not messagebox.askyesno("Oniflow Update", message, parent=parent):
            self._log("Update cancelled by user.")
            return
        if update.get("update_kind") == "patch":
            self._log(f"Downloading Oniflow {update['latest_version']} patch...")
        else:
            self._log(f"Downloading Oniflow {update['latest_version']} installer...")
        threading.Thread(target=self._download_update_worker, args=(update, parent), daemon=True).start()

    def _download_update_worker(self, update: dict[str, str], parent: ctk.CTkToplevel | None) -> None:
        try:
            progress = lambda downloaded, total: self.events.put(("update_progress", (downloaded, total)))
            if update.get("update_kind") == "patch":
                target = download_update_patch(update, APP_DATA_ROOT / "updates", progress)
                self.root.after(0, lambda: self._launch_patch_updater(target, update, parent))
            else:
                target = download_update_installer(update, APP_DATA_ROOT / "updates", progress)
                self.root.after(0, lambda: self._launch_update_installer(target, parent))
        except Exception as exc:
            message = str(exc)
            self.events.put(("log", f"Update download failed: {message}"))
            self.events.put(("status", "Update download failed"))
            self.root.after(0, lambda: messagebox.showerror("Oniflow Update", message, parent=parent))

    def _launch_update_installer(self, installer: Path, parent: ctk.CTkToplevel | None) -> None:
        self._log(f"Starting update installer: {installer}")
        messagebox.showinfo(
            "Oniflow Update",
            "The updater will start now. Windows may ask for administrator permission.",
            parent=parent,
        )
        subprocess.Popen([
            str(installer),
            "/SP-",
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
            "/CLOSEAPPLICATIONS",
        ])
        self.root.after(1000, self.root.destroy)

    def _launch_patch_updater(self, patch: Path, update: dict[str, str], parent: ctk.CTkToplevel | None) -> None:
        script = self._write_patch_updater_script()
        exe_path = self._app_executable_path()
        updater_dir = APP_DATA_ROOT / "updates"
        updater_dir.mkdir(parents=True, exist_ok=True)
        request = updater_dir / "patch-request.json"
        request.write_text(
            json.dumps(
                {
                    "zip_path": str(patch.resolve()),
                    "app_dir": str(ROOT.resolve()),
                    "exe_path": str(exe_path.resolve()),
                    "process_id": os.getpid(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        self._log(f"Starting patch updater: {patch}")
        messagebox.showinfo(
            "Oniflow Update",
            "The patch updater will start now. Windows may ask for administrator permission.",
            parent=parent,
        )
        powershell_args = (
            f'-NoProfile -ExecutionPolicy Bypass -File "{script}" '
            f'-RequestPath "{request}"'
        )
        result = ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            "powershell.exe",
            powershell_args,
            None,
            0,
        )
        if result <= 32:
            raise RuntimeError(f"Windows could not start the patch updater (code {result}).")
        self.root.after(1000, self.root.destroy)

    @staticmethod
    def _write_patch_updater_script() -> Path:
        updater_dir = APP_DATA_ROOT / "updates"
        updater_dir.mkdir(parents=True, exist_ok=True)
        script = updater_dir / "apply-oniflow-patch.ps1"
        script.write_text(
            """param(
    [Parameter(Mandatory=$true)][string]$RequestPath
)
$ErrorActionPreference = 'Stop'
$UpdateDir = Join-Path $env:LOCALAPPDATA 'Oniflow\\updates'
$LogPath = Join-Path $UpdateDir 'patch-update.log'
try {
    New-Item -ItemType Directory -Force -Path $UpdateDir | Out-Null
    "Patch updater started: $(Get-Date -Format o)" | Set-Content -Path $LogPath -Encoding utf8
    if (-not (Test-Path -LiteralPath $RequestPath)) {
        throw "Patch request file was not found: $RequestPath"
    }
    $request = Get-Content -LiteralPath $RequestPath -Raw | ConvertFrom-Json
    $zipPath = [string]$request.zip_path
    $appDir = [string]$request.app_dir
    $exePath = [string]$request.exe_path
    $processId = [int]$request.process_id
    if (-not (Test-Path -LiteralPath $zipPath)) {
        throw "Patch archive was not found: $zipPath"
    }
    if (-not (Test-Path -LiteralPath $appDir)) {
        throw "Oniflow folder was not found: $appDir"
    }
    "Waiting for Oniflow process $processId" | Out-File -FilePath $LogPath -Encoding utf8 -Append
    Wait-Process -Id $processId -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    Expand-Archive -LiteralPath $zipPath -DestinationPath $appDir -Force
    "Patch applied from $zipPath" | Out-File -FilePath $LogPath -Encoding utf8 -Append
    Start-Process -FilePath $exePath
    "Oniflow restarted: $exePath" | Out-File -FilePath $LogPath -Encoding utf8 -Append
} catch {
    New-Item -ItemType Directory -Force -Path $UpdateDir | Out-Null
    $_.Exception.Message | Out-File -FilePath $LogPath -Encoding utf8 -Append
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show($_.Exception.Message, 'Oniflow Patch Update Failed') | Out-Null
}
""",
            encoding="utf-8",
        )
        return script

    @staticmethod
    def _app_executable_path() -> Path:
        if getattr(sys, "frozen", False):
            return Path(sys.executable)
        candidate = ROOT / "Oniflow.exe"
        return candidate if candidate.is_file() else Path(sys.executable)

    @staticmethod
    def _pipeline_python() -> Path:
        portable_python = ROOT / "work" / "python-runtime" / "python.exe"
        bundled_python = ROOT / "work" / "gmfss-venv" / "Scripts" / "python.exe"
        if portable_python.is_file():
            return portable_python
        return bundled_python if bundled_python.is_file() else Path(sys.executable)

    def cancel(self) -> None:
        self.cancelled = True
        self.status.set("Stopping process...")
        if self.process and self.process.poll() is None:
            subprocess.run(
                ["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )

    def toggle_pause(self) -> None:
        if not self.process or self.process.poll() is not None:
            return
        try:
            import psutil

            process = psutil.Process(self.process.pid)
            children = process.children(recursive=True)
            if self.paused:
                for child in reversed(children):
                    child.resume()
                process.resume()
                self.paused = False
                self.pause_button.configure(text="Pause")
                self.status.set("Processing resumed")
                self._log("Processing resumed.")
            else:
                for child in children:
                    child.suspend()
                process.suspend()
                self.paused = True
                self.pause_button.configure(text="Resume")
                self.status.set("Processing paused")
                self._log("Processing paused.")
        except Exception as exc:
            self._log(f"Pause or resume failed: {exc}")

    def _log_job_estimate(self) -> None:
        total_frames = 0
        total_bytes = 0
        multiplier = int(self.multiplier.get().removesuffix("x"))
        for item in self.items:
            info = probe_video(item.path)
            total_frames += info.frame_count * multiplier
            total_bytes += item.path.stat().st_size * multiplier
        estimated_gb = total_bytes / 1024**3
        free_gb = shutil.disk_usage(self.output_dir.get()).free / 1024**3
        self._log(
            f"Estimate: {len(self.items)} video(s) | approximately {total_frames:,} output frames | "
            f"up to {estimated_gb:.2f} GB working/output data | {free_gb:.1f} GB free"
        )

    def _startup_device_check(self) -> None:
        try:
            local_ffmpeg = ROOT / "tools" / "ffmpeg.exe"
            ffmpeg = str(local_ffmpeg) if local_ffmpeg.is_file() else "ffmpeg"
            gpu_result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if gpu_result.returncode:
                raise RuntimeError(gpu_result.stderr.strip() or "nvidia-smi failed")
            name, memory, driver = [part.strip() for part in gpu_result.stdout.split(",")]
            encoder_result = subprocess.run(
                [ffmpeg, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=8,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if encoder_result.returncode:
                raise RuntimeError(encoder_result.stderr.strip() or "FFmpeg encoder check failed")
            encoders = encoder_result.stdout
            supported = [label for label, codec in (("AV1", "av1_nvenc"), ("HEVC", "hevc_nvenc"), ("H.264", "h264_nvenc")) if codec in encoders]
            self.events.put(("device", {
                "gpu": name,
                "vram_mb": int(memory),
                "driver": driver,
                "encoders": supported,
            }))
        except Exception as exc:
            self.events.put(("log", f"Device compatibility check failed: {exc}"))

    @staticmethod
    def _friendly_error(line: str) -> str:
        lowered = line.lower()
        if "out of memory" in lowered:
            return "ERROR: GPU VRAM is insufficient. Use 4K Memory Saver, Fast quality, or a lower multiplier."
        if "no space left" in lowered or "not enough space" in lowered:
            return "ERROR: The selected drive does not have enough free space."
        if "permission denied" in lowered or "access is denied" in lowered:
            return "ERROR: Oniflow cannot access a required file or folder. Select another output directory."
        if line.startswith("ERROR: Command"):
            return "ERROR: Interpolation engine stopped unexpectedly. Review the preceding log messages."
        return line

    def _poll_events(self) -> None:
        while True:
            try:
                kind, payload = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "log":
                self._log(str(payload))
            elif kind == "status":
                self.status.set(str(payload))
            elif kind == "device":
                caps = payload
                if isinstance(caps, dict):
                    self.device_caps = caps
                    supported = caps.get("encoders", [])
                    self._log(
                        f"Device check: {caps.get('gpu')} | {caps.get('vram_mb')} MB VRAM | "
                        f"Driver {caps.get('driver')} | Encoders: {', '.join(supported)}"
                    )
                    if not supported:
                        messagebox.showerror("Unsupported GPU", "No supported NVIDIA NVENC encoder was detected.")
            elif kind == "gpu":
                self.gpu.set(str(payload))
                self.root.after(2000, self._start_gpu_update)
            elif kind == "render":
                self._render_queue()
            elif kind == "render_status":
                self._render_process_status()
            elif kind == "archive":
                item = payload
                if isinstance(item, QueueItem):
                    if item in self.items:
                        self.items.remove(item)
                    self._render_queue()
                    self._render_process_status()
            elif kind == "access_success":
                self._record_successful_clip()
            elif kind == "progress":
                value = float(payload)
                self.progress.set(value)
                self.progress_text.set(f"{value * 100:.1f}%")
                elapsed = time.monotonic() - self.started_at
                remaining = elapsed * (1 - value) / value if value > 0 else 0
                self.eta_text.set(f"ETA {int(remaining // 60):02d}:{int(remaining % 60):02d}")
            elif kind == "update_progress":
                downloaded, total = payload
                downloaded_mb = int(downloaded) / (1024 * 1024)
                if total:
                    total_mb = int(total) / (1024 * 1024)
                    value = min(max(int(downloaded) / int(total), 0.0), 1.0)
                    self.progress.set(value)
                    self.progress_text.set(f"{value * 100:.1f}%")
                    self.status.set(f"Downloading update {downloaded_mb:.0f}/{total_mb:.0f} MB")
                else:
                    self.status.set(f"Downloading update {downloaded_mb:.0f} MB")
                    self.progress_text.set("Downloading")
                self.eta_text.set("ETA --:--")
            elif kind == "done":
                self.start_button.configure(state="normal")
                self.cancel_button.configure(state="disabled")
                self.pause_button.configure(state="disabled", text="Pause")
                self.status.set("Stopped" if self.cancelled else f"Completed. {payload} failed.")
                if not self.cancelled:
                    self.progress.set(1)
                    self.progress_text.set("100%")
                    if self.settings["open_output"]:
                        os.startfile(self.output_dir.get())
                    if self.settings["notify_complete"]:
                        messagebox.showinfo("Oniflow", f"Processing completed. {payload} failed.")
        self.root.after(100, self._poll_events)

    def _start_gpu_update(self) -> None:
        threading.Thread(target=self._update_gpu, daemon=True).start()

    def _update_gpu(self) -> None:
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=3, creationflags=subprocess.CREATE_NO_WINDOW,
            )
            name, util, used, total = [part.strip() for part in result.stdout.split(",")]
            text = f"{name}  |  GPU {util}%  |  VRAM {used}/{total} MB"
        except Exception:
            text = "GPU unavailable"
        self.events.put(("gpu", text))

    def _log(self, text: str) -> None:
        timestamp = time.strftime("%H:%M:%S")
        line = f"[{timestamp}] {text}\n"
        self.log.insert("end", line)
        self.log.see("end")
        if self.settings["save_logs"]:
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(line)

    @staticmethod
    def _unique_output(path: Path) -> Path:
        if not path.exists():
            return path
        counter = 2
        while True:
            candidate = path.with_name(f"{path.stem}_{counter}{path.suffix}")
            if not candidate.exists():
                return candidate
            counter += 1

    def _close(self) -> None:
        if self.process and self.settings["confirm_exit"] and not messagebox.askyesno(
            "Exit", "Processing is still active. Stop it and exit?"
        ):
            return
        self.cancel()
        self.root.destroy()


def main() -> None:
    root = CTkDnD()
    AnimeVfiPro(root)
    root.mainloop()


if __name__ == "__main__":
    main()
