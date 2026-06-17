#!/usr/bin/env python3
"""Anime-focused video interpolation pipeline with a pluggable GMFSS engine."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

from runtime_security import verify_runtime_access


SCENE_RE = re.compile(r"pts_time:(?P<time>[0-9.]+)")
DROP_RE = re.compile(r"\bdrop pts:")
WINDOWS_CREATION_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


class PipelineError(RuntimeError):
    pass


@dataclass(frozen=True)
class VideoInfo:
    width: int
    height: int
    fps: float
    duration: float
    frame_count: int
    codec: str
    pixel_format: str
    has_audio: bool
    has_subtitles: bool


def run_command(
    command: list[str],
    capture: bool = False,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    print(f"VFI_TASK {Path(command[0]).name}", flush=True)
    if capture:
        return subprocess.run(
            command,
            check=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            cwd=cwd,
            creationflags=WINDOWS_CREATION_FLAGS,
        )

    process = subprocess.Popen(
        command,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=cwd,
        creationflags=WINDOWS_CREATION_FLAGS,
    )
    output: list[str] = []
    assert process.stdout
    for line in process.stdout:
        output.append(line)
        print(line, end="", flush=True)
    return_code = process.wait()
    combined_output = "".join(output)
    if return_code:
        raise subprocess.CalledProcessError(return_code, command, output=combined_output)
    return subprocess.CompletedProcess(command, return_code, stdout=combined_output, stderr=None)


def require_tool(name: str) -> str:
    local_tool = Path(__file__).resolve().parent / "tools" / f"{name}.exe"
    path = str(local_tool) if local_tool.is_file() else shutil.which(name)
    if not path:
        raise PipelineError(f"{name} tidak ditemukan di PATH.")
    return path


def parse_rate(value: str) -> float:
    try:
        return float(Fraction(value))
    except (ValueError, ZeroDivisionError) as exc:
        raise PipelineError(f"Frame rate tidak valid: {value}") from exc


def resolve_motion_scale(width: int, height: int, requested_scale: float, uhd_mode: str) -> float:
    is_4k = width >= 3840 or height >= 2160
    if uhd_mode == "memory" or (uhd_mode == "auto" and is_4k):
        return min(requested_scale, 0.5)
    return requested_scale


def probe_video(path: Path) -> VideoInfo:
    ffprobe = require_tool("ffprobe")
    result = run_command(
        [
            ffprobe,
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ],
        capture=True,
    )
    data = json.loads(result.stdout)
    video = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
    if not video:
        raise PipelineError("Input tidak memiliki stream video.")
    duration = float(video.get("duration") or data["format"].get("duration") or 0)
    fps = parse_rate(video.get("avg_frame_rate") or video["r_frame_rate"])
    frame_count = int(video.get("nb_frames") or round(duration * fps))
    types = {stream["codec_type"] for stream in data["streams"]}
    return VideoInfo(
        width=int(video["width"]),
        height=int(video["height"]),
        fps=fps,
        duration=duration,
        frame_count=frame_count,
        codec=video["codec_name"],
        pixel_format=video.get("pix_fmt", "unknown"),
        has_audio="audio" in types,
        has_subtitles="subtitle" in types,
    )


def detect_scenes(path: Path, threshold: float) -> list[float]:
    ffmpeg = require_tool("ffmpeg")
    result = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-i",
            str(path),
            "-vf",
            f"select='gt(scene,{threshold})',metadata=print",
            "-an",
            "-f",
            "null",
            "-",
        ],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        creationflags=WINDOWS_CREATION_FLAGS,
    )
    if result.returncode:
        raise PipelineError("Deteksi scene gagal.\n" + result.stderr[-1200:])
    return [float(match.group("time")) for match in SCENE_RE.finditer(result.stderr)]


def count_duplicate_frames(path: Path, similarity: float) -> int:
    ffmpeg = require_tool("ffmpeg")
    result = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "debug",
            "-i",
            str(path),
            "-vf",
            f"mpdecimate=hi={similarity}:lo={similarity}:frac=1",
            "-an",
            "-f",
            "null",
            "-",
        ],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        creationflags=WINDOWS_CREATION_FLAGS,
    )
    if result.returncode:
        raise PipelineError("Deteksi held frame gagal.\n" + result.stderr[-1200:])
    return len(DROP_RE.findall(result.stderr))


def analyze(input_path: Path, report_path: Path, scene_threshold: float, duplicate_threshold: int) -> None:
    info = probe_video(input_path)
    scenes = detect_scenes(input_path, scene_threshold)
    duplicates = count_duplicate_frames(input_path, duplicate_threshold)
    report = {
        "input": str(input_path.resolve()),
        "video": asdict(info),
        "analysis": {
            "scene_threshold": scene_threshold,
            "scene_changes": len(scenes),
            "scene_change_times": scenes,
            "duplicate_threshold": duplicate_threshold,
            "estimated_duplicate_frames": duplicates,
            "duplicate_ratio": None if duplicates < 0 else round(duplicates / max(info.frame_count, 1), 5),
        },
        "recommendation": {
            "engine": "gmfss",
            "target_fps": 60,
            "protect_scene_changes": True,
            "preserve_held_frames": True,
            "encoder": "av1_nvenc",
            "pixel_format": "p010le",
        },
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Laporan tersimpan: {report_path}")


def render_template(template: list[str], values: dict[str, str]) -> list[str]:
    try:
        return [part.format(**values) for part in template]
    except KeyError as exc:
        raise PipelineError(f"Placeholder konfigurasi tidak dikenal: {exc}") from exc


def validate_engine_command(command: list[str], cwd: Path | None) -> None:
    """Allow only the bundled GMFSS inference entry point."""
    project_root = Path(__file__).resolve().parent
    allowed_python = {
        (project_root / "work" / "python-runtime" / "python.exe").resolve(),
        (project_root / "work" / "gmfss-venv" / "Scripts" / "python.exe").resolve(),
    }
    allowed_cwd = (project_root / "work" / "GMFSS_Fortuna").resolve()
    if len(command) < 2:
        raise PipelineError("GMFSS engine command is incomplete.")
    executable = Path(command[0]).resolve()
    script = Path(command[1])
    resolved_script = ((cwd or project_root) / script).resolve() if not script.is_absolute() else script.resolve()
    allowed_script = (allowed_cwd / "inference_video.py").resolve()
    if executable not in allowed_python or resolved_script != allowed_script or cwd != allowed_cwd:
        raise PipelineError("Unsafe GMFSS engine command was blocked.")


def load_config(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PipelineError(f"Konfigurasi tidak ditemukan: {path}") from exc
    except json.JSONDecodeError as exc:
        raise PipelineError(f"JSON konfigurasi tidak valid: {exc}") from exc


def interpolate_preview(input_path: Path, output_path: Path, target_fps: int) -> None:
    ffmpeg = require_tool("ffmpeg")
    run_command(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-i",
            str(input_path),
            "-vf",
            f"minterpolate=fps={target_fps}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1",
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
            "-c:v",
            "h264_nvenc",
            "-preset",
            "p6",
            "-cq",
            "16",
            "-c:a",
            "copy",
            str(output_path),
        ]
    )


def atempo_filter(speed: float) -> str:
    """Build a valid FFmpeg atempo chain for speeds outside the 0.5 to 2.0 range."""
    if speed <= 0:
        raise PipelineError("Kecepatan audio harus lebih besar dari nol.")
    factors: list[float] = []
    while speed < 0.5:
        factors.append(0.5)
        speed /= 0.5
    while speed > 2.0:
        factors.append(2.0)
        speed /= 2.0
    factors.append(speed)
    return ",".join(f"atempo={factor:.8f}".rstrip("0").rstrip(".") for factor in factors)


def mux_final(
    silent_video: Path,
    source: Path,
    output: Path,
    config: dict[str, Any],
    slow_motion_factor: int = 1,
) -> None:
    print("VFI_STAGE mux", flush=True)
    ffmpeg = require_tool("ffmpeg")
    encoder = config.get("encoder", {})
    audio = config.get("audio", {})
    mute_audio = audio.get("mute", False)
    preserve_metadata = config.get("preserve_metadata", True)
    preserve_subtitles = config.get("preserve_subtitles", True)
    is_mp4 = output.suffix.lower() == ".mp4"
    slow_motion = slow_motion_factor > 1
    source_info = probe_video(source)
    silent_info = probe_video(silent_video)
    command = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-i",
        str(silent_video),
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-c:v",
        encoder.get("codec", "av1_nvenc"),
        "-preset",
        encoder.get("preset", "p6"),
        "-cq",
        str(encoder.get("cq", 18)),
        "-pix_fmt",
        encoder.get("pixel_format", "p010le"),
    ]
    video_filters: list[str] = []
    if (silent_info.width, silent_info.height) != (source_info.width, source_info.height):
        video_filters.append(f"scale={source_info.width}:{source_info.height}:flags=lanczos")
    if slow_motion:
        output_fps = silent_info.fps / slow_motion_factor
        video_filters.append(f"setpts={slow_motion_factor}*PTS")
        command.extend(["-r", f"{output_fps:.8f}"])
    if video_filters:
        command.extend(["-filter:v", ",".join(video_filters)])
    if not mute_audio:
        command.extend(["-map", "1:a?"])
    if preserve_metadata:
        command.extend(["-map_metadata", "1"])
    if mute_audio:
        command.append("-an")
        if is_mp4:
            command.extend(["-movflags", "+faststart"])
    elif slow_motion:
        command.extend(["-filter:a", atempo_filter(1 / slow_motion_factor), "-c:a", "aac", "-q:a", "2"])
    elif is_mp4:
        command.extend(["-c:a", "copy", "-movflags", "+faststart"])
    else:
        if preserve_subtitles and not slow_motion:
            command.extend(["-map", "1:s?", "-c:s", "copy"])
        command.extend(["-c:a", "copy" if audio.get("copy_for_mkv", True) else "aac"])
    command.extend(["-shortest", str(output)])
    try:
        run_command(command)
    except subprocess.CalledProcessError:
        if not is_mp4 or mute_audio or slow_motion:
            raise
        print("VFI_NOTICE source audio is not MP4-compatible; falling back to AAC", flush=True)
        fallback = list(command)
        audio_codec_index = fallback.index("-c:a") + 1
        fallback[audio_codec_index] = audio.get("mp4_fallback_codec", "aac")
        fallback[audio_codec_index + 1:audio_codec_index + 1] = ["-q:a", "2"]
        run_command(fallback)
    output_info = probe_video(output)
    if (output_info.width, output_info.height) != (source_info.width, source_info.height):
        output.unlink(missing_ok=True)
        raise PipelineError(
            "Resolusi output tidak cocok dengan input: "
            f"{output_info.width}x{output_info.height} != {source_info.width}x{source_info.height}"
        )


def interpolate_gmfss(
    input_path: Path,
    output_path: Path,
    target_fps: float,
    config: dict[str, Any],
    mode: str,
    scale: float,
    scene_threshold: float | None,
    static_threshold: float | None,
    temp_root: Path | None,
    keep_temp: bool,
    slow_motion_factor: int,
    uhd_mode: str,
    throttle_ms: int,
) -> None:
    profile_name = "gmfss_anime" if mode == "anime" else "gmfss_live_action"
    engine = config.get(profile_name) or config.get("gmfss", {})
    template = engine.get("command")
    if not isinstance(template, list) or not template:
        raise PipelineError("Isi gmfss.command di config.json dengan perintah implementasi GMFSS Anda.")
    temp_owner = None
    if temp_root:
        temp_root.mkdir(parents=True, exist_ok=True)
    if keep_temp:
        temp_dir = Path(tempfile.mkdtemp(prefix="anime-vfi-", dir=temp_root))
    else:
        temp_owner = tempfile.TemporaryDirectory(prefix="anime-vfi-", dir=temp_root)
        temp_dir = Path(temp_owner.name)
    info = probe_video(input_path)
    requested_scale = scale
    scale = resolve_motion_scale(info.width, info.height, requested_scale, uhd_mode)
    if uhd_mode == "memory" and scale != requested_scale:
        print("VFI_NOTICE memory-saver processing uses motion scale 0.5", flush=True)
    elif uhd_mode == "auto" and scale != requested_scale:
        print("VFI_NOTICE 4K input detected; using protected motion scale 0.5", flush=True)
    multiplier = round(target_fps / info.fps)
    if multiplier < 2 or abs(info.fps * multiplier - target_fps) > 0.02:
        raise PipelineError(
            "GMFSS membutuhkan pengali FPS integer. "
            "Gunakan --multiplier, misalnya --multiplier 10."
        )
    silent_video = temp_dir / f"gmfss_silent.{engine.get('output_extension', 'mp4')}"
    values = {
        "project_root": str(Path(__file__).resolve().parent),
        "input": str(input_path.resolve()),
        "output": str(silent_video.resolve()),
        "target_fps": f"{target_fps:.6f}".rstrip("0").rstrip("."),
        "multiplier": str(multiplier),
        "scale": str(scale),
        "temp_dir": str(temp_dir.resolve()),
    }
    cwd_value = engine.get("cwd")
    cwd = Path(str(cwd_value).format(**values)).resolve() if cwd_value else None
    print("VFI_STAGE interpolate", flush=True)
    command = render_template(template, values)
    validate_engine_command(command, cwd)
    if scene_threshold is not None:
        command.extend(["--scene-threshold", str(scene_threshold)])
    if static_threshold is not None:
        command.extend(["--static-threshold", str(static_threshold)])
    if throttle_ms > 0:
        command.extend(["--throttle-ms", str(throttle_ms)])
    try:
        run_command(command, cwd=cwd)
    except subprocess.CalledProcessError as exc:
        error_output = str(exc.output or "").lower()
        if "out of memory" in error_output and scale > 0.5:
            print("VFI_NOTICE GPU memory limit reached; retrying at motion scale 0.5", flush=True)
            silent_video.unlink(missing_ok=True)
            retry_values = dict(values)
            retry_values["scale"] = "0.5"
            retry_command = render_template(template, retry_values)
            if scene_threshold is not None:
                retry_command.extend(["--scene-threshold", str(scene_threshold)])
            if static_threshold is not None:
                retry_command.extend(["--static-threshold", str(static_threshold)])
            if throttle_ms > 0:
                retry_command.extend(["--throttle-ms", str(throttle_ms)])
            run_command(retry_command, cwd=cwd)
        elif "out of memory" in error_output:
            raise PipelineError("GPU VRAM tidak cukup untuk video ini. Gunakan 4K Processing Mode: Memory Saver.") from exc
        elif "--amp" not in command:
            raise
        else:
            print("VFI_NOTICE mixed precision failed; retrying with full precision", flush=True)
            silent_video.unlink(missing_ok=True)
            fallback_command = [argument for argument in command if argument != "--amp"]
            run_command(fallback_command, cwd=cwd)
    if not silent_video.exists():
        raise PipelineError(f"GMFSS tidak membuat output yang diharapkan: {silent_video}")
    silent_info = probe_video(silent_video)
    if (silent_info.width, silent_info.height) != (info.width, info.height):
        raise PipelineError(
            "Engine menghasilkan resolusi yang berbeda dari input: "
            f"{silent_info.width}x{silent_info.height} != {info.width}x{info.height}"
        )
    mux_final(silent_video, input_path, output_path, config, slow_motion_factor)
    if keep_temp:
        print(f"File sementara dipertahankan: {temp_dir}")
    if temp_owner:
        temp_owner.cleanup()


def doctor() -> None:
    checks = {
        "ffmpeg": shutil.which("ffmpeg"),
        "ffprobe": shutil.which("ffprobe"),
        "nvidia-smi": shutil.which("nvidia-smi"),
    }
    for name, path in checks.items():
        print(f"{name:12} {'OK' if path else 'MISSING':8} {path or ''}")
    if checks["nvidia-smi"]:
        result = run_command(
            [
                checks["nvidia-smi"],
                "--query-gpu=name,memory.total,driver_version",
                "--format=csv,noheader",
            ],
            capture=True,
        )
        print("GPU          ", result.stdout.strip())
    if not all(checks.values()):
        raise PipelineError("Lengkapi alat yang berstatus MISSING.")


def existing_file(value: str) -> Path:
    path = Path(value)
    if not path.is_file():
        raise argparse.ArgumentTypeError(f"File tidak ditemukan: {value}")
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pipeline interpolasi video anime berbasis GMFSS.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Periksa kesiapan sistem.")

    analyze_parser = sub.add_parser("analyze", help="Analisis scene dan held frame.")
    analyze_parser.add_argument("input", type=existing_file)
    analyze_parser.add_argument("--report", type=Path, default=Path("outputs/analysis.json"))
    analyze_parser.add_argument("--scene-threshold", type=float, default=0.32)
    analyze_parser.add_argument("--duplicate-threshold", type=int, default=768)

    run_parser = sub.add_parser("run", help="Jalankan interpolasi.")
    run_parser.add_argument("input", type=existing_file)
    run_parser.add_argument("output", type=Path)
    target_group = run_parser.add_mutually_exclusive_group()
    target_group.add_argument("--fps", type=float, help="FPS tujuan. Harus merupakan pengali integer FPS sumber.")
    target_group.add_argument("--multiplier", type=int, default=2, help="Pengali FPS. Nilai bawaan: 2.")
    run_parser.add_argument("--engine", choices=["gmfss", "preview"], default="gmfss")
    run_parser.add_argument("--mode", choices=["anime", "live-action"], default="anime")
    run_parser.add_argument("--scale", type=float, choices=[0.5, 0.75, 1.0], default=1.0)
    run_parser.add_argument("--scene-threshold", type=float)
    run_parser.add_argument("--static-threshold", type=float)
    run_parser.add_argument("--temp-dir", type=Path)
    run_parser.add_argument("--throttle-ms", type=int, choices=range(0, 101), default=0)
    run_parser.add_argument("--config", type=Path, default=Path("config.json"))
    run_parser.add_argument("--keep-temp", action="store_true")
    run_parser.add_argument(
        "--slow-motion-factor",
        type=int,
        choices=[1, 2, 4, 6, 8, 10],
        default=1,
        help="Perlambat video dengan membagi FPS hasil interpolasi. Nilai 1 menonaktifkan slow motion.",
    )
    run_parser.add_argument(
        "--uhd-mode",
        choices=["auto", "full", "memory"],
        default="auto",
        help="Strategi VRAM untuk video resolusi tinggi.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "doctor":
            doctor()
        elif args.command == "analyze":
            analyze(args.input, args.report, args.scene_threshold, args.duplicate_threshold)
        elif args.command == "run":
            root = Path(__file__).resolve().parent
            access_ok, access_message = verify_runtime_access(root, require_manifest=(root / "integrity-manifest.json").is_file())
            if not access_ok:
                raise PipelineError(f"Oniflow security check failed: {access_message}")
            args.output.parent.mkdir(parents=True, exist_ok=True)
            info = probe_video(args.input)
            target_fps = args.fps if args.fps is not None else info.fps * args.multiplier
            if target_fps <= info.fps:
                raise PipelineError("FPS tujuan harus lebih tinggi daripada FPS sumber.")
            if args.engine == "preview":
                interpolate_preview(args.input, args.output, target_fps)
            else:
                interpolate_gmfss(
                    args.input,
                    args.output,
                    target_fps,
                    load_config(args.config),
                    args.mode,
                    args.scale,
                    args.scene_threshold,
                    args.static_threshold,
                    args.temp_dir,
                    args.keep_temp,
                    args.slow_motion_factor,
                    args.uhd_mode,
                    args.throttle_ms,
                )
        return 0
    except (PipelineError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
