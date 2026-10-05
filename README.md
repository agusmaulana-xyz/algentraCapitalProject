# Algentra Capital

Layanan copy trading berbasis AI dengan FastAPI, SQLite, parser Gemini, koneksi Telegram, REST API untuk EA MT5, dashboard publik, dan workspace operasi privat.

## Menjalankan backend

1. Gunakan Python 3.11 atau lebih baru.
2. Dari folder proyek, salin `.env.example` menjadi `.env`, lalu ganti `APP_SECRET_KEY` dengan nilai acak minimal 32 karakter, `ADMIN_PASSWORD` dengan password minimal 12 karakter, dan `EA_API_KEY` dengan nilai acak. Isi konfigurasi SMTP untuk mengaktifkan pendaftaran klien dan reset kata sandi melalui email.
3. Buat virtual environment (`python -m venv .venv` di Windows atau `python3 -m venv .venv` di Linux/macOS), lalu pasang dependensi dengan `.venv\Scripts\python -m pip install -r backend/requirements.txt` di Windows atau `.venv/bin/python -m pip install -r backend/requirements.txt` di Linux/macOS.
4. Jalankan `run.bat` untuk pengembangan. Backend bind ke `127.0.0.1:8000` dan memuat ulang saat kode berubah.
5. Buka `http://127.0.0.1:8000/loginAdmin` untuk masuk sebagai admin. Klien masuk melalui `/login`, mendaftar dari `/register`, dan mereset kata sandi melalui `/forgot-password` setelah SMTP diisi.
6. Isi `GEMINI_API_KEY` di `.env` untuk mengaktifkan Gemini. Model default `gemini-3.8-flash` dapat diganti lewat `GEMINI_MODEL`; regex fallback mati kecuali `ENABLE_REGEX_FALLBACK=true`.
7. Untuk Telegram, isi `TELEGRAM_API_ID` dan `TELEGRAM_API_HASH` dari [my.telegram.org](https://my.telegram.org), lalu restart backend dan buka `/telegram-setup` setelah login admin.

Kontak publik pada beranda diatur melalui variabel `CONTACT_*` di `.env.example` dan `.env`. Tautan email, Instagram, TikTok, grup/admin Telegram, dan website ditampilkan dengan ikon; alamat sosial harus berupa URL HTTPS.

## Akses publik melalui Cloudflare Tunnel

Quick Tunnel untuk pengembangan membuat URL sementara pada domain trycloudflare.com. Untuk menggunakannya:

1. Jalankan backend dengan run.bat atau ./run.sh.
2. Buka terminal kedua dari folder proyek dan jalankan **cloudflared tunnel --url http://127.0.0.1:8000**.
3. Buka URL HTTPS yang dicetak cloudflared. URL berhenti berlaku ketika proses tunnel dihentikan.

Quick Tunnel ditujukan untuk pengembangan. Untuk domain tetap, buat named tunnel di Cloudflare, atur public hostname menuju http://127.0.0.1:8000, lalu jalankan **cloudflared tunnel run --token TOKEN_DARI_DASHBOARD** dengan token dari dashboard Cloudflare. Gunakan COOKIE_SECURE=true di .env untuk akses HTTPS produksi. Backend tetap mendengarkan di localhost; tunnel meneruskan trafik tanpa membuka port 8000 ke internet. Lihat [Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/) dan [panduan tunnel bernama](https://developers.cloudflare.com/tunnel/features/locally-managed-tunnels/create-local-tunnel/).

## Produksi di Windows Server

Gunakan satu Windows Server dengan Cloudflare Tunnel. Simpan `.env`, SQLite, sesi Telegram, dan backup di folder data persisten di luar folder kode; berikan akses folder hanya ke akun layanan. Atur `APP_ENV=production`, `COOKIE_SECURE=true`, dan `DATABASE_URL` ke jalur SQLite absolut, misalnya `sqlite:///D:/algentra-data/app.db`. Jangan gunakan jalur relatif karena layanan dapat dimulai dengan direktori kerja berbeda.

Pasang aplikasi sebagai Windows Service melalui NSSM atau Task Scheduler saat boot. Jalankan `run-service.bat` sebagai perintah layanan; ia bind ke `127.0.0.1:8000`, memakai satu worker, dan tidak mengaktifkan reload. Atur Cloudflare Tunnel ingress ke `http://127.0.0.1:8000`; jangan buka port 8000 ke jaringan. Aktifkan HSTS pada Cloudflare SSL/TLS Edge Certificates. Konfigurasikan rotasi log pada service manager.

Database SQLite dibuat otomatis pada jalur yang ditentukan. Atur `BACKUP_DIR` pada environment layanan ke folder backup di disk/lokasi terpisah. Buat task harian Windows Task Scheduler yang menjalankan `run-backup.bat`; skrip menggunakan SQLite online backup API dan mempertahankan 14 salinan terakhir. Pulihkan dengan menyalin file backup saat aplikasi berhenti, lalu mulai ulang layanan. Uji restore sebelum peluncuran. Perubahan Gemini hanya menerima nama model dari dashboard; simpan API key di environment layanan.

## Endpoint M1

- `GET /health`
- Public site: `GET /` dan `/performance`; data performa anonim di `GET /api/public/performance` hanya memakai trade yang sudah ditutup.
- `POST /api/auth/login` untuk admin, `POST /api/auth/client-login` untuk klien, `POST /api/auth/logout`, pendaftaran melalui `POST /api/auth/register`, `POST /api/auth/resend-code`, dan `POST /api/auth/verify-email`, serta reset kata sandi melalui `POST /api/auth/password-reset/request` dan `POST /api/auth/password-reset/confirm`. Halaman reset: `GET /forgot-password`.
- Portal klien: `/account`; pengelolaan terminal melalui `GET/POST /api/mt5/accounts`, `PUT /api/mt5/accounts/{id}`, `PUT /api/mt5/accounts/{id}/active`, dan `POST /api/mt5/accounts/{id}/rotate-token`.
- Copy posisi MT5: `POST /api/ea/master/snapshot` memakai `X-API-Key` dari EA Telegram; `GET /api/mt5/follower/positions` memakai `X-Account-Token` khusus untuk setiap terminal follower.
- `GET /api/stats`
- `GET /api/signals?limit=100&offset=0`
- `GET /api/logs?limit=100&offset=0&level=INFO&search=...`
- `GET /api/settings` dan `PUT /api/settings` dengan body `{"values":{"confidence_threshold":0.75}}`
- `POST /api/parser/test` untuk menguji klasifikasi dan validasi. Halaman admin tersedia di `/parser-test`.
- Telegram: `GET /api/tg/status`, `POST /api/tg/send-code`, `POST /api/tg/verify-code`, `POST /api/tg/verify-2fa`, `POST /api/tg/logout`, `POST /api/tg/reconnect`, `GET /api/tg/groups`, dan `POST /api/tg/groups/select`.
- EA: `GET /api/ea/pending`, `POST /api/ea/report`, `POST /api/ea/result`, `POST /api/ea/heartbeat`, dan `POST /api/ea/master/snapshot` memakai header `X-API-Key` yang nilainya sama dengan `EA_API_KEY`.

## Website publik dan workspace operasi

Beranda publik Algentra Capital tersedia di `/`; bagian performa menampilkan P&L agregat aktual dari trade tertutup. Database saat ini belum mengaitkan trade dengan akun klien terpisah, jadi angka publik tidak diklaim sebagai hasil beberapa akun. Workspace privat tetap tersedia di `/dashboard` setelah login admin. Tabel signal terbaru dan log sistem menampilkan paling banyak lima baris.

Grafik Indeks Equity publik membentuk candle M1 dari laporan equity akun utama MT5: open pertama, high/low selama menit berjalan, dan close terakhir. Halaman menampilkan hingga 60 candle dan memperbarui candle berjalan dari laporan EA. Grafik mulai terisi setelah EA mengirim data; data per jam lama tidak diubah menjadi candle menit sintetis.

## Dashboard admin

Setelah login admin, buka `/dashboard` untuk melihat statistik signal dan trade, heartbeat EA, status Telegram/Gemini, signal terbaru, statistik grup, grafik profit, log, dan riwayat trade. WebSocket `/ws` mengirim pembaruan berkala; dashboard mencoba menyambung ulang otomatis. Log dan riwayat trade dapat difilter serta diekspor ke CSV. Halaman settings saat ini mengatur confidence, symbol default/mapping, demo mode, update signal, kill switch, dan konfigurasi Gemini. Chart.js dimuat dari CDN sehingga grafik memerlukan akses jaringan browser.

Endpoint dashboard (semuanya memerlukan sesi admin): `GET /api/stats`, `GET /api/signals`, `GET /api/groups/stats`, `GET /api/logs`, `GET /api/logs/export.csv`, `GET /api/trades`, `GET /api/trades/export.csv`, `GET/PUT /api/settings`, `PUT /api/settings/gemini-config`, serta `WS /ws`.

Sebelum memanggil Gemini, filter lokal hanya meneruskan pesan yang memiliki arah transaksi dan harga; percakapan serta laporan hasil trade dilewati tanpa permintaan Gemini. Validasi simbol dan daftar simbol yang boleh dieksekusi dapat disesuaikan di settings dan EA.

## Uji login Telegram manual

1. Buat API ID dan API hash pada `my.telegram.org`, simpan di `.env`, dan restart backend.
2. Login admin di `/loginAdmin`, lalu buka `/telegram-setup`.
3. Masukkan nomor telepon dengan kode negara, minta kode, lalu masukkan kode yang diterima di aplikasi Telegram.
4. Jika akun memakai 2FA, masukkan password 2FA. Status harus berubah ke `connected`.
5. Muat daftar grup/channel, aktifkan whitelist yang diinginkan, isi alias bila perlu, lalu simpan.
6. Kirim pesan uji di salah satu grup whitelist dan periksa hasil di API `/api/signals` dan `/api/logs`.

Session Telethon berada di `backend/data/telegram_user.session`, tidak disajikan oleh FastAPI, dan folder `backend/data` masuk `.gitignore`. Logout dari halaman Telegram Setup mencabut session yang tersimpan.

## Memasang EA MT5

1. Buat `EA_API_KEY` acak minimal 24 karakter di `.env`, lalu restart backend.
2. Untuk rilis yang sudah dibangun, login sebagai admin dan unduh EA utama dari `/downloads/TelegramSignalEA.ex5`.
3. Jika memakai perubahan source di repositori ini, buka `mt5/TelegramSignalEA.mq5` dengan MetaEditor dari MT5, tekan **F7** untuk compile, lalu salin `.ex5` hasil compile ke `MQL5/Experts`. File `.ex5` di repo/server harus dibangun ulang setelah source berubah.
4. Di MT5, buka **Tools > Options > Expert Advisors**, aktifkan **Allow WebRequest for listed URL**, lalu tambahkan URL yang sama dengan `ServerURL` (default publik: `https://algentracapital.my.id`; untuk server lokal: `http://127.0.0.1:8000`).
5. Pasang EA ke chart akun demo, isi `ApiKey` dengan nilai `EA_API_KEY`, gunakan `LotMode=LOT_RISK_PERCENT` dan `RiskPercent=1.0`, lalu biarkan `DemoMode=true`. Backend juga memulai `demo_mode=true`.
6. Periksa tab Experts/Journal untuk heartbeat, status koneksi, dan laporan signal.

Resolusi simbol mencoba nama persis, akhiran broker yang unik, lalu pemetaan eksplisit. Untuk broker yang menambahkan akhiran umum, isi `SymbolSuffix` pada EA Telegram dan EA Copy Trading, misalnya `c`. Untuk nama berbeda atau beberapa kandidat yang sama-sama cocok, isi `SymbolMapCsv` dalam format `XAUUSD=XAUUSDc,US30=US30.cash` pada EA terkait. `MarketWatchlistCsv` mengatur simbol yang dipublikasikan EA utama untuk panel harga. `TradeOnlyAllowedSymbols` EA Telegram sekarang nonaktif secara default; daftar izin simbol di backend tetap berlaku bila dikonfigurasi. Akun cent didukung; batas rugi harian otomatis diskalakan 100 kali untuk kode mata uang cent yang dikenali.

`GET /api/ea/pending` mengklaim signal selama 90 detik. Jika simbol atau quote belum tersedia, izin trading mati, spread melewati batas, atau batas posisi penuh, EA menunda laporan final agar signal bisa dicoba lagi setelah klaim dilepas. Signal tetap tunduk pada umur maksimum backend dan dapat kedaluwarsa jika kondisi belum pulih. EA menyimpan penanda idempotensi per entry dan mengirim ulang laporan bila perlu agar polling/restart tidak membuat order ganda. Jika sinyal memiliki beberapa TP, EA membuat satu order untuk setiap TP. Semua order memakai SL dari sinyal; bila SL tidak tersedia, EA memakai `DefaultSLPoints`. Dengan `LotMode=LOT_RISK_PERCENT` dan `RiskPercent=1.0`, anggaran risiko seluruh entry dari satu sinyal adalah sekitar 1% ekuitas akun jika semua entry mencapai SL. Anggaran uang itu dibagi rata per entry, lalu lot tiap entry dihitung dari estimasi P/L MT5 antara harga entry dan SL serta dibulatkan ke bawah sesuai langkah lot broker. Batas `MaxOpenTrades` default EA adalah 20; signal menunggu jika jumlah posisi/order yang dibutuhkan melampaui batas itu. Beberapa order memerlukan akun MT5 hedging.

## Copy posisi dari akun utama ke akun follower

Pendaftaran dan reset kata sandi memakai email OTP enam digit yang berlaku 10 menit. Pengiriman kode dibatasi satu kali per menit dan maksimal tiga kali berturut-turut; setelah pengiriman ketiga, pengiriman berikutnya menunggu satu jam. Kode menerima maksimal tiga percobaan. Gmail bisa dipakai sebagai pengirim: buat akun Gmail khusus, aktifkan 2-Step Verification, lalu buat App Password dari pengaturan Google Account. Isi `.env` seperti di bawah memakai App Password, bukan password Gmail biasa, lalu restart backend. Endpoint juga dibatasi per alamat IP.

```env
EMAIL_SMTP_HOST=smtp.gmail.com
EMAIL_SMTP_PORT=587
EMAIL_SMTP_USERNAME=algentra.sender@gmail.com
EMAIL_SMTP_PASSWORD=app-password-google
EMAIL_FROM="Algentra Capital <algentra.sender@gmail.com>"
EMAIL_SMTP_STARTTLS=true
```

### Panduan klien: menyalin posisi MT5

EA Telegram yang berjalan pada terminal akun utama Algentra mengeksekusi sinyal Telegram sekaligus membagikan posisi terbuka yang dibuat EA itu. Backend menyediakan snapshot tersebut untuk semua terminal follower klien. Follower menyalin posisi, perubahan SL/TP, dan penutupan posisi. Portal tidak meminta password broker. Masuk ke `/account`, daftarkan setiap akun follower, lalu simpan token yang muncul karena token lengkap hanya ditampilkan saat dibuat atau dirotasi.

Unduh EA setelah login ke portal:

- [Unduh EA follower](https://algentracapital.my.id/downloads/MT5FollowerCopyEA.ex5) — pasang pada setiap terminal MT5 akun klien.

Untuk memasang EA:

1. Di MT5, pilih **File → Open Data Folder**, lalu buka `MQL5/Experts`.
2. Salin file `.ex5` yang diunduh ke folder tersebut. Untuk membangun binary dari perubahan source repo, buka `mt5/MT5FollowerCopyEA.mq5` di MetaEditor dan tekan **F7**.
3. Di MT5, pilih **Tools → Options → Expert Advisors**. Aktifkan **Allow WebRequest for listed URL** dan tambahkan `https://algentracapital.my.id`.
4. Dari **Navigator → Expert Advisors**, tarik EA follower ke chart. Isi `AccountToken` dengan token akun itu dan pastikan `ServerURL` berisi `https://algentracapital.my.id`.
5. Aktifkan **Algo Trading**. EA Telegram di terminal utama Algentra harus berjalan agar posisi sumber terus diperbarui. Uji follower di akun demo sebelum menggunakan akun live.

EA Telegram menerbitkan posisi dengan magic number miliknya setiap detik; posisi manual atau EA lain di terminal utama tidak dibagikan. Follower hanya menyalin posisi terbuka, perubahan SL/TP, dan penutupan, bukan pending order sebelum terisi. Akun demo/contest bisa menyalin dengan izin trading MT5 aktif; akun real juga memerlukan `AllowLiveTrading=true`. `VolumeMultiplier` menentukan volume salinan relatif terhadap volume sumber, bukan persentase ekuitas. Lot disesuaikan dengan maksimum dan langkah volume broker. `MaxEntryDeviationPercent=0` menonaktifkan batas keterlambatan entry; isi angka positif bila ingin membatasi salinan yang jauh dari harga entry master. Akun follower tetap harus memakai mode **hedging** karena follower mengelola tiap posisi sumber secara terpisah. Jika data sumber tidak diperbarui selama 20 detik, follower berhenti menyinkronkan. Jika EA berhenti, posisi follower yang sudah terbuka tetap berada di terminal dan perlu dikelola di MT5. Rotasi token jika hilang atau terekspos, lalu masukkan token baru ke EA.

Semua terminal follower klien menerima sumber posisi Algentra yang sama. Akun MT5 klien hanya perlu didaftarkan sebagai follower; terminal sumber tidak perlu didaftarkan lewat portal klien.

Kedua EA yang dibagikan berupa file `.ex5` hasil compile. Jika binary diperbarui, unduh file terbaru dan salin ulang ke folder `MQL5/Experts`.

### Entry berupa rentang harga

Pesan seperti `XAUUSD BUY NOW 4100:::4093`, `XAUUSD BUY 4000-4010`, atau `BUY : ENTRY ZONE : 4185–4190 | TP : 4195, 4200, 4205, 4210, 4215 | SL : 4175` disimpan sebagai zona entry. Parser menyimpan batas bawah dan atas; rentang eksplisit mengesampingkan kata BUY NOW/SELL NOW. Bila zona memiliki beberapa TP, EA membuat jumlah order sesuai jumlah TP dan membagi entry merata di dalam zona. Untuk dua TP atau lebih, BUY dimulai dari batas bawah dan SELL dari batas atas; satu TP memakai titik tengah zona. Harga entry diselaraskan dengan tick symbol dan dijaga tetap di dalam zona. Tiap order memakai TP sesuai urutannya; jenis order (Limit atau Stop) mengikuti posisi harga pasar MT5. Bila zona tidak memiliki TP, EA tetap membuat dua order di batas zona dengan TP default.

Sinyal dengan lebih dari satu entry memerlukan akun MT5 mode hedging agar tiap order menjadi posisi terpisah; akun netting ditolak. Pending order berlaku 60 menit secara default (`PendingOrderExpiryMinutes`) lalu dihapus jika belum terisi. EA memakai expiration broker bila tersedia dan penghapusan berkala saat EA berjalan sebagai fallback.

SL dan setiap TP divalidasi terhadap seluruh zona: SL BUY harus di bawah batas bawah dan TP BUY di atas batas atas; aturan SELL kebalikannya. EA tetap menghormati Demo mode, kill switch, batas lot, spread, dan batas risiko yang sudah dikonfigurasi. Bila lot hasil perhitungan risiko lebih kecil dari lot minimum broker, entry ditolak agar batas risiko tidak terlampaui.

## Test

Jalankan dari folder proyek: `.venv\Scripts\python -m pytest backend/tests` di Windows atau `.venv/bin/python -m pytest backend/tests` di Linux/macOS.

## Belum teruji

Koneksi Gemini, Telegram, dan SMTP dengan kredensial sungguhan belum diuji. EA Telegram 0.8.0 dan EA copy MT5 baru belum dikompilasi di MetaEditor atau diuji pada terminal/akun demo; validasi itu memerlukan MetaEditor/MT5 di Windows.
