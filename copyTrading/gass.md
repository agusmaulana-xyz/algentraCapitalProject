# PROMPT: Bangun Sistem Copy Trade MT5 (1 Master, Banyak Follower, 1 VPS Windows)

Kamu adalah senior Python engineer yang berpengalaman dengan MetaTrader 5 dan sistem trading otomatis. Bangun project lengkap sesuai spesifikasi di bawah. Kerjakan secara bertahap, jalankan tes di setiap tahap, dan jangan lanjut ke tahap berikutnya sebelum tahap sebelumnya lolos.

---

## 1. Tujuan

Bangun sistem **copy trade** di satu VPS Windows:

- **Akun master**: berjalan di aplikasi MT5 biasa. Trade di akun ini bisa manual atau dari EA apa pun. Sistem **tidak boleh mengubah atau bergantung pada cara trade dibuat** di master.
- **Akun follower (N akun)**: setiap akun dikendalikan lewat package Python `MetaTrader5`. Setiap kali master membuka, mengubah, mengurangi, atau menutup posisi, semua follower harus meniru hal yang sama sesegera mungkin.
- Semua follower harus aktif dan siap menerima sinyal sepanjang waktu.

## 2. Batasan teknis yang WAJIB dipatuhi

Ini fakta tentang package `MetaTrader5` yang menentukan arsitektur. Jangan dilanggar:

1. Package `MetaTrader5` menyimpan koneksi sebagai state global **per proses**. Satu proses Python hanya bisa terhubung ke **satu terminal** pada satu waktu. Threading tidak menyelesaikan ini.
2. Satu terminal MT5 hanya login ke **satu akun**.
3. Maka: **satu akun = satu folder terminal MT5 (mode `/portable`) = satu proses Python.**
4. Package ini **tidak bisa** memasang EA ke chart, membuka chart, atau compile `.mq5`. Jangan mencoba.
5. Package ini hanya berjalan di Windows, dan butuh terminal MT5 yang sudah terpasang.
6. `order_send()` hanya berhasil jika "Algo Trading" menyala di terminal dan opsi "Allow algorithmic trading" aktif.

## 3. Arsitektur

```
Master MT5 terminal
      │ (dipantau)
      ▼
master_publisher.py ──► tulis sinyal ke folder bersama (JSONL per hari)
                                   │
        ┌──────────────────────────┼──────────────────────────┐
        ▼                          ▼                          ▼
 follower.py akun1.json     follower.py akun2.json     follower.py akunN.json
        │                          │                          │
 Terminal MT5 #1            Terminal MT5 #2            Terminal MT5 #N

launcher.py (supervisor/watchdog) menjalankan dan menjaga semua proses di atas.
```

Transport sinyal: **file JSONL di folder bersama** (path bisa diatur di config). Satu baris = satu sinyal. File baru per hari: `sinyal_YYYYMMDD.jsonl`. Tulis satu baris lalu langsung tutup file. Follower membaca dengan melacak offset byte, bukan membaca ulang seluruh file.

## 4. Struktur project

```
copytrade-mt5/
├── README.md
├── requirements.txt
├── .gitignore                  # wajib mengabaikan config/*.json berisi password dan .env
├── config/
│   ├── master.example.json
│   ├── follower.example.json
│   └── launcher.example.json
├── src/
│   └── copytrade/
│       ├── __init__.py
│       ├── protocol.py         # skema sinyal + validasi
│       ├── signal_io.py        # tulis sinyal (master), baca sinyal berdasarkan offset (follower)
│       ├── master_publisher.py
│       ├── follower.py
│       ├── lot_calc.py         # hitung dan normalisasi lot
│       ├── symbol_map.py
│       ├── state.py            # simpan pemetaan + offset ke disk (atomic write)
│       ├── logging_setup.py
│       └── launcher.py
├── scripts/
│   ├── start_all.bat
│   └── install_startup_task.ps1   # buat Task Scheduler "At startup"
└── tests/
    ├── test_protocol.py
    ├── test_lot_calc.py
    ├── test_signal_io.py
    ├── test_follower_logic.py   # dengan mock MetaTrader5
    └── conftest.py
```

