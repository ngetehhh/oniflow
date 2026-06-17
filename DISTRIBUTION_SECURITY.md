# Oniflow Distribution Security

Python packaging does not prevent determined reverse engineering.

Before commercial release:

1. Sign the executable and installer with a trusted code-signing certificate.
2. Publish SHA-256 checksums through an official Oniven channel.
3. Keep private signing keys outside the source repository.
4. Use Nuitka or another reviewed compilation method for proprietary application code.
5. Store model files in a documented package with integrity checks.
6. Do not claim that encryption makes model extraction impossible.
7. Scan every release package for secrets and malware.
8. Run `release_audit.py` before every release.
9. Never distribute development logs, test videos, Git metadata, user settings, or a relocatable virtual environment that still references the build computer.
10. Never distribute `private/offline-license-private.json`, `offline_license_admin.py`, `buat_offline_license.ps1`, or generated license files.
11. Treat a missing or failed signed integrity manifest as a compromised installation.
12. The signed manifest increases tamper resistance. It does not make local software impossible to reverse engineer.
13. Use `build_native_release.ps1` for the native Nuitka launcher.
14. A self-signed certificate does not remove Windows SmartScreen warnings and is suitable only for private testing.

Model distribution rights must be confirmed before adding protection or selling the package.
