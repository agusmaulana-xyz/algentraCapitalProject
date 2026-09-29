# EA Telegram Signal

Backend awal untuk sistem copy trading Telegram. M1 menyediakan kerangka FastAPI, database SQLite, login admin, dan endpoint statistik, signal, log, serta settings. Proses Telegram, parsing Gemini, EA MT5, dan dashboard lengkap dikerjakan pada milestone berikutnya.

## Menjalankan backend

1. Gunakan Python 3.11 atau lebih baru.
2. Dari folder proyek, salin `.env.example` menjadi `.env`, lalu ganti `APP_SECRET_KEY` dengan nilai acak minimal 32 karakter dan ganti `ADMIN_PASSWORD` dengan password minimal 12 karakter.
3. Buat virtual environment (`python -m venv .venv` di Windows atau `python3 -m venv .venv` di Linux/macOS), lalu pasang dependensi dengan `.venv\Scripts\python -m pip install -r backend/requirements.txt` di Windows atau `.venv/bin/python -m pip install -r backend/requirements.txt` di Linux/macOS.
4. Jalankan `run.bat` di Windows atau `./run.sh` di Linux/macOS. Backend bind ke `127.0.0.1:8000`.
5. Buka `http://127.0.0.1:8000/login` dan masuk memakai kredensial dari `.env`.
6. Isi `GEMINI_API_KEY` di `.env` untuk mengaktifkan Gemini. Model default `gemini-3.8-flash` dapat diganti lewat `GEMINI_MODEL`; regex fallback mati kecuali `ENABLE_REGEX_FALLBACK=true`.

Database SQLite dibuat otomatis di `backend/data/app.db`. Password admin disimpan sebagai hash bcrypt. Saat backend mulai, password admin di `.env` disinkronkan ke database, jadi perubahan password berlaku setelah server direstart. Endpoint dashboard memerlukan cookie sesi admin; gunakan login melalui halaman web terlebih dahulu.

## Endpoint M1

- `GET /health`
- `POST /api/auth/login` dan `POST /api/auth/logout`
- `GET /api/stats`
- `GET /api/signals?limit=100&offset=0`
- `GET /api/logs?limit=100&offset=0&level=INFO&search=...`
- `GET /api/settings` dan `PUT /api/settings` dengan body `{"values":{"confidence_threshold":0.75}}`
- `POST /api/parser/test` untuk menguji klasifikasi dan validasi. Halaman admin tersedia di `/parser-test`.

## Test

Jalankan dari folder proyek: `.venv\Scripts\python -m pytest backend/tests` di Windows atau `.venv/bin/python -m pytest backend/tests` di Linux/macOS.

## Belum teruji

Koneksi Gemini dengan API key sungguhan belum diuji. Eksekusi EA/kompilasi MQL5, koneksi Telegram, serta perilaku di akun demo belum diuji; fitur tersebut dikerjakan pada milestone berikutnya dan memerlukan MetaEditor atau kredensial layanan eksternal.