Gunakan Python 3.10+, type hints, `dataclasses`, dan modul `logging` (bukan `print`). Dependensi minimal: `MetaTrader5`, `pytest`. Hindari dependensi lain kecuali benar-benar perlu.

## 5. Protokol sinyal

Setiap baris JSONL adalah satu objek:

```json
{
  "v": 1,
  "id": "1760000000000-17",
  "ts": 1760000000.123,
  "aksi": "buka",
  "pos_id": 123456789,
  "simbol": "XAUUSD",
  "arah": "buy",
  "lot": 0.10,
  "harga": 2650.12,
  "sl": 2645.00,
  "tp": 2660.00,
  "komentar": ""
}
```

Nilai `aksi` yang valid:

| aksi | arti | field wajib |
|---|---|---|
| `buka` | posisi baru dibuka di master | pos_id, simbol, arah, lot, sl, tp |
| `ubah` | SL/TP posisi berubah | pos_id, sl, tp |
| `kurang` | sebagian posisi ditutup (partial close) | pos_id, lot (lot yang ditutup), lot_sisa |
| `tutup` | posisi ditutup penuh | pos_id |

Aturan:
- `id` unik dan naik terus (timestamp ms + counter). `ts` adalah epoch detik.
- Gunakan **position ID** (`TradePosition.identifier`) di semua aksi, bukan ticket order.
- `protocol.py` harus punya fungsi parse + validasi yang menolak sinyal rusak dengan error jelas, bukan crash.

## 6. master_publisher.py

Tugas: mengawasi akun master dan menulis sinyal. **Tidak boleh membuka, mengubah, atau menutup order apa pun.**

- Panggil `mt5.initialize(path=...)` **tanpa login**, supaya menempel ke terminal master yang sudah login. Path diambil dari config.
- Loop polling `mt5.positions_get()` setiap `poll_interval_ms` (default 50 ms). Bandingkan dengan snapshot sebelumnya berdasarkan `identifier`:
  - ada ID baru → sinyal `buka`
  - ID sama tapi `sl` atau `tp` berubah → sinyal `ubah`
  - ID sama tapi `volume` berkurang → sinyal `kurang`
  - ID hilang dari daftar → sinyal `tutup`
- Saat start, ambil snapshot awal dan **jangan** mengirim sinyal `buka` untuk posisi yang sudah ada. Posisi lama dianggap baseline.
- Filter opsional di config: `filter_magic` (daftar magic number), `filter_simbol`, `abaikan_komentar_mengandung`. Jika filter kosong, semua posisi dicopy.
- Jika `positions_get()` mengembalikan `None`, catat error dari `mt5.last_error()`, coba lagi, dan **jangan** menganggap semua posisi hilang (itu akan memicu sinyal `tutup` palsu untuk semua follower). Hanya anggap daftar valid jika bukan `None`.
- Jika koneksi terminal terputus (`mt5.terminal_info().connected` bernilai False), jangan kirim sinyal apa pun sampai pulih. Setelah pulih, bandingkan snapshot lalu kirim selisihnya.
- Tangani Ctrl+C dengan rapi (`mt5.shutdown()`).

## 7. follower.py

Dijalankan sebagai: `python -m copytrade.follower config/akun1.json`

### 7.1 Config follower

