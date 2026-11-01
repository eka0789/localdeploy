# 🛡️ Mitigasi Downtime — Saat PC Mati atau Internet Putus

> LocalDeploy menjalankan aplikasi di PC sendiri. Ini panduan jujur + praktis:
> **apa yang terjadi saat gangguan**, **apa yang bisa disiapkan sebelumnya**, dan
> **cara pulih secepat mungkin** — sehingga PC tua Anda tetap layak sebagai pengganti VPS.

---

## 1. Realitas Dulu (Jujur)

| Kondisi | Aplikasi | Data | Dashboard |
|---|---|---|---|
| PC hidup, internet normal | ✅ Live | ✅ Aman | ✅ |
| **Internet putus** (modem/ISP) | ❌ Tak terakses dari luar* | ✅ Aman (lokal) | ✅ Masih bisa dari LAN |
| **PC mati/restart** | ❌ Tak terakses | ✅ Aman (volume + backup) | ❌ |
| PC hidup, listrik DGU (blinking) | ⚠️ Booting ulang otomatis | ✅ Aman | ⚠️ 1–3 menit |

\* **Kecuali** Anda memasang mitigasi layer Cloudflare di bawah.

Kesimpulan: **data tidak akan hilang** (volume persisten + backup terjadwal), yang terganggu hanya **ketersediaan sementara**. Tugas mitigasi = memperkecil durasi & dampak gangguan.

---

## 2. Lapisan 1 — Cegah PC Mati Sendiri (paling penting)

### BIOS/UEFI (akses: tekan Del/F2 saat nyala)
- **Restore on AC Power Loss → Power On** — listrik naik lagi setelah mati lampu → PC nyala sendiri
- Matikan **Deep Sleep / ErP**

### Windows
```powershell
# Jalankan sebagai Administrator:
powercfg /change standby-timeout-ac 0        # jangan sleep
powercfg /change monitor-timeout-ac 10
powercfg /change hibernate-timeout-ac 0
powercfg /lastwake
# Matikan Fast Startup (sumber boot macet):
powercfg /h off
```
- **Windows Update**: Settings → Windows Update → Active hours 00:00–06:00, atau pause hingga 5 minggu — hindari restart di jam trafik
- **Auto-login** (agar Startup folder + LocalDeploy menyala tanpa menunggu): `netplwiz` → uncheck *Users must enter a user name and password* (Windows 11: setujui via registry `DevicePasswordLessBuildVersion=0` di HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\PasswordLess\Device)
- Verifikasi: folder Startup berisi `localdeploy-autostart.bat` ✅ (sudah terpasang)

### Jaringan
- **DHCP Reservation** — kunci IP LAN PC di router (untuk port forwarding)
- **DDNS** (jika mode Public IP): Cloudflare DDNS / DuckDNS agar IP dinamis tak merusak DNS
- **Internet cadangan** (opsional tapi ampuh): USB tethering HP / ISP kedua + failover di router — saat ISP utama putus, trafik pindah otomatis

### Listrik
- **UPS mini (300–500VA)** — cukup untuk PC + router: bertahan 10–30 menit + shutdown aman
- Kabel daya router & PC ke UPS; **jangan** matikan PC pakai tombol power

---

## 3. Lapisan 2 — Mitigasi di Sisi Cloudflare (saat origin mati, pengunjung tetap dilayani)

### a) Halaman Maintenance Otomatis — Cloudflare Worker (gratis)
Saat PC mati, pengunjung melihat halaman "sebentar ya" alih-alih error jelek — dan page masih terindeks.

Script siap pakai: [`infrastructure/cloudflare/worker-maintenance.js`](../infrastructure/cloudflare/worker-maintenance.js)

Pasang:
1. Cloudflare Dashboard → **Workers & Pages → Create Worker** → paste script → Deploy
2. Worker → Settings → Variables: `ORIGIN_HOST` = hostname asal (mis. `toko.namadomain.com`), `MAINTENANCE_HTML` (opsional, kustom)
3. Domain → **Rules → Origin Rules / Route**: arahkan route `toko.namadomain.com/*` ke Worker **saat gangguan** (atau selalu — worker cek origin dulu, kalau hidup diteruskan normal)

> Cara kerja: `fetch(origin)` dengan timeout 3 detik → **gagal/timeout → tampilkan halaman maintenance cantik**; sukses → proxy normal. PC hidup lagi → otomatis normal tanpa sentuh apa pun.

### b) Cloudflare "Always Online" (untuk situs statis)
Domain → Caching → **Always Online™** → ON. Cloudflare menyajikan versi cache untuk halaman statis saat origin down. (Tidak untuk konten dinamis/API.)

### c) Custom Error Pages
Domain → Page Rules / Cloudflare Pages: buat 502/503 page kustom dengan info WhatsApp/email Anda.

