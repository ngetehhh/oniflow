# Oniflow Release Checklist

- Confirm written permission to distribute every model weight.
- Review GMFSS and dependency licenses with legal counsel.
- Replace the current GPL FFmpeg build or comply with its distribution obligations.
- Include source offers and notices required by bundled components.
- Test Anime and Human profiles on supported RTX generations.
- Test 720p, 1080p, 1440p, 4K, portrait, VFR, HDR, 8-bit, and 10-bit video.
- Test MP4, MKV, audio tracks, subtitles, metadata, pause, resume, stop, and recovery.
- Build the protected launcher with `build_native_release.ps1`.
- Sign the executable and installer. Self-signed certificates are acceptable only for private testing.
- Scan the release package for malware and secrets.
- Run `release_audit.py` and confirm that no logs, test videos, private paths, settings, cache, or Git metadata are included.
- Run `python -m pip check` and `python -m pip_audit` against the final bundled runtime.
- Test the release on a clean Windows computer that has no Python installation.
- Verify EULA, privacy policy, version, support links, and update policy.