```json
{
  "nama": "akun1",
  "terminal_path": "C:\\MT5_F1\\terminal64.exe",
  "login": 12345678,
  "password_env": "MT5_PASS_AKUN1",
  "server": "NamaBroker-Server",
  "folder_sinyal": "C:\\Users\\Administrator\\AppData\\Roaming\\MetaQuotes\\Terminal\\Common\\Files",
  "map_simbol": { "XAUUSD": "XAUUSDm" },
  "mode_lot": "rasio",
  "rasio_lot": 1.0,
  "lot_tetap": 0.01,
  "max_lot_per_order": 5.0,
  "max_umur_sinyal_buka_detik": 3,
  "deviation_poin": 20,
  "magic": 880001,
  "komentar": "copy",
  "arah_terbalik": false,
  "polling_ms": 20,
  "aktif": true
}
```

Password **tidak boleh** disimpan plaintext di config. Ambil dari environment variable bernama `password_env`. Jika env tidak ada, hentikan dengan pesan error yang jelas.

### 7.2 Perilaku

1. `mt5.initialize(path, login, password, server)`. Cek hasilnya. Jika gagal, log `mt5.last_error()` dan coba ulang dengan backoff (1s, 2s, 5s, 10s, maksimum 30s).
2. Validasi saat start, lalu log hasilnya:
   - `account_info().margin_mode` harus **hedging** (`ACCOUNT_MARGIN_MODE_RETAIL_HEDGING`). Jika netting, tampilkan peringatan keras bahwa pemetaan satu posisi ke satu ticket tidak akan akurat, dan hentikan kecuali `izinkan_netting: true`.
   - `terminal_info().trade_allowed` harus True. Jika tidak, log error jelas: "Algo Trading belum menyala di terminal".
   - Simbol hasil mapping harus ada. Panggil `symbol_select(simbol, True)` agar muncul di Market Watch.
3. Muat state dari disk (pemetaan `pos_id_master -> ticket_follower`, dan offset file sinyal terakhir). Jika state tidak ada, mulai dari **akhir** file sinyal hari ini (jangan memproses sinyal lama).
4. Loop: baca baris baru dari file sinyal sejak offset. Tangani pergantian hari (pindah ke file hari berikutnya, selesaikan sisa file lama dulu). Setiap sinyal diproses **tepat satu kali** (cek `id` di set `terproses` yang dipersist).
5. Tangani per aksi:
   - **buka**: 
     - Jika `now - ts` melebihi `max_umur_sinyal_buka_detik`, **lewati** dan log "sinyal buka kedaluwarsa". Entry yang terlambat tidak boleh dikejar.
     - Hitung lot lewat `lot_calc` (lihat bagian 8).
     - Kirim `order_send` tipe `TRADE_ACTION_DEAL` ke harga pasar saat ini (ask untuk buy, bid untuk sell), dengan sl, tp, deviation, magic, dan komentar.
     - Deteksi `type_filling` yang didukung simbol (dari `symbol_info().filling_mode`), bukan di-hardcode. Coba urutan FOK → IOC → RETURN sesuai yang didukung.
     - Jika berhasil, simpan pemetaan `pos_id_master -> ticket/position follower`. Ambil ID posisi follower dari `result.order` lalu verifikasi lewat `positions_get(ticket=...)`.
     - Validasi level SL/TP terhadap `symbol_info().trade_stops_level` dan `freeze_level`. Jika SL/TP terlalu dekat, sesuaikan ke jarak minimum dan log peringatan, jangan gagal total.
   - **ubah**: cari ticket lewat pemetaan; jika ada, kirim `TRADE_ACTION_SLTP`. Jika pemetaan tidak ada (posisi dulu dilewati), abaikan dengan log tingkat info.
   - **kurang**: tutup sebagian volume follower secara proporsional (`lot_follower * lot_ditutup / lot_awal_master`), dinormalisasi ke `volume_step`, tidak boleh di bawah `volume_min` (jika sisa akan di bawah minimum, tutup penuh).
   - **tutup**: tutup posisi follower, hapus dari pemetaan.
   - **Aksi `ubah`, `kurang`, `tutup` TIDAK terkena aturan kedaluwarsa.** Mereka harus selalu diproses supaya follower tidak menggantung setelah master menutup.
