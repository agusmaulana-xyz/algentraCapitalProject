# EA Telegram Signal

Backend untuk sistem copy trading Telegram dengan FastAPI, SQLite, parser Gemini, login Telegram via Telethon, REST API untuk EA MT5, dan dashboard web admin.

## Menjalankan backend

1. Gunakan Python 3.11 atau lebih baru.
2. Dari folder proyek, salin `.env.example` menjadi `.env`, lalu ganti `APP_SECRET_KEY` dengan nilai acak minimal 32 karakter dan ganti `ADMIN_PASSWORD` dengan password minimal 12 karakter.
3. Buat virtual environment (`python -m venv .venv` di Windows atau `python3 -m venv .venv` di Linux/macOS), lalu pasang dependensi dengan `.venv\Scripts\python -m pip install -r backend/requirements.txt` di Windows atau `.venv/bin/python -m pip install -r backend/requirements.txt` di Linux/macOS.
4. Jalankan `run.bat` di Windows atau `./run.sh` di Linux/macOS. Backend bind ke `127.0.0.1:8000`.
5. Buka `http://127.0.0.1:8000/login` dan masuk memakai kredensial dari `.env`.
6. Isi `GEMINI_API_KEY` di `.env` untuk mengaktifkan Gemini. Model default `gemini-3.8-flash` dapat diganti lewat `GEMINI_MODEL`; regex fallback mati kecuali `ENABLE_REGEX_FALLBACK=true`.
7. Untuk Telegram, isi `TELEGRAM_API_ID` dan `TELEGRAM_API_HASH` dari [my.telegram.org](https://my.telegram.org), lalu restart backend dan buka `/telegram-setup` setelah login admin.

Database SQLite dibuat otomatis di `backend/data/app.db`. Password admin disimpan sebagai hash bcrypt. Saat backend mulai, password admin di `.env` disinkronkan ke database, jadi perubahan password berlaku setelah server direstart. Endpoint dashboard memerlukan cookie sesi admin; gunakan login melalui halaman web terlebih dahulu.

## Endpoint M1

- `GET /health`
- `POST /api/auth/login` dan `POST /api/auth/logout`
- `GET /api/stats`
- `GET /api/signals?limit=100&offset=0`
- `GET /api/logs?limit=100&offset=0&level=INFO&search=...`
- `GET /api/settings` dan `PUT /api/settings` dengan body `{"values":{"confidence_threshold":0.75}}`
- `POST /api/parser/test` untuk menguji klasifikasi dan validasi. Halaman admin tersedia di `/parser-test`.
- Telegram: `GET /api/tg/status`, `POST /api/tg/send-code`, `POST /api/tg/verify-code`, `POST /api/tg/verify-2fa`, `POST /api/tg/logout`, `POST /api/tg/reconnect`, `GET /api/tg/groups`, dan `POST /api/tg/groups/select`.
- EA: `GET /api/ea/pending`, `POST /api/ea/report`, `POST /api/ea/result`, dan `POST /api/ea/heartbeat` memakai header `X-API-Key` yang nilainya sama dengan `EA_API_KEY`.

## Dashboard M5

Setelah login admin, buka `/dashboard` untuk melihat statistik signal dan trade, heartbeat EA, status Telegram/Gemini, signal terbaru, statistik grup, grafik profit, log, dan riwayat trade. WebSocket `/ws` mengirim pembaruan berkala; dashboard mencoba menyambung ulang otomatis. Log dan riwayat trade dapat difilter serta diekspor ke CSV. Halaman settings saat ini mengatur confidence, symbol default/mapping, demo mode, update signal, kill switch, dan konfigurasi Gemini. Chart.js dimuat dari CDN sehingga grafik memerlukan akses jaringan browser.

Endpoint dashboard (semuanya memerlukan sesi admin): `GET /api/stats`, `GET /api/signals`, `GET /api/groups/stats`, `GET /api/logs`, `GET /api/logs/export.csv`, `GET /api/trades`, `GET /api/trades/export.csv`, `GET/PUT /api/settings`, `PUT /api/settings/gemini-config`, serta `WS /ws`.

## Uji login Telegram manual

1. Buat API ID dan API hash pada `my.telegram.org`, simpan di `.env`, dan restart backend.
2. Login admin di `/login`, lalu buka `/telegram-setup`.
3. Masukkan nomor telepon dengan kode negara, minta kode, lalu masukkan kode yang diterima di aplikasi Telegram.
4. Jika akun memakai 2FA, masukkan password 2FA. Status harus berubah ke `connected`.
5. Muat daftar grup/channel, aktifkan whitelist yang diinginkan, isi alias bila perlu, lalu simpan.
6. Kirim pesan uji di salah satu grup whitelist dan periksa hasil di API `/api/signals` dan `/api/logs`.

Session Telethon berada di `backend/data/telegram_user.session`, tidak disajikan oleh FastAPI, dan folder `backend/data` masuk `.gitignore`. Logout dari halaman Telegram Setup mencabut session yang tersimpan.

## Memasang EA MT5

1. Buat `EA_API_KEY` acak minimal 24 karakter di `.env`, restart backend, lalu buka `mt5/TelegramSignalEA.mq5` di MetaEditor.
2. Compile dengan **F7**. Salin file ke `MQL5/Experts` bila MetaEditor tidak membukanya langsung dari folder proyek.
3. Di MT5, buka **Tools > Options > Expert Advisors**, aktifkan **Allow WebRequest for listed URL**, lalu tambahkan persis `http://127.0.0.1:8000`.
4. Pasang EA ke chart akun demo, isi `ApiKey` dengan nilai `EA_API_KEY`, dan biarkan `DemoMode=true`. Backend juga memulai `demo_mode=true`.
5. Periksa tab Experts/Journal untuk heartbeat, status koneksi, dan laporan signal.

`GET /api/ea/pending` mengklaim signal selama 90 detik. EA menyimpan penanda idempotensi lokal dan mengirim ulang laporan bila perlu agar polling/restart tidak membuat order ganda. EA memakai TP pertama bila signal berisi beberapa TP.

## Test

Jalankan dari folder proyek: `.venv\Scripts\python -m pytest backend/tests` di Windows atau `.venv/bin/python -m pytest backend/tests` di Linux/macOS.

## Belum teruji

Koneksi Gemini dan Telegram dengan akun/kredensial sungguhan belum diuji. Kode EA belum dikompilasi di MetaEditor dan belum diuji pada terminal atau akun demo; validasi itu memerlukan MetaEditor/MT5 di Windows.
