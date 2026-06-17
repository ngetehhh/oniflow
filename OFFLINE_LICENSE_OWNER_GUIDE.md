# Oniflow Offline License Owner Guide

Keep `private/offline-license-private.json` private. Back it up securely. Never send this file to users.

## Create a License

Ask the user to open Oniflow and send the Device ID shown on the license screen.

Cara paling mudah:

1. Buka `Buat Lisensi Oniflow.vbs`.
2. Masukkan Device ID dan nama pengguna.
3. Pilih masa berlaku.
4. Klik `Buat Lisensi`.
5. Kirim hanya file JSON yang dibuat di `generated-licenses`.

Cara PowerShell tetap tersedia untuk otomatisasi.

Create a permanent license:

```powershell
.\buat_offline_license.ps1 -DeviceId "DEVICE-ID-HERE" -Name "Friend Name"
```

Create a license that expires after 30 days:

```powershell
.\buat_offline_license.ps1 -DeviceId "DEVICE-ID-HERE" -Name "Friend Name" -Days 30
```

Send only the generated JSON file from `generated-licenses` to the user. The user imports it through the Oniflow license screen.

## Security Rules

- Never send the `private` folder.
- Never include `offline_license_admin.py` or `buat_offline_license.ps1` in a public release.
- One license works only on the Device ID used when creating it.
- Generate a new license if the user's Device ID changes.
- Losing the private key prevents you from creating compatible licenses for existing releases.
