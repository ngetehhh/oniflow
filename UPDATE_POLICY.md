# Oniflow Update Policy

Oniflow can check an official update manifest published by Oniven.

Release packages must be signed and published through an official Oniven channel. Users should not install packages from unverified sources.

The updater must verify SHA256, show release notes, require user confirmation, and never upload videos or logs.

For GitHub Releases, publish:

1. `Oniflow-Setup-x.y.z-beta.exe`
2. `update.json`, based on `update_manifest.example.json`

Then set `update_config.json` to the raw `update.json` URL before building Oniflow.
