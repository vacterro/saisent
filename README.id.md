# SAISENT 4.0

Panel kontrol yang menempelkan teks yang disiapkan sebelumnya ke sesi agen yang sedang berjalan di mesin ini.

Letakkan teks di antrean sesi yang tepat — SAISENT mengaktifkan jendela agen, berpindah ke tab sesi itu, menempelkan teks dalam satu operasi, dan menekan Enter.

## Mulai cepat

```
START_SAISENT.bat
```

Membutuhkan Python 3.11+ di Windows.

## Cara menggunakan

1. **Agen.** Baris atas — kotak centang: Claude Code, Freebuff, Antigravity, CodeNomad.
   Centang sebuah agen, sesinya muncul di panel kiri.
2. **Sesi langsung.** Di kiri adalah yang benar-benar berjalan: nama sesi, nomor tab, sensor aktivitas, dan proyek. Daftar tidak memperbarui sendiri kecuali Anda mengaktifkan "setiap N dtk" — secara default hanya melalui tombol **Segarkan**.
3. **Tab.** SAISENT menebak nomor tab dari urutan peluncuran sesi. Salah? Tulis nomornya secara manual di `SAISENT.json`, kunci `tabs` (kunci sesi berbentuk `<agen>:<id>`, mis. `{ "tabs": { "claude-code:abc123": 3 } }`). `0` = jangan ganti tab sama sekali.
4. **Teks.** Tulis (atau tempel) di kanan bawah, tekan **Antre** (atau Ctrl+Enter). **Semua ke antrean** menaruh teks yang sama ke setiap sesi langsung — menggantikan makro lama "CTRL+2, teks, CTRL+3, teks".
5. **Antrean.** Urutan baris = urutan pengiriman. Seret baris dengan mouse atau pindahkan dengan **Atas**/**Bawah**. Setiap sesi memiliki antreannya sendiri. Klik dua kali pada baris (atau tombol **Edit**) menarik prompt kembali ke kotak teks; **Simpan edit** menulis ulang di tempat, **Batal** membuang. Mengedit prompt yang sudah terkirim mengembalikannya ke antrean — teks di baris tidak lagi cocok dengan yang diterima sesi. **Duplikat** menaruh salinan tepat di bawahnya.
6. **Pengiriman.** **KIRIM ANTREAN INI** — hanya sesi yang dipilih. **KIRIM SEMUA** — semua antrean berurutan. **Uji kering** tidak mengirim apa pun, hanya menampilkan rencana di log. Pengiriman sungguhan meminta konfirmasi dulu dan menyebutkan sesinya.

## Batalkan pengiriman

Setelah pengiriman, tombol **Batalkan** muncul selama 30 detik. Tombol itu mengembalikan prompt terakhir yang dikirim ke antrean sebagai `pending` — kecuali sesi sudah memprosesnya (pengiriman terkonfirmasi).

## Penjadwalan dan batas

Di grup "Kirim":

- **Kirim pada (HH:MM)** — kosong berarti "sekarang". Dengan waktu, antrean menunggu kemunculan berikutnya dari waktu itu (hari ini, atau besok jika sudah lewat) dan menampilkan hitung mundur di bilah status.
- **Tunggu reset batas** — sebelum setiap prompt, SAISENT membaca teks agen itu sendiri. Jika agen berkata "limit reached", antrean menunggu dan melanjutkan otomatis saat batas bebas. Tidak ada satu prompt pun yang menabrak pintu terkunci.
- **Periksa batas** — pindai ulang sekarang.
- Bidang status di kanan menampilkan status langsung: `limits: all agents free` atau `claude-code: LIMITED until 09:22 (1h 05m remaining)`, merah. Hitung mundur berdetak sekali per detik dari cache; disk hanya disentuh saat pembacaan basi atau waktu reset yang disebut tiba.

Waktu reset diambil dari kata-kata agen sendiri. Jika tidak menyebutkan, SAISENT menulis "reset time not stated" alih-alih mengarang placeholder seperti "+5 jam".

### Kapan batas direset

Jika agen tidak pernah menyebut waktu reset, SAISENT beralih ke aturan per agen:

| Agen | Aturan | Arti |
|---|---|---|
| Freebuff | `daily 10:00` | reset setiap hari pukul 10:00 |
| CodeNomad | `daily 03:00` | reset setiap hari pukul 03:00 |
| Claude Code | `rolling 5h` | 5 jam setelah prompt terakhir yang dikirim |
| Antigravity | hanya kata-kata agen | tanpa aturan — apa yang disebut, atau tidak ada |

Aturan tidak pernah mengesampingkan waktu yang disebut agen; agen adalah otoritas atas kuotanya sendiri. Aturan apa pun dapat ditimpa di `SAISENT.json` di bawah `quota_plans`, mis. `{ "quota_plans": { "claude-code": "rolling 3h" } }`.

## Mengapa yang berikutnya tidak terkirim

Pengiriman bersifat sekuensial ketat dan berhenti pada kesalahan nyata pertama. Alasannya muncul di bilah status (`stopped: window not found: ...`), di baris prompt dalam daftar, dan di log. Sisanya tetap `pending` — tidak ada yang hilang.

Di antara prompt ada jeda `gap_ms` (default 1500 ms) dan status menampilkan `Waiting N.Ns before next`. Jika prompt terkirim tetapi sesi tidak bergerak, prompt ditandai **tidak terkonfirmasi** dan tetap di antrean. "Terkirim" hanya berlaku untuk pengiriman terkonfirmasi.

## Sensor aktivitas

Kolom "Sensor" menjawab "dapatkah saya mengetik sekarang".

- `busy` — sesi menulis ke penyimpanannya kurang dari 20 detik lalu (agen sedang di tengah giliran);
- `idle` — hening lebih dari 20 detik, bidang input bebas.

Dari mana asalnya:

| Agen | Sumber | Sensor |
|---|---|---|
| Claude Code | `~/.claude/sessions/<pid>.json` + transkrip | waktu tulis terakhir di transkrip |
| Freebuff | `<project>/.freebuff/desktop-v2.db`, tabel `threads` | bidang `turn_state` |
| Antigravity | `~/.gemini/antigravity/conversations/*.db` | mtime DB dan `-wal`-nya |
| CodeNomad | `~/.local/share/opencode/opencode.db` SQLite | waktu tulis terakhir di transkrip |

Kelahiran hidup adalah pemeriksaan terpisah, bukan "file di disk masih segar":

- **Claude Code** — PID dari `~/.claude/sessions/<pid>.json` hidup. File bertahan dari penutupan sesi; PID tidak.
- **Freebuff** — `Freebuff.exe` berjalan. DB menjaga thread tetap `open` bahkan setelah aplikasi ditutup.
- **Antigravity** — `Antigravity.exe` berjalan **dan** percakapannya segar. Kesegaran saja tidak cukup: penyimpanan ini menyimpan semua percakapan selamanya, dan editor yang ditutup dulu mengisi daftar dengan sesi yang tidak bisa dijangkau tombol mana pun.
- **CodeNomad** — baris DB tidak diarsipkan (`time_archived IS NULL`). Yang aktif hanya yang sedang terbuka.

## Alamat pengiriman — kolom "Alamat"

Bilah sisi menunjukkan persis bagaimana setiap sesi akan ditangani:

| Nilai | Metode | Keandalan |
|---|---|---|
| `cdp:28194` | Tempel melalui debugger agen | Tepat: bidang dibaca sebelum dan sesudah, fokus tidak dicuri |
| `CTRL+3` | Ganti tab di jendela agen | Baik, jika nomor tab benar |
| `blind` | Tanpa port, tanpa nomor tab | Prompt jatuh ke chat yang sedang terbuka |

Tidak ada judul jendela yang memuat nama sesi — `claude.exe` disebut "Claude", Antigravity disebut "Antigravity", Freebuff disebut "Freebuff Desktop". Menujukan melalui jendela karena itu mustahil, dan `blind` berarti persis seperti bunyinya.

### CDP — jalur andal

Jika agen diluncurkan dengan `--remote-debugging-port`, SAISENT mengirim melalui debugger dan tidak menyentuh fokus maupun keyboard. Artinya:

- teks ditempel langsung ke bidang input, bukan "ke mana pun";
- bidang dibaca **sebelum** menempel: jika ada pesan setengah jadi, pengiriman menolak alih-alih menambahkan ke kalimat orang lain;
- bidang dibaca **setelah** menempel: jika tidak mendarat, kami tidak mengirim.

Penolakan CDP tidak pernah jatuh kembali ke penekanan tombol buta. Transport yang presisi baru saja mengatakan momennya salah; menghantamkan tombol di atasnya persis cara merusak chat orang lain.

Port dibaca dari `DevToolsActivePort` agen, tetapi satu file saja tidak cukup — ia bertahan dari peluncuran sebelumnya. SAISENT benar-benar terhubung ke port sebelum setiap penyelidikan.

Aktifkan debugger untuk agen (restart membunuh apa yang sedang dilakukannya — SAISENT tidak pernah melakukannya sendiri):

```bash
"%LOCALAPPDATA%\Programs\Antigravity\Antigravity.exe" --remote-debugging-port=22998
```

### Pemilih halaman (DOM langsung, 2026-08-05)

| Agen | Port | Bidang input | Daftar dialog |
|---|---|---|---|
| Antigravity | `%APPDATA%\Antigravity\DevToolsActivePort` | `[aria-label="Message input"]` | `button[class*="headerbtn"]` |
| CodeNomad | `%APPDATA%\Plasticity\DevToolsActivePort` | `textarea.prompt-input` | `span.session-item-title` |
| Claude Code | `%APPDATA%\Claude\DevToolsActivePort` | — | — |
| Freebuff | tidak ada | — | — |

Antigravity terverifikasi: 16 tombol, labelnya cocok persis dengan nama proyek yang ditampilkan SAISENT (`_SAIPEN`, `_FastPrompter`, `SAISENT`, …) — pemilihan dialog berdasarkan nama bekerja tepat.

CodeNomad adalah Electron di atas OpenCode; folder data masih disebut `Plasticity`. Daftar sesi di DOM hanya berisi sesi dari **proyek yang sedang terbuka**; sesi dari proyek lain tidak dirender dan SAISENT tidak akan menemukannya — pengiriman menolak alih-alih memukul buta chat yang terbuka.

Timpa kunci profil apa pun di `SAISENT.json`:

```json
{ "cdp_profiles": { "codenomad": { "dialog_selector": ".session-list-item" } } }
```

## CodeNomad

Sesi dibaca dari `~/.local/share/opencode/opencode.db`, tabel `session`: nama = `title`, proyek = `directory`, yang diarsipkan disaring dengan `time_archived`, sensor dengan `time_updated`. Satu-satunya agen di sini yang daftar sesinya berupa kolom biasa — tanpa protobuf, tanpa parsing.

Kelahiran hidup — `CodeNomad.exe` berjalan. Tanpa nomor tab: ditujukan dengan nama melalui debugger.

## Mengapa bukan berdasarkan judul jendela

Setiap jendela `claude.exe` disebut "Claude". Nama sesi tidak pernah muncul di judul, jadi menujukan melalui jendela mustahil — nama, proyek, dan PID berasal dari disk; jendela hanya dibutuhkan untuk fokus.

## Konfirmasi pengiriman

Chromium tidak menjawab `WM_GETTEXT`, jadi membaca "apakah mendarat" melalui Win32 mustahil — read-back lama untuk agen-agen ini selalu mengembalikan "tidak terkonfirmasi". Sebagai gantinya, SAISENT menunggu file yang sama yang diawasi sensor aktivitas bergerak. Bergerak? Terkirim. Tidak bergerak dalam waktu yang ditentukan? Prompt ditandai terkirim tetapi tidak terkonfirmasi, dan ini terlihat di log. Ini tidak dianggap kesalahan: agen mungkin saja belum memulai gilirannya.

Pengiriman berhenti pada kesalahan nyata pertama (jendela tidak ditemukan, fokus hilang, clipboard sibuk). Prompt berikutnya tetap di antrean — tidak hilang dan tidak terkirim buta.

## Ekspor & Impor

Tombol **Ekspor** dan **Impor** menyimpan/memuat antrean dalam format JSONL. Setiap baris mandiri dengan kunci sesinya. Impor menggabungkan tanpa kehilangan data — item duplikat (kunci + teks sama) dilewati.

## File di sebelah program

| File | Isi |
|---|---|
| `SAISENT.json` | pengaturan: agen, nomor tab, waktu tunggu, geometri jendela |
| `SAISENT_QUEUES.json` | antrean per sesi, bertahan dari restart |
| `SAISENT.log` | log riwayat pengiriman |

Antrean tidak pernah dibersihkan otomatis. Jika sesi hilang dari daftar tetapi memiliki item yang belum terkirim, antrean tetap: agen dimulai ulang, dan antrean yang dibuang diam-diam lebih buruk daripada satu baris ekstra di file.

## Pengaturan tersembunyi

Edit `SAISENT.json` saat program tertutup:

- `gap_ms` — jeda antara prompt dalam satu batch (default 1500);
- `settle_ms` — jeda setelah ganti tab dan setelah menempel (400);
- `confirm_seconds` — berapa lama menunggu konfirmasi pengiriman (10);
- `busy_seconds` — ambang sensor "busy/idle" (20);
- `freebuff_roots` — akar tempat mencari `.freebuff/desktop-v2.db`, mis. `["V:\\___VAC\\__K\\__CODE"]`; kedalaman pencarian dibatasi 3;
- `submit` — tombol untuk mengirim, default `ENTER`.

## Keterbatasan

- Tab ditujukan melalui `Ctrl+1..Ctrl+9`. Sesi kesepuluh tidak terjangkau — `Ctrl+10` tidak ada, dan SAISENT menolak alih-alih menebak.
- Nomor tab adalah tebakan berdasarkan urutan peluncuran. Lakukan percobaan pertama dengan **Uji kering**, lalu pada sesi yang tidak penting.
- Antigravity tidak menyimpan nama percakapan sebagai teks: daftar menampilkan nama folder kerja yang diekstrak dari metadata.

## Pengujian

```
python -m pytest -q
```

<!-- source-digest: README.md sha256:8396e932d633848051a0136a6389cad9784a44e2a74b88b1cdb693c9505b6d2b -->