### d) Failover DNS ke landing page
A record `toko` → PC (utama). Saat tahu akan mati lama (perbaikan listrik): sementara arahkan CNAME ke landing page statis (Cloudflare Pages gratis) — pulihkan setelahnya. **Data & deployment tidak disentuh** — hanya DNS.

---

## 4. Lapisan 3 — Pemantauan dari LUAR (wajib!)

PC yang mati tidak bisa mengabari Anda. Gunakan monitor eksternal gratis:
- **UptimeRobot** (free, cek tiap 5 menit) / **Better Stack** / **Healthchecks.io**
- Monitor `https://toko.namadomain.com` + `https://panel.namadomain.com` (dashboard)
- Notifikasi ke **email/Telegram Anda** (bukan ke LocalDeploy — dia ikut mati 😄)

Tambahan: Cloudflare Health Checks / Notification (Zero Trust → Notifications) untuk perubahan status tunnel.

---

## 5. Lapisan 4 — Lindungi Data (agar mati = tak rugi)

| Langkah | Sudah ada di LocalDeploy | Tindakan tambahan Anda |
|---|---|---|
| Backup DB/volume terjadwal | ✅ Built-in (Backups → Schedules) | — |
| **Salin backup keluar PC** | Unduh manual via ⤓ | Mingguan: `rclone copy data/backups gdrive:localdeploy-backups` atau simpan ke flashdisk/cloud |
| **Data kritikal di luar PC** | ✅ Integrasi Supabase/Neon/Turso | Gunakan untuk DB produksi; aplikasi di PC |
| Enkripsi secret | ✅ Fernet + SECRET_KEY | **Backup file `apps/api/data/.secret_key`** + database platform — tanpa dia, secret terenkripsi tak bisa dibuka |
| Deployment reproducible | ✅ Git + IaC (semua dari repo) | Pastikan `.env` aplikasi terdokumentasi |

> Kombinasi terbaik "pengganti VPS hemat": **DB di Neon/Supabase (gratis tier) + aplikasi di PC + backup harian terjadwal + rclone keluar PC.** PC mati total sekalipun, data 100% utuh dan aplikasi redeploy dalam hitungan menit di mesin lain (git clone → deploy → arahkan DNS).

---

## 6. Lapisan 5 — Webhook & CI/CD Saat Downtime

Saat PC mati, push git → webhook gagal → **deploy tidak jalan**. Solusi:

1. **GitHub redelivery**: Repo → Webhooks → Recent Deliveries → delivery gagal → **Redeliver** setelah PC hidup
2. **Deploy via API token** setelah online:
   ```bash
   curl -X POST "$LOCALDEPLOY_URL/api/applications/$APP_ID/deploy" -H "Authorization: Bearer ldt_..."
   ```
3. **GitHub Action dengan retry** (jalankan redeploy tiap 10 menit × 6 saat deploy window):
   ```yaml
   - uses: nick-fields/retry@v3
     with: { timeout_minutes: 5, max_attempts: 6, command: |
       curl -sf -X POST "$URL/api/applications/$APP/deploy" -H "Authorization: Bearer $TOKEN" }
   ```
4. Atau cukup tekan **Deploy** di dashboard (commit terakhir otomatis di-pull).

---

## 7. Checklist Saat PC Hidup Kembali

LocalDeploy auto-start — biasanya tak perlu apa-apa. Verifikasi 2 menit:

1. ☐ `http://localhost:3000` terbuka, badge **Docker connected**
2. ☐ Overview: semua aplikasi **running** (yang `exited`: tombol **Start**, atau **Redeploy**)
3. ☐ Networking → tunnels: status **running/connected** (cloudflared auto-reconnect; kalau tidak: Stop → Start)
4. ☐ Backups → jadwal berjalan lagi (cek record terakhir)
5. ☐ Redeliver webhook GitHub yang gagal saat downtime (§6.1)
6. ☐ Monitor eksternal (UptimeRobot) menunjukkan hijau lagi

**Jika auto-start tidak jalan** (jarang — Windows Update mengubah sesi):
```bat
C:\Users\LENOVO\localdeploy\scripts\start-localdeploy.bat
```
lalu periksa kembali netplwiz/Startup folder.

---

## 8. Bonus Efisiensi "PC Server 24/7"

- PC tua: cabang monitor/keyboard tidak perlu (remote via dashboard/SSH WSL) → hemat daya
- Daya idle kecil: set Windows power plan **Balanced** + C-states on (jangan High Performance untuk server rumah)
- Bersihkan debu, thermal paste bila perlu — PC mati panas = downtime tak terduga
- Taruh di ruang berventilasi; sambungkan ke stabilizer/UPS
- Estimasi biaya listrik PC mini (10–25W) ≈ Rp 20–50 ribu/bulan vs VPS 2GB ≈ Rp 80–200 ribu/bulan — **hemat 60–80%**, plus kapasitas jauh lebih besar

---

*Terakhir diperbarui bersama platform. Panduan utama: [`PANDUAN-LENGKAP.md`](PANDUAN-LENGKAP.md).*
