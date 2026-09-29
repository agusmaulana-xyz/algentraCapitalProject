# EA Telegram Signal

Backend awal untuk sistem copy trading Telegram. M1 menyediakan kerangka FastAPI, database SQLite, login admin, dan endpoint statistik, signal, log, serta settings. Proses Telegram, parsing Gemini, EA MT5, dan dashboard lengkap dikerjakan pada milestone berikutnya.

## Menjalankan backend

1. Gunakan Python 3.11 atau lebih baru.
2. Dari folder proyek, salin `.env.example` menjadi `.env`, lalu ganti `APP_SECRET_KEY` dengan nilai acak minimal 32 karakter dan ganti `ADMIN_PASSWORD` dengan password minimal 12 karakter.
3. Buat virtual environment (`python -m venv .venv` di Windows atau `python3 -m venv .venv` di Linux/macOS), lalu pasang dependensi dengan `.venv\Scripts\python -m pip install -r backend/requirements.txt` di Windows atau `.venv/bin/python -m pip install -r backend/requirements.txt` di Linux/macOS.
4. Jalankan `run.bat` di Windows atau `./run.sh` di Linux/macOS. Backend bind ke `127.0.0.1:8000`.
5. Buka `http://127.0.0.1:8000/login` dan masuk memakai kredensial dari `.env`.

Database SQLite dibuat otomatis di `backend/data/app.db`. Password admin disimpan sebagai hash bcrypt. Endpoint dashboard memerlukan cookie sesi admin; gunakan login melalui halaman web terlebih dahulu.

## Endpoint M1

- `GET /health`
- `POST /api/auth/login` dan `POST /api/auth/logout`
- `GET /api/stats`
- `GET /api/signals?limit=100&offset=0`
- `GET /api/logs?limit=100&offset=0&level=INFO&search=...`
- `GET /api/settings` dan `PUT /api/settings` dengan body `{"values":{"confidence_threshold":0.75}}`

## Test

Jalankan dari folder proyek: `.venv\Scripts\python -m pytest backend/tests` di Windows atau `.venv/bin/python -m pytest backend/tests` di Linux/macOS.

## Belum teruji

Eksekusi EA/kompilasi MQL5, koneksi Telegram dan Gemini, serta perilaku di akun demo belum diuji; fitur tersebut belum termasuk M1 dan memerlukan MetaEditor atau kredensial layanan eksternal.
