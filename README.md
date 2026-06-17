# Oniflow

Oniflow is a Windows video frame interpolation application created by Oniven. It provides separate Anime and Human profiles powered by GMFSS, scene-change protection, held-frame protection, slow motion, queue processing, and NVENC output.

## Main Features

- Automatic NVIDIA GPU, VRAM, driver, and NVENC detection at startup.
- Anime and Human interpolation profiles.
- 2x, 4x, 6x, 8x, and 10x FPS multiplication.
- Optional slow motion without changing the interpolated frame count.
- Fast, Normal, and Quality interpolation presets.
- Automatic source-resolution preservation, including 4K input.
- MP4 and MKV output with AV1, HEVC, or H.264 NVENC.
- Pause, resume, stop, process status, progress, ETA, and session logs.
- Job size estimates and friendly error messages.

## Run From Source

```powershell
.\buka_anime_vfi.ps1
```

Drop videos or folders into the application. The output directory follows the first dropped input by default and remains editable.

## Compatibility Check

```powershell
& work\gmfss-venv\Scripts\python.exe compatibility_check.py
```

The check reports required tools, release documents, available NVENC encoders, and detected NVIDIA GPU details.

## Tests

```powershell
& work\gmfss-venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Portable Release

```powershell
.\build_release.ps1
```

The script creates `dist\Oniflow`. It bundles the GUI, pipeline, Python environment, GMFSS backend, FFmpeg tools, configuration, and product documents.

## Windows Installer

Install Inno Setup, create the portable release, then compile `installer.iss` with `ISCC.exe`. Review `RELEASE_CHECKLIST.md` before distribution.

## GitHub Updates

Publish each installer through a GitHub Release. Upload the installer and a JSON manifest based on `update_manifest.example.json`.

Set `update_config.json` to the raw manifest URL before building the release. Oniflow checks that manifest, downloads the installer, verifies SHA256, and starts the updater.

## Commercial Release Notice

Confirm written permission to distribute all model weights before selling Oniflow. Review every dependency and the bundled FFmpeg build with qualified legal counsel. The current project documents are drafts and do not replace legal advice.
