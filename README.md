# Algentra Capital

Layanan copy trading XAUUSD berbasis AI dengan FastAPI, SQLite, parser Gemini, koneksi Telegram, REST API untuk EA MT5, dashboard publik, dan workspace operasi privat.

## Menjalankan backend

1. Gunakan Python 3.11 atau lebih baru.
2. Dari folder proyek, salin `.env.example` menjadi `.env`, lalu ganti `APP_SECRET_KEY` dengan nilai acak minimal 32 karakter dan ganti `ADMIN_PASSWORD` dengan password minimal 12 karakter.
3. Buat virtual environment (`python -m venv .venv` di Windows atau `python3 -m venv .venv` di Linux/macOS), lalu pasang dependensi dengan `.venv\Scripts\python -m pip install -r backend/requirements.txt` di Windows atau `.venv/bin/python -m pip install -r backend/requirements.txt` di Linux/macOS.
4. Jalankan `run.bat` di Windows atau `./run.sh` di Linux/macOS. Backend bind ke `127.0.0.1:8000`.
5. Buka `http://127.0.0.1:8000/login` dan masuk memakai kredensial dari `.env`.
6. Isi `GEMINI_API_KEY` di `.env` untuk mengaktifkan Gemini. Model default `gemini-3.8-flash` dapat diganti lewat `GEMINI_MODEL`; regex fallback mati kecuali `ENABLE_REGEX_FALLBACK=true`.
7. Untuk Telegram, isi `TELEGRAM_API_ID` dan `TELEGRAM_API_HASH` dari [my.telegram.org](https://my.telegram.org), lalu restart backend dan buka `/telegram-setup` setelah login admin.

## Akses publik melalui Caddy

File `caddyFile` mengarahkan domain `algentracapital.my.id` ke backend lokal di `127.0.0.1:8000`. Caddy mengurus HTTPS otomatis untuk domain tersebut.

1. Arahkan DNS A/AAAA domain ke alamat server publik dan izinkan koneksi masuk TCP port 80 dan 443 pada firewall/server. Pastikan record AAAA benar bila server belum memiliki IPv6.
2. Di `.env` server produksi, isi `COOKIE_SECURE=true` agar cookie admin hanya dikirim lewat HTTPS. Jalankan backend dengan `run.bat` atau `./run.sh`; backend tetap bind ke loopback dan hanya mempercayai header proxy dari Caddy lokal.
3. Dari folder proyek, jalankan Caddy dengan `caddy run --config caddyFile --adapter caddyfile`.
4. Publik dapat membuka `https://algentracapital.my.id`. Jangan buka port 8000 ke internet; hanya port Caddy 80/443 yang perlu dapat diakses dari luar.

Untuk EA MT5 yang berjalan pada komputer berbeda dari server, gunakan `https://algentracapital.my.id` sebagai `ServerURL` dan tambahkan URL yang sama ke daftar **Allow WebRequest**. URL `http://127.0.0.1:8000` hanya untuk EA dan backend yang berjalan pada komputer yang sama.

Database SQLite dibuat otomatis di `backend/data/app.db`. Password admin disimpan sebagai hash bcrypt. Saat backend mulai, password admin di `.env` disinkronkan ke database, jadi perubahan password berlaku setelah server direstart. Endpoint dashboard memerlukan cookie sesi admin; gunakan login melalui halaman web terlebih dahulu.

## Endpoint M1

- `GET /health`
- Public site: `GET /` dan `/performance`; data performa anonim di `GET /api/public/performance` hanya memakai trade yang sudah ditutup.
- `POST /api/auth/login` dan `POST /api/auth/logout`
- `GET /api/stats`
- `GET /api/signals?limit=100&offset=0`
- `GET /api/logs?limit=100&offset=0&level=INFO&search=...`
- `GET /api/settings` dan `PUT /api/settings` dengan body `{"values":{"confidence_threshold":0.75}}`
- `POST /api/parser/test` untuk menguji klasifikasi dan validasi. Halaman admin tersedia di `/parser-test`.
- Telegram: `GET /api/tg/status`, `POST /api/tg/send-code`, `POST /api/tg/verify-code`, `POST /api/tg/verify-2fa`, `POST /api/tg/logout`, `POST /api/tg/reconnect`, `GET /api/tg/groups`, dan `POST /api/tg/groups/select`.
- EA: `GET /api/ea/pending`, `POST /api/ea/report`, `POST /api/ea/result`, dan `POST /api/ea/heartbeat` memakai header `X-API-Key` yang nilainya sama dengan `EA_API_KEY`.

## Website publik dan workspace operasi

Beranda publik Algentra Capital tersedia di `/`; bagian performa menampilkan P&L agregat aktual dari trade tertutup. Database saat ini belum mengaitkan trade dengan akun klien terpisah, jadi angka publik tidak diklaim sebagai hasil beberapa akun. Workspace privat tetap tersedia di `/dashboard` setelah login admin. Tabel signal terbaru dan log sistem menampilkan paling banyak lima baris.

## Dashboard admin

Setelah login admin, buka `/dashboard` untuk melihat statistik signal dan trade, heartbeat EA, status Telegram/Gemini, signal terbaru, statistik grup, grafik profit, log, dan riwayat trade. WebSocket `/ws` mengirim pembaruan berkala; dashboard mencoba menyambung ulang otomatis. Log dan riwayat trade dapat difilter serta diekspor ke CSV. Halaman settings saat ini mengatur confidence, symbol default/mapping, demo mode, update signal, kill switch, dan konfigurasi Gemini. Chart.js dimuat dari CDN sehingga grafik memerlukan akses jaringan browser.

Endpoint dashboard (semuanya memerlukan sesi admin): `GET /api/stats`, `GET /api/signals`, `GET /api/groups/stats`, `GET /api/logs`, `GET /api/logs/export.csv`, `GET /api/trades`, `GET /api/trades/export.csv`, `GET/PUT /api/settings`, `PUT /api/settings/gemini-config`, serta `WS /ws`.

Sebelum memanggil Gemini, filter lokal hanya meneruskan pesan berformat kandidat signal XAUUSD; percakapan, laporan hasil trade, dan simbol non-XAU dilewati tanpa permintaan Gemini.

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
3. Di MT5, buka **Tools > Options > Expert Advisors**, aktifkan **Allow WebRequest for listed URL**, lalu tambahkan URL yang sama dengan `ServerURL` (default publik: `https://algentracapital.my.id`; untuk server lokal: `http://127.0.0.1:8000`).
4. Pasang EA ke chart akun demo, isi `ApiKey` dengan nilai `EA_API_KEY`, gunakan `LotMode=LOT_RISK_PERCENT` dan `RiskPercent=1.0`, lalu biarkan `DemoMode=true`. Backend juga memulai `demo_mode=true`.
5. Periksa tab Experts/Journal untuk heartbeat, status koneksi, dan laporan signal.

`GET /api/ea/pending` mengklaim signal selama 90 detik. EA menyimpan penanda idempotensi per entry dan mengirim ulang laporan bila perlu agar polling/restart tidak membuat order ganda. Jika sinyal memiliki beberapa TP, EA membuat satu order untuk setiap TP. Semua order memakai SL dari sinyal; bila SL tidak tersedia, EA memakai `DefaultSLPoints`. Dengan `LotMode=LOT_RISK_PERCENT` dan `RiskPercent=1.0`, anggaran risiko seluruh entry dari satu sinyal adalah sekitar 1% ekuitas akun jika semua entry mencapai SL. Anggaran uang itu dibagi rata per entry, lalu lot tiap entry dihitung dari estimasi P/L MT5 antara harga entry dan SL serta dibulatkan ke bawah sesuai langkah lot broker. Batas `MaxOpenTrades` default EA adalah 20; sinyal tetap ditolak bila jumlah posisi/order yang dibutuhkan melampaui batas itu. Beberapa order memerlukan akun MT5 hedging.

### Entry berupa rentang harga

Pesan seperti `XAUUSD BUY NOW 4100:::4093`, `XAUUSD BUY 4000-4010`, atau `BUY : ENTRY ZONE : 4185–4190 | TP : 4195, 4200, 4205, 4210, 4215 | SL : 4175` disimpan sebagai zona entry. Parser menyimpan batas bawah dan atas; rentang eksplisit mengesampingkan kata BUY NOW/SELL NOW. Bila zona memiliki beberapa TP, EA membuat jumlah order sesuai jumlah TP dan membagi entry merata di dalam zona. Untuk dua TP atau lebih, BUY dimulai dari batas bawah dan SELL dari batas atas; satu TP memakai titik tengah zona. Harga entry diselaraskan dengan tick symbol dan dijaga tetap di dalam zona. Tiap order memakai TP sesuai urutannya; jenis order (Limit atau Stop) mengikuti posisi harga pasar MT5. Bila zona tidak memiliki TP, EA tetap membuat dua order di batas zona dengan TP default.

Sinyal dengan lebih dari satu entry memerlukan akun MT5 mode hedging agar tiap order menjadi posisi terpisah; akun netting ditolak. Pending order berlaku 60 menit secara default (`PendingOrderExpiryMinutes`) lalu dihapus jika belum terisi. EA memakai expiration broker bila tersedia dan penghapusan berkala saat EA berjalan sebagai fallback.

SL dan setiap TP divalidasi terhadap seluruh zona: SL BUY harus di bawah batas bawah dan TP BUY di atas batas atas; aturan SELL kebalikannya. EA tetap menghormati Demo mode, kill switch, batas lot, spread, dan batas risiko yang sudah dikonfigurasi. Bila lot hasil perhitungan risiko lebih kecil dari lot minimum broker, entry ditolak agar batas risiko tidak terlampaui.

## Test

Jalankan dari folder proyek: `.venv\Scripts\python -m pytest backend/tests` di Windows atau `.venv/bin/python -m pytest backend/tests` di Linux/macOS.

## Belum teruji

Koneksi Gemini dan Telegram dengan akun/kredensial sungguhan belum diuji. Versi EA 0.7.0 belum dikompilasi di MetaEditor dan belum diuji pada terminal atau akun demo; validasi itu memerlukan MetaEditor/MT5 di Windows.