6. Tangani `retcode` dengan benar. Retry (maksimal 3 kali, jeda singkat) hanya untuk `TRADE_RETCODE_REQUOTE`, `TRADE_RETCODE_PRICE_CHANGED`, `TRADE_RETCODE_TIMEOUT`, `TRADE_RETCODE_CONNECTION`. Untuk `TRADE_RETCODE_NO_MONEY`, `TRADE_RETCODE_MARKET_CLOSED`, `TRADE_RETCODE_TRADE_DISABLED`, `TRADE_RETCODE_INVALID_VOLUME`, jangan retry; log lalu lanjut. Log setiap hasil beserta `retcode` dan `comment`.
7. **Rekonsiliasi saat start dan setiap 30 detik**: jika ada ticket di pemetaan yang sudah tidak ada di `positions_get()` (misalnya kena SL/TP lebih dulu di follower), hapus dari pemetaan. Posisi dengan magic follower yang tidak ada di pemetaan hanya dicatat, tidak ditutup otomatis.
8. Kalau terminal terputus di tengah jalan: log, jangan crash, coba `initialize` ulang dengan backoff. Sinyal `buka` yang masuk selama terputus akan otomatis kedaluwarsa dan dilewati.
9. Fungsi `heartbeat`: tulis file `heartbeat_<nama>.txt` berisi timestamp tiap 5 detik, supaya launcher bisa mendeteksi proses yang macet (hidup tapi tidak berjalan).

## 8. lot_calc.py

Mode lot:
- `tetap`: pakai `lot_tetap`.
- `rasio`: `lot_master * rasio_lot`.
- `saldo` (opsional): `lot_master * (saldo_follower / saldo_master)`, dengan saldo master dibaca dari config statis.

Normalisasi wajib: bulatkan ke bawah ke kelipatan `volume_step`, terapkan `volume_min` dan `volume_max` dari `symbol_info`, lalu batasi `max_lot_per_order`. Jika hasil di bawah `volume_min`, **lewati order** dan log alasannya, jangan dipaksa ke minimum. Buat tes unit untuk kasus tepi (step 0.01, step 0.1, hasil di bawah minimum, melebihi maksimum).

## 9. launcher.py (supervisor)

Config `launcher.json` berisi path config master dan daftar config follower.

- Jalankan master_publisher dan setiap follower sebagai **subprocess terpisah**.
- Cek setiap 5 detik: jika proses mati (exit code apapun) atau heartbeat lebih tua dari 30 detik, matikan lalu jalankan ulang dengan backoff. Batasi maksimal 10 restart per 10 menit per proses; jika terlampaui, beri status "gagal permanen" dan log error keras.
- Opsional: jika terminal MT5 dari suatu follower tidak berjalan, launcher bisa menjalankan `terminal64.exe /portable` lebih dulu.
- Log status ringkas semua proses setiap 60 detik.
- Matikan semua anak proses dengan rapi saat menerima Ctrl+C.
- Sediakan `scripts/install_startup_task.ps1` yang membuat scheduled task "At startup" untuk menjalankan launcher dengan hak tertinggi, dan `scripts/start_all.bat` untuk uji manual.

## 10. Logging dan state

- Log per proses ke `logs/<nama>.log` dengan rotasi (`RotatingFileHandler`, 5 MB x 5 file). Format: waktu, level, nama, pesan.
- Setiap sinyal yang diproses dicatat satu baris: id, aksi, hasil (sukses / lewati / gagal) dan alasan.
- State disimpan ke `state/<nama>.json` dengan **atomic write** (tulis ke file sementara lalu `os.replace`), supaya tidak rusak saat proses mati mendadak.

## 11. Keamanan dan keselamatan

