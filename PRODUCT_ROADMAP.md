# Oniflow Product Roadmap

## Status saat ini

Oniflow memiliki dua profil GMFSS Union, antrean video, drag and drop,
progress bar nyata, ETA, log proses, pembatalan proses, monitor GPU, perlindungan
scene cut, perlindungan held frame, AV1 NVENC 10-bit, dan output batch.

## Target performa

Kecepatan harus diukur menggunakan video uji yang sama, resolusi yang sama,
pengali FPS yang sama, dan preset kualitas yang setara. Klaim lebih cepat dari
SVFI belum boleh digunakan sebelum benchmark tersebut selesai.

Urutan optimasi:

1. Buat worker persisten agar model tidak dimuat ulang untuk setiap video.
2. Pisahkan decode, inferensi, dan encode menjadi pipeline paralel.
3. Profilkan GMFlow, softsplat, IFNet, dan FusionNet pada RTX 5070 Ti.
4. Konversi komponen yang kompatibel ke ONNX dan TensorRT.
5. Gunakan FP16 hanya setelah seluruh grafik lolos uji konsistensi numerik.
6. Tambahkan benchmark otomatis untuk Anime dan Human.

## Target produk

Sebelum distribusi komersial:

1. Tentukan nama, merek, ikon, dan identitas visual final.
2. Buat installer Windows dan proses uninstall.
3. Tambahkan validasi model, pemeriksaan update, dan pemulihan proses gagal.
4. Tambahkan pengaturan encoder, lokasi cache, dan batas penggunaan VRAM.
5. Uji video VFR, HDR, subtitle, audio multitrack, 4K, dan file rusak.
6. Lakukan audit lisensi kode, model, FFmpeg, codec, dan aset visual.
7. Buat kebijakan privasi, EULA, dokumentasi pengguna, dan kanal dukungan.
