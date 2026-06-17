# Oniflow Activation Server

This server records access codes, activated devices, Pro expiration dates, and daily free clip usage.

## Local Test

Start the server:

```powershell
& ".\jalankan_server_aktivasi.ps1"
```

Enter an admin password when requested. Open `http://127.0.0.1:8765/admin` and sign in with that password.

The dashboard provides statistics, code creation, code enable or disable controls, registered devices, Pro revocation, device deletion, and recent activation records.

Create a code for one device and 30 days:

```powershell
& "work\gmfss-venv\Scripts\python.exe" activation_admin.py create --days 30 --devices 1
```

Create a custom code:

```powershell
& "work\gmfss-venv\Scripts\python.exe" activation_admin.py create --days 30 --devices 1 --code ONIVEN-FRIEND-30D
```

You can run this helper from any PowerShell directory:

```powershell
& "C:\Users\user\Documents\Codex\2026-06-13\saya-ingin-membuat-video-interpolation-yang\buat_kode_aktivasi.ps1" -Code "ONIVEN-FRIEND-30D" -Days 30 -Devices 1
```

List codes:

```powershell
& "work\gmfss-venv\Scripts\python.exe" activation_admin.py list
```

Disable or enable a code:

```powershell
& "work\gmfss-venv\Scripts\python.exe" activation_admin.py disable ONIVEN-FRIEND-30D
& "work\gmfss-venv\Scripts\python.exe" activation_admin.py enable ONIVEN-FRIEND-30D
```

For local testing, set `server_url` in `activation_config.json` to:

```json
{
  "server_url": "http://127.0.0.1:8765"
}
```

## Sharing With Friends

Run the server on a computer or cloud host that remains online. Use HTTPS. Replace `server_url` with the public HTTPS address before building the application.

Do not distribute `activation.db`, `activation_admin.py`, or the server files with the client application.

The local test address only works on your computer. Friends need a public HTTPS server address.

## Same-Network Friend Test

The current test client is configured for `http://192.168.1.6:8765`.

Run `siapkan_firewall_server.ps1` once from PowerShell as Administrator. Start the server with
`jalankan_server_aktivasi.ps1`. Friends must use the same router or Wi-Fi network.

The LAN address may change after restarting the router. Update `activation_config.json` and rebuild the installer
when the address changes.
