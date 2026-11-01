# 📘 Panduan Lengkap LocalDeploy

> Panduan penggunaan end-to-end platform LocalDeploy — dari nol sampai aplikasi Anda live di domain sendiri.
> Pendamping: [`MITIGASI-DOWNTIME.md`](MITIGASI-DOWNTIME.md) (strategi saat PC mati / internet putus).

---

## Daftar Isi

1. [Konsep Dasar](#1-konsep-dasar)
2. [Persiapan Mesin](#2-persiapan-mesin)
3. [Login Pertama & Keamanan](#3-login-pertama--keamanan)
4. [Deploy Aplikasi Pertama](#4-deploy-aplikasi-pertama)
5. [Domain: Akses dari Internet](#5-domain-akses-dari-internet)
6. [Database: Managed & Eksternal (Supabase/Neon/Turso)](#6-database-managed--eksternal)
7. [Environment Variables & Secrets](#7-environment-variables--secrets)
8. [Webhook Auto-Deploy & CI/CD](#8-webhook-auto-deploy--cicd)
9. [Preview Deployments per Pull Request](#9-preview-deployments-per-pull-request)
10. [Replicas & Auto-Scaling](#10-replicas--auto-scaling)
11. [Multi-Server (Agent)](#11-multi-server-agent)
12. [Monitoring, Logs & Terminal](#12-monitoring-logs--terminal)
13. [Notifikasi](#13-notifikasi)
14. [Backup & Restore](#14-backup--restore)
15. [Update Aplikasi & Rollback](#15-update-aplikasi--rollback)
16. [Perawatan Harian/Mingguan](#16-perawatan)

---

## 1. Konsep Dasar

LocalDeploy mengubah PC/laptop/mini-PC yang tidak terpakai menjadi **hosting platform pribadi** (pengganti VPS):

```
Internet → Cloudflare Edge (SSL) → Tunnel → PC Anda (LocalDeploy)
                                             ├── Dashboard :3000
                                             ├── API :8000
                                             ├── Docker Engine (WSL2)
                                             │     ├── Traefik (routing)
                                             │     ├── Aplikasi Anda (containers)
                                             │     └── Database (containers)
                                             └── PostgreSQL/SQLite (data platform)
```

**Yang tidak perlu disewa:** VPS, load balancer, SSL certificate, database cloud (opsional).
**Yang tetap dibutuhkan:** listrik + internet di rumah (lihat [mitigasi](MITIGASI-DOWNTIME.md) jika salah satu mati).

---

## 2. Persiapan Mesin

### Windows (mesin ini — sudah terpasang)
| Komponen | Status | Cara cek |
|---|---|---|
| WSL2 Ubuntu + Docker Engine | ✅ | Dashboard → badge **"Docker connected"** |
| API `:8000` + Dashboard `:3000` | ✅ | `curl http://localhost:8000/api/health` |
| Auto-start saat boot | ✅ | Folder Startup: `localdeploy-autostart.bat` |

Setelah PC direstart, semuanya menyala otomatis. Verifikasi manual:
```bat
C:\Users\LENOVO\localdeploy\scripts\start-localdeploy.bat
```

### Linux / VPS (alternatif produksi)
```bash
git clone <repo> && cd localdeploy
cp .env.example .env     # isi SECRET_KEY, password Postgres, ACME_EMAIL
docker compose up -d --build
# atau: ./scripts/install.sh
```

### 💡 Wajib untuk mode 24/7 (lihat detail di MITIGASI-DOWNTIME.md)
- BIOS: **Restore on AC Power Loss → Power On**
- Windows: matikan sleep, kontrol Windows Update
- (Opsional tapi disarankan) UPS mini + internet cadangan

---

## 3. Login Pertama & Keamanan

1. Buka `http://localhost:3000`
2. Login: `admin` / `localdeploy123` (bootstrap dari `.env`)
3. **SEGERA ganti password**: Settings → Profile → Change password (Argon2id; semua sesi lain otomatis dicabut)

Akun & peran:
- Role **admin** = akses penuh; role **viewer** = hanya baca
- Tambah anggota tim: Settings → Users & roles → Add user

---

## 4. Deploy Aplikasi Pertama

### Langkah (contoh: aplikasi Node/Next.js dari GitHub)

1. **Applications → New application**
2. Isi:
   - **Name**: `toko-online` (slug otomatis `toko-online`)
   - **Deployment source**: pilih satu —
     | Source | Kapan dipakai |
     |---|---|
     | **Git repo** | Repo punya package.json / requirements.txt / dll → runtime terdeteksi otomatis |
     | **Dockerfile** | Repo sudah punya Dockerfile sendiri (selalu menang atas buildpack) |
     | **Compose** | Aplikasi multi-container (db + app) |
     | **Image** | Image siap dari registry (`nginx:latest`) |
     | **Upload** | Upload `.zip/.tar.gz` source tanpa repo |
   - **Git URL + Branch**, opsi username/password (token) untuk repo privat — tersimpan terenkripsi
   - **Container port**: port aplikasi mendengarkan di dalam container (Next.js=3000, Laravel=80, FastAPI=8000)
3. Klik **Create** lalu **Deploy**
4. Pantau **log build real-time** (tab Deployments) — clone → deteksi runtime → build → health check → live!

### Runtime yang didukung otomatis
Next.js, Node/Express/NestJS, React/Vue/Angular/Nuxt (static), Laravel/PHP, FastAPI/Django/Flask, Go, Java/Spring, Ruby, static HTML — atau Dockerfile/compose Anda sendiri.

### Health check
Deploy dianggap sukses hanya jika aplikasi menjawab HTTP < 500 di `health_check_path` (default `/`). Aplikasi harus listen di `0.0.0.0`. Kontainer lama **tetap hidup** sampai yang baru lolos cek → tidak ada downtime saat re-deploy.

---

## 5. Domain: Akses dari Internet

### Cara terbaik: Cloudflare Tunnel (tanpa buka port router)

**Sekali setup:**
1. **Networking → Cloudflare → Connect** — paste API Token dari [dash.cloudflare.com/profile/api-tokens](https://dash.cloudflare.com/profile/api-tokens) (izin: `Account:Read`, `Zone:Read`, `DNS:Edit`, `Cloudflare Tunnel:Edit`)
2. Zero Trust → Networks → Tunnels → Create tunnel (Cloudflared) → copy token
3. **Networking → Add tunnel** → paste → Start

**Tiap aplikasi:**
4. **Domains → Add domain** → hostname (mis. `toko.namadomain.com`) → pilih aplikasi → HTTPS on
5. Klik **"Tunnel"** pada baris domain → pilih tunnel → **Provision** → ingress + DNS CNAME dibuat otomatis
6. `https://toko.namadomain.com` **LIVE dengan SSL** — dari mana pun, selama PC menyala

> Domain apa pun bisa: `.com`, `.id`, `.my.id`, `.biz.id` — cukup tambahkan ke Cloudflare (gratis, ganti nameserver sesuai petunjuk registrar).

### Alternatif: Public IP + Port Forwarding
Networking → mode **Public IP** → router forward TCP 80/443 → server → DNS A record ke IP publik → Traefik + Let's Encrypt otomatis. **Jangan pernah** buka port Docker/DB/API ke internet.

### Akses dashboard dari luar rumah (opsional)
Buat hostname `panel.namadomain.com → http://localhost:3000` di tunnel, lalu **lindungi dengan Cloudflare Access** (Zero Trust → Access → Applications, email OTP gratis) agar hanya Anda yang bisa login dari luar.

---

## 6. Database: Managed & Eksternal

### Managed (berjalan di PC — volume persisten, backup otomatis)
**Databases → Managed (Docker) → New database**
- Engine: PostgreSQL / MySQL / MariaDB / Redis / MongoDB
- Port **tidak pernah dipublikasikan** — aplikasi mengakses via jaringan internal: host `ld-db-<nama>`, port internal
- Info koneksi lengkap: tombol **ⓘ Connection info**
- Backup: tab ⤓ di baris database, atau terjadwal ([§14](#14-backup--restore))

### Eksternal (Supabase/Neon/Turso/Atlas/Upstash/PlanetScale) — data aman walau PC mati
**Databases → External → Add connection**
1. Pilih provider → paste **Connection URL** (+ token/key tambahan)
2. **Test** — koneksi diuji nyata (SELECT 1 / PING), bukan simulasi
3. **Buka aplikasi → tab Databases → Link database**
   → `DATABASE_URL`, `SUPABASE_ANON_KEY`, `TURSO_AUTH_TOKEN`, dst. **otomatis ter-inject** tiap deploy

> 💡 **Arsitektur yang disarankan untuk "pengganti VPS" yang tahan gangguan:** data di cloud provider (gratis tier Supabase/Neon/Turso), aplikasi di PC. PC mati 1 jam → data aman, aplikasi hanya tak terakses sementara (lihat [mitigasi](MITIGASI-DOWNTIME.md)).

---

## 7. Environment Variables & Secrets

Aplikasi → tab **Environment**:
- **Add**: `KEY` + value → **terenkripsi Fernet** di database
- **Reveal** (👁) hanya untuk role write
- Ter-inject ke container **setiap deploy** (termasuk dari database links)
- Ubah env → **Deploy ulang** untuk menerapkan

Contoh wajib untuk Laravel: `APP_KEY`, `DB_HOST=ld-db-appdb`, `DB_PASSWORD=…`.
Untuk Next.js: `DATABASE_URL`, `NEXT_PUBLIC_*` (di-inject saat build).

---

## 8. Webhook Auto-Deploy & CI/CD

### Auto-deploy on push
1. Aplikasi → tab **Settings → Git webhook** → copy URL
2. GitHub repo → Settings → Webhooks → Add webhook:
   - Payload URL: URL tadi
   - Content type: `application/json`
   - Secret: (dari LocalDeploy, provider=github)
   - Events: **Just the push event**
3. Push ke branch yang di-watch → **deploy otomatis**

### Deploy manual dari mana saja (API token)
Settings → **API tokens** → Generate (`ldt_…`, tampil sekali):
```bash
curl -X POST "https://panel.namadomain.com/api/applications/<APP_ID>/deploy" \
     -H "Authorization: Bearer ldt_xxx"
```
GitHub Actions:
```yaml
- name: Redeploy
  if: success()
  run: |
    curl -sf -X POST "$LOCALDEPLOY_URL/api/applications/$APP_ID/deploy" \
         -H "Authorization: Bearer ${{ secrets.LOCALDEPLOY_TOKEN }}"
```

---

## 9. Preview Deployments per Pull Request

1. Aplikasi → tab **Previews** → enable + isi **Preview base domain** (mis. `preview.namadomain.com`)
2. Pastikan webhook GitHub menerima event **Pull requests** (centang di settings webhook)
3. Setiap PR → otomatis: container terisolasi `pr<N>.<base-domain>` + env & database tersalin
4. PR di-merge/close → preview dibersihkan otomatis (atau kedaluwarsa sesuai retensi)

---

## 10. Replicas & Auto-Scaling

Aplikasi → tab **Settings**:
- **Replicas**: jumlah container identik — Traefik membagi trafik otomatis (round-robin)
- **Autoscale on CPU**: threshold %, min & max replika → naik/turun otomatis dengan histeresis (anti flapping)

Skala cepat: ubah angka → Save → Deploy (atau `POST /api/applications/{id}/scale {"replicas":3}`).

---

## 11. Multi-Server (Agent)

Kelola banyak mesin Docker dari satu dashboard:

1. **Settings → Servers → Add server** → copy token `lds_…` (sekali tampil)
2. Di mesin remote (butuh Docker + Python 3.11+):
   ```bash
   pip install docker requests psutil
   export LOCALDEPLOY_API_URL="http://<ip-localdeploy>:8000"
   export LOCALDEPLOY_SERVER_TOKEN="lds_..."
   python agent.py      # atau systemd service — lihat apps/agent/README.md
   ```
3. Agent **dial-out** ke dashboard (nol port inbound di remote) → status **online** + statistik
4. Aplikasi → Settings → **Run on server** → pilih server → Deploy berjalan di mesin itu (log streaming balik)

---

## 12. Monitoring, Logs & Terminal

| Halaman | Isi |
|---|---|
| **Overview** | Widget CPU/RAM/Disk/aplikasi, grafik 6 jam, deployment terakhir, aktivitas |
| **Monitoring** | Riwayat 24 jam, metrik per-aplikasi, jaringan |
| **Logs** | Event stream platform (WS realtime) |
| **Docker** | Container/image/network/volume + aksi start/stop/restart/remove |
| **Storage** | Pemakaian disk host + Docker |
| Aplikasi → **Logs** | Log container live (WS, tail 200) |
| Aplikasi → **Terminal** | Shell interaktif dalam container (xterm) — hati-hati, ini akses root-equivalent ke kontainer |
| Aplikasi → tab Overview | Grafik resource 6 jam milik aplikasi |

Prometheus scraper: `GET /metrics` (plain text) — pasang UptimeRobot/Grafana Agent dari luar untuk uptime eksternal.

---

## 13. Notifikasi

Settings → **Notifications** → Add channel:
- **Discord/Slack**: paste webhook URL
- **Telegram**: bot token + chat ID (dari @BotFather, chat_id via @userinfobot)
- Events: `deployment.success`, `deployment.failed`, `container.died`

**Send test** untuk verifikasi. Penting: notifikasi hanya terkirim selalu jika *eksternal monitor* juga dipasang (PC mati = tak bisa mengabari dirinya sendiri — lihat [mitigasi §3](MITIGASI-DOWNTIME.md)).

---

## 14. Backup & Restore

### Manual
- **Database**: Databases → ⓘ/⤓ → *Create backup now* (dump via helper container, checksum SHA-256)
- **Volume**: Backups → *Backup a volume* → arsip `.tar.gz`
- Download: Backups → ⤓ per record

### Terjadwal
Backups → **Scheduled backups** → target + interval (jam) + **keep last N** → scheduler berjalan tiap menit, memprune otomatis.

### Strategi 3-2-1 untuk rumahan
1. Jadwal otomatis harian (built-in)
2. **Salin keluar PC** minimal mingguan: unduh file backup (atau `rclone copy` folder `data/backups` ke Google Drive/S3)
3. Data kritikal di provider eksternal (Supabase/Neon) — backup bawaan mereka

### Restore
Backups → pilih record → **Restore** (database: pipa balik dump; volume: ekstrak tar ke volume target).

---

## 15. Update Aplikasi & Rollback

- **Update**: push git / tekan Deploy — kontainer baru dibangun, health-checked, lalu switch; yang lama dihapus
- **Rollback**: Deployments → pilih deployment sukses lama → **Rollback to this** → image lama langsung di-deploy ulang (tanpa rebuild)
- **Cancel**: deployment berjalan → Cancel (kooperatif antar-fase)
- **Retry**: deployment gagal → Retry (commit sama)

---

## 16. Perawatan

| Frekuensi | Tugas |
|---|---|
| Otomatis | Auto-start, backup terjadwal, prune image (3 terakhir), purge log 30 hari, bersih-bersih preview kedaluwarsa |
| Mingguan | Cek Monitoring (tren disk), unduh/mirror backup, cek update OS ringan |
| Bulanan | Update aplikasi dependency, `docker system prune` dari halaman Docker bila perlu, uji restore 1 backup |
| Saat listrik mati | Pastikan nyala lagi → auto-start bekerja → cek Overview (lihat [checklist pulih](MITIGASI-DOWNTIME.md#7-checklist-saat-pc-hidup-kembali)) |

---

*Terakhir diperbarui: bersama commit platform terbaru. Panduan teknis lanjutan: [`ARCHITECTURE.md`](ARCHITECTURE.md), [`NETWORKING.md`](NETWORKING.md), [`ENVIRONMENT.md`](ENVIRONMENT.md), [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md).*