- Jangan hardcode kredensial. Jangan log password.
- Sediakan flag `dry_run: true` di config follower: semua logika berjalan, tetapi `order_send` diganti log saja. Default `dry_run` bernilai **true** pada contoh config.
- Tambahkan batas pengaman di follower: `max_posisi_terbuka` dan `max_lot_total`. Jika terlampaui, lewati sinyal `buka` baru dan log peringatan.
- Dokumentasikan di README bahwa semua pengujian awal harus di **akun demo**.

## 12. Pengujian

- Buat mock untuk modul `MetaTrader5` (di `conftest.py`) sehingga tes berjalan tanpa terminal asli.
- Tes minimal:
  - parsing dan validasi protokol (sinyal valid, rusak, field kurang)
  - `signal_io`: membaca dengan offset, pergantian hari, baris setengah jadi di akhir file tidak boleh diproses
  - `lot_calc`: semua kasus tepi
  - logika diff snapshot di master (baru, ubah, kurang, tutup, `None` dari `positions_get`)
  - follower: sinyal buka kedaluwarsa dilewati; `ubah/kurang/tutup` tetap diproses walau lama; idempotensi (sinyal yang sama dua kali hanya diproses sekali); pemulihan state setelah restart
- Jalankan `pytest` dan pastikan semuanya hijau sebelum menyatakan selesai.

## 13. Urutan pengerjaan (kerjakan berurutan)

1. Kerangka project, `requirements.txt`, `.gitignore`, config contoh.
2. `protocol.py`, `signal_io.py`, `state.py`, `lot_calc.py`, `symbol_map.py`, beserta tes.
3. `master_publisher.py` beserta tes diff snapshot.
4. `follower.py` (dengan `dry_run` dulu) beserta tes dengan mock.
5. `launcher.py`, `scripts/`, `logging_setup.py`.
6. `README.md`.
7. Jalankan seluruh tes, perbaiki, lalu tulis ringkasan akhir.

## 14. README.md harus memuat

- Diagram arsitektur dan penjelasan singkat kenapa satu akun = satu terminal = satu proses.
- Cara menyiapkan banyak terminal: copy folder MT5, jalankan dengan `/portable`, login, nyalakan Algo Trading, dan centang "Allow algorithmic trading".
- Cara mengisi config dan mengatur environment variable password.
- Cara menjalankan: uji `dry_run`, lalu live di akun demo, lalu live sebenarnya.
- Cara menambah follower baru (copy folder terminal, buat satu file JSON, tambahkan ke config launcher).
- Checklist "follower siap menerima sinyal".
- Keterbatasan: latensi dan slippage membuat hasil follower **mirip, bukan identik**; perbedaan spread, nama simbol, dan lot minimum antar broker; aturan broker atau prop firm tentang copy trading dan banyak akun dari IP yang sama.
- Pemecahan masalah umum (retcode 10027 autotrading dinonaktifkan, 10030 filling mode tidak didukung, 10014 volume tidak valid, dll.).

## 15. Kriteria selesai

- Semua tes `pytest` lolos.
- Dengan mock: master mengirim `buka`, `ubah`, `kurang`, `tutup` dan 3 follower mock memprosesnya dengan benar dan masing-masing menghasilkan pemetaan yang konsisten.
- Menambah follower baru hanya butuh satu file JSON baru, tanpa mengubah kode.
- Tidak ada kredensial di repo.
- README cukup jelas sehingga orang lain bisa memasang sistem ini di VPS baru.

## 16. Hal yang TIDAK boleh dilakukan

- Jangan menggabungkan dua akun dalam satu proses Python.
- Jangan memproses sinyal `buka` yang sudah kedaluwarsa.
- Jangan menutup posisi follower yang tidak ada di pemetaan.
- Jangan mengirim sinyal `tutup` hanya karena `positions_get()` mengembalikan `None`.
- Jangan menambah fitur di luar spesifikasi ini tanpa diminta. Jika ada keputusan yang ambigu, pilih opsi paling aman, tuliskan asumsinya di README, dan lanjutkan.