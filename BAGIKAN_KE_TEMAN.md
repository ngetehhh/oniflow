# Membagikan Oniflow Kepada Teman

Paket ini disiapkan untuk pengujian bersama teman yang menggunakan jaringan Wi-Fi atau router yang sama.

## Sebelum Teman Membuka Oniflow

1. Jalankan PowerShell sebagai Administrator.
2. Jalankan `siapkan_firewall_server.ps1` satu kali.
3. Jalankan `jalankan_server_aktivasi.ps1`.
4. Buat password admin ketika diminta.
5. Biarkan jendela PowerShell server tetap terbuka.
6. Buka dashboard di `http://127.0.0.1:8765/admin`.

## File Yang Dibagikan

Bagikan hanya:

`installer-output\Oniflow-Setup-0.9.3-beta.exe`

Jangan bagikan folder proyek, `activation.db`, password admin, atau file server aktivasi.

## Penggunaan Oleh Teman

1. Teman harus tersambung ke jaringan yang sama dengan komputer server.
2. Teman menginstal Oniflow menggunakan installer.
3. Teman membuka Oniflow.
4. Oniflow akan terhubung ke `http://192.168.1.6:8765`.
5. Buat access code dari dashboard admin dan berikan kepada teman bila ingin mengaktifkan Pro.

## Catatan

Alamat IP `192.168.1.6` dapat berubah setelah router atau komputer dimulai ulang. Jika berubah, perbarui
`activation_config.json`, lalu bangun ulang release dan installer.

Pengujian LAN ini tidak memakai HTTPS. Gunakan hosting publik dengan HTTPS sebelum membagikan Oniflow kepada
pengguna di luar jaringan pribadi.
