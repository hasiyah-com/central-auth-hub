# Red-Team Setup เต็ม — Kali VM + VPN จริง + Cloudflare Tunnel

> **วิธีที่ 2 (authentic)** — โจมตีจากต่างประเทศจริงผ่าน VPN ยิงเข้า Hub ผ่าน tunnel
> ใช้คู่กับ [RED_TEAM_GUIDE.md](RED_TEAM_GUIDE.md) (สถานการณ์ + วิธีบันทึกผล)
>
> **เวลารวม:** ~2–3 ชม. (ติดตั้ง 1 ชม. + โจมตี 1 ชม.)

---

## แผนภาพ: traffic วิ่งยังไง (เข้าใจก่อนทำ)

```
┌────────────────────┐   ①VPN ต่างประเทศ    🌍          ┌──────────────────┐
│  Kali VM (โจมตี)    │ ───────────────────▶ Cloudflare  │  host (Hub)       │
│  Firefox + ProtonVPN│    ②https://xxx.trycloudflare    │  localhost:8000   │
│                     │       .com/auth/google/login     │  cloudflared →    │
└────────────────────┘                       ③X-Fwd-For   │  hub-backend      │
                                             = IP VPN จริง └──────────────────┘
                                                    ↓
                                          geo_country = ประเทศ VPN ✅
```

**หัวใจ:** Kali → VPN → อินเทอร์เน็ต → Cloudflare → tunnel → Hub
→ Cloudflare set `X-Forwarded-For` = IP ขา exit ของ VPN → Hub เห็นประเทศจริง

---

# ส่วนที่ 1 — ติดตั้ง Kali ใน VMware (30 นาที)

## 1.1 โหลด Kali (แบบ prebuilt — ง่ายสุด ไม่ต้องลง OS เอง)

1. ไป https://www.kali.org/get-kali/#kali-virtual-machines
2. เลือกแท็บ **VMware** → โหลด **Kali Linux VMware 64-bit** (ไฟล์ `.7z` ~3GB)
3. แตกไฟล์ด้วย 7-Zip → ได้โฟลเดอร์มี `.vmx`, `.vmdk`

> 💡 แบบ prebuilt มี OS + tools ครบแล้ว ไม่ต้องลงจาก ISO (ประหยัดเวลา 30 นาที)

## 1.2 เปิดใน VMware

1. VMware Workstation → **Open a Virtual Machine** → เลือกไฟล์ `.vmx`
2. **ตั้งค่าก่อน power on:**
   - RAM: 2–4 GB
   - **Network Adapter: NAT** ← สำคัญ (VM ใช้เน็ตผ่าน host, VPN ใน VM จะ tunnel ทับ)
3. **Power on** → รอ boot
4. Login: user `kali` / password `kali`

## 1.3 อัปเดต + ตรวจเน็ต

เปิด Terminal ใน Kali:
```bash
# ตรวจว่าเน็ตออกได้
curl https://ipinfo.io/country      # ควรได้ TH (IP host คุณ)

# อัปเดต (ข้ามได้ถ้าจะรีบ)
sudo apt update
```

✅ **Checkpoint 1:** `curl ipinfo.io/country` ได้ `TH` = Kali ออกเน็ตผ่าน host ได้แล้ว

---

# ส่วนที่ 2 — ติดตั้ง VPN ใน Kali (15 นาที)

ใช้ **Proton VPN** (ฟรี — มี US/NL/JP บน free tier พอสำหรับ "ต่างประเทศ")

## 2.1 สมัคร (ถ้ายังไม่มี)
https://protonvpn.com → Sign up → เลือก **Free plan**

## 2.2 ติดตั้ง Proton VPN app ใน Kali (วิธี A — GUI)

> คำสั่งทางการล่าสุด (ก.ค. 2026, v1.0.8) — ถ้า version เปลี่ยน ดูที่
> protonvpn.com/support/official-linux-vpn-ubuntu (Kali ใช้วิธีเดียวกับ Ubuntu)

**ทำใน Terminal ของ Kali ทีละบรรทัด:**

```bash
# 1) โหลด repository package
wget https://repo.protonvpn.com/debian/dists/stable/main/binary-all/protonvpn-stable-release_1.0.8_all.deb

# 2) ตรวจ integrity (ควรได้ "OK")
echo "0b14e71586b22e498eb20926c48c7b434b751149b1f2af9902ef1cfe6b03e180  protonvpn-stable-release_1.0.8_all.deb" | sha256sum --check -

# 3) ติดตั้ง repo + อัปเดตรายการ package
sudo dpkg -i ./protonvpn-stable-release_1.0.8_all.deb && sudo apt update

# 4) ติดตั้ง GUI app
sudo apt install -y proton-vpn-gnome-desktop
```

> ชื่อมี "gnome" แต่**รันบน Xfce ของ Kali ได้ปกติ** (เป็นแค่ GTK toolkit)

**ถ้าขั้น 4 error เรื่อง dependency** (Kali เป็น rolling อาจมี package ไม่ครบ):
```bash
sudo apt install -f -y        # ซ่อม dependency ที่ขาด
sudo apt install -y proton-vpn-gnome-desktop   # ลองใหม่
```

**เปิดแอป:** เมนู Kali (มุมซ้ายบน) → พิมพ์ค้น "Proton" → เปิด → login บัญชี Proton

---

## 2.2 (ทางเลือก B — OpenVPN CLI) ถ้า GUI ไม่ยอมลง

เสถียรกว่า ไม่ต้องพึ่ง repo — เหมาะถ้า Kali มีปัญหา dependency

```bash
# ติดตั้ง OpenVPN
sudo apt update && sudo apt install -y openvpn

# โหลด config: เว็บ Proton → Account → Downloads →
#   "OpenVPN configuration files" → Platform: GNU/Linux → Protocol: UDP
#   เลือกประเทศ (เช่น US Free) → โหลดไฟล์ .ovpn มาไว้ใน Kali

# เชื่อมต่อ (จะถามตั้ง username/password จาก Account → OpenVPN/IKEv2 username)
sudo openvpn --config ~/Downloads/us-free-01.protonvpn.udp.ovpn
```
> เปิด terminal นี้ค้างไว้ = VPN ต่ออยู่ · ปิด terminal / Ctrl+C = ตัด VPN
> (เปิด terminal ที่ 2 ไว้ทำอย่างอื่น)

## 2.3 เชื่อมต่อ + ตรวจ IP เปลี่ยน

1. เปิด **Proton VPN** (เมนู Applications) → login
2. Connect → เลือก **United States** (หรือ Japan)
3. ตรวจใน Terminal:
```bash
curl https://ipinfo.io       # ต้องเห็น "country": "US" + IP ใหม่
```

✅ **Checkpoint 2:** `ipinfo.io` แสดงประเทศ VPN (ไม่ใช่ TH) = VPN ทำงาน
**จดค่า IP + country ไว้** (จะเทียบกับที่ Hub เห็น)

---

# ส่วนที่ 3 — เปิด Hub ให้เข้าถึงจากภายนอก (บน host, 15 นาที)

> ทำบน **เครื่อง host** (ที่รัน Hub) ไม่ใช่ใน Kali

## 3.1 เปิด Cloudflare Tunnel

```bash
bash scripts/expose/quick-tunnel.sh start
```
รอจนได้ URL เช่น `https://random-words-1234.trycloudflare.com` — **copy ไว้**

## 3.2 เพิ่ม redirect URI ใน Google Console

1. https://console.cloud.google.com → APIs & Services → Credentials
2. เปิด OAuth Client → **Authorized redirect URIs** → เพิ่ม:
   ```
   https://<tunnel-url>/auth/google/callback
   ```
3. Save (รอ ~1 นาทีให้มีผล)

> ⚠️ URL เปลี่ยนทุกครั้งที่ restart tunnel → **ทำ red-team ให้จบในรอบเดียว** ไม่ต้อง restart

## 3.3 แก้ .env + recreate

```bash
# แก้ .env (root) — เปลี่ยน 3 ตัวชั่วคราว
GOOGLE_REDIRECT_URI=https://<tunnel-url>/auth/google/callback
HUB_BASE_URL=https://<tunnel-url>
ADMIN_FRONTEND_URL=https://<tunnel-url>

docker compose up -d --force-recreate hub-backend
```

## 3.4 ตรวจว่าเข้าถึงได้

```bash
curl https://<tunnel-url>/health      # ควรได้ {"status":"ok"...}
```

✅ **Checkpoint 3:** `/health` ตอบ 200 ผ่าน tunnel = Hub เข้าถึงจากภายนอกได้

> 💡 **ML enforce mode (optional):** ถ้าอยากเห็น decision จริง (block/challenge)
> แทน `would_*` ตั้ง `ML_SHADOW_MODE=false` ใน .env แล้ว recreate — หรือปล่อยไว้
> จะเห็น `would_block` ก็สื่อความหมายเดียวกัน

---

# ส่วนที่ 4 — ยืนยัน signal ก่อนโจมตีจริง (สำคัญ! 5 นาที)

ทำ **1 login ทดสอบ** เพื่อเช็คว่าสัญญาณครบ ก่อนเสียเวลาทำครบ 12 เคส

**ใน Kali (VPN เปิดอยู่):**
1. เปิด **Firefox** → ไป `https://<tunnel-url>/auth/google/login`
2. Login ด้วย **บัญชี Google ของคุณเอง** (ที่มีสิทธิ์ในระบบ)
   - Google อาจถามยืนยันตัวตน (login จากที่ใหม่) → กดยืนยัน (เป็นชั้นของ Google เอง)

**บน host เช็คผล:**
```bash
docker compose exec hub-backend python -m scripts.redteam_report list --email your@email.com
```
ดูแถวบนสุด:
- `ประเทศ` = **US** (ประเทศ VPN) ← ถ้าเป็น `-` แปลว่า geo ยังไม่ทำงาน หยุดแก้ก่อน
- `อุปกรณ์` = **Firefox/...** (ต่างจาก host)
- `score` = สูง

✅ **Checkpoint 4:** ประเทศตรงกับ VPN + อุปกรณ์เป็น Firefox = **พร้อมโจมตีจริง**

> ❌ ถ้าประเทศเป็น `-`: ตรวจว่า (1) มี `data/GeoLite2-Country.mmdb` (2) ยิงเข้า tunnel-url
> ไม่ใช่ localhost (3) VPN เปิดอยู่จริง

---

# ส่วนที่ 5 — โจมตีจริง 4 ระดับ (1 ชม.)

ทำ **2–3 ครั้งต่อระดับ** → รวม ~10 เคส ทุกครั้ง login ผ่าน `https://<tunnel-url>/auth/google/login`

| # | Model | Kali VPN | Browser | เวลา | จด model ตอน mark |
|---|---|---|---|---|---|
| 1 | **very_naive** | US/RU (ไกล) | Firefox | ตี 2–4 | `very_naive` |
| 2 | **naive** | US | Firefox | เวลาปกติ | `naive` |
| 3 | **vpn** | **ปิด VPN** (IP ไทยผ่าน host) | Firefox | เวลาปกติ | `vpn` |
| 4 | **targeted** | ทำบน **host จริง** ไม่ใช่ Kali | Chrome เดิม | เวลาปกติ | `targeted` |

**อธิบายแต่ละระดับ:**
- **very_naive/naive** = Kali + VPN ต่างประเทศ → ประเทศใหม่ + เครื่องใหม่ (Firefox/Linux)
- **vpn** = Kali **ไม่เปิด VPN** → IP ไทย (ผ่าน host) แต่เครื่องยังใหม่ (Firefox/Linux)
  → ทดสอบว่าระบบจับได้ด้วย **device** แม้ประเทศปกติ
- **targeted** = เปิด browser ปกติบน **host** (Chrome เดิม, IP ไทย, เวลาเดิม) → เลียนเหยื่อ
  → คาดว่า `allow` (RBA จับไม่ได้ — ยืนยันข้อจำกัดเชิงทฤษฎี)

> 💡 ระหว่างทำ ให้เว้นเวลาแต่ละ login สัก 1–2 นาที (กัน login_count_24h พุ่งจน hard-block
> ทุกเคสเหมือนกันหมด จะแยกไม่ออก)

---

# ส่วนที่ 6 — บันทึกผล + เทียบ simulated (15 นาที)

**บน host** หลังทำครบ:

## 6.1 หา session แต่ละเคส
```bash
docker compose exec hub-backend python -m scripts.redteam_report list --email your@email.com --limit 20
```

## 6.2 mark ทุกเคส
```bash
docker compose exec hub-backend python -m scripts.redteam_report mark \
    <session_id> --model very_naive --note "ProtonVPN US, Kali Firefox, ตี3"
# ทำซ้ำทุก session
```

## 6.3 ดูรายงานเทียบ
```bash
docker compose exec hub-backend python -m scripts.redteam_report report
```

จะได้ตารางเทียบ **คะแนนจริง vs simulated** + คำตัดสินว่า attacker modeling น่าเชื่อถือไหม

## 6.4 บันทึกลงไฟล์รายงาน
```bash
docker compose exec hub-backend python -m scripts.redteam_report report \
  > hub/backend/tests/reports/redteam_$(date +%Y-%m-%d).md
```

---

# ส่วนที่ 7 — เก็บกวาด (5 นาที)

```bash
# 1. ปิด tunnel
bash scripts/expose/quick-tunnel.sh stop

# 2. คืนค่า .env กลับ localhost
# GOOGLE_REDIRECT_URI=http://localhost:8000/auth/google/callback
# HUB_BASE_URL=http://localhost:8000
# ADMIN_FRONTEND_URL=http://localhost:3000
docker compose up -d --force-recreate hub-backend

# 3. (ถ้าตั้ง ML_SHADOW_MODE=false) คืนเป็น true

# 4. ลบ redirect URI tunnel ออกจาก Google Console (ความสะอาด)
```

> ⚠️ **อย่า unmark** red-team sessions — เก็บไว้เป็น real attack label (มีค่ามาก ใช้ต่อได้ใน retrain)
> จะ unmark เฉพาะเคสที่ทำพลาด

---

# Checklist ครบวงจร

```
ติดตั้ง
[ ] Kali VMware prebuilt import + boot (kali/kali)
[ ] Network = NAT + curl ipinfo.io ได้ TH
[ ] Proton VPN ติดตั้ง + connect + ipinfo.io แสดงประเทศ VPN

เปิด Hub
[ ] quick-tunnel.sh start → ได้ trycloudflare URL
[ ] เพิ่ม redirect URI ใน Google Console
[ ] แก้ .env (3 ตัว) + recreate hub-backend
[ ] curl <tunnel>/health = 200

ยืนยัน
[ ] login ทดสอบจาก Kali+VPN → redteam_report list → ประเทศตรง VPN ✅

โจมตี
[ ] very_naive × 2-3   (VPN ไกล + Firefox + ตี3)
[ ] naive × 2-3        (VPN + Firefox + เวลาปกติ)
[ ] vpn × 2-3          (ปิด VPN, IP ไทย + Firefox)
[ ] targeted × 2-3     (host จริง, Chrome เดิม)

บันทึก
[ ] mark ทุกเคส --model + --note
[ ] report > tests/reports/redteam_<date>.md

เก็บกวาด
[ ] tunnel stop + .env คืน localhost + recreate
[ ] ลบ redirect URI ออกจาก Google Console
```

---

# ⚠️ ปัญหาที่อาจเจอ + วิธีแก้

| อาการ | สาเหตุ | แก้ |
|---|---|---|
| ประเทศเป็น `-` ตลอด | ยิงเข้า localhost / ไม่มี mmdb | ยิงเข้า tunnel-url + เช็ค `data/GeoLite2-Country.mmdb` |
| Google `redirect_uri_mismatch` | ยังไม่เพิ่ม URL ใน Console | เพิ่ม `<tunnel>/auth/google/callback` + รอ 1 นาที |
| Google บล็อก "sign-in ไม่ปลอดภัย" | Google เห็น login ต่างประเทศ | กดยืนยัน (ชั้นของ Google เอง) — บัญชีตัวเองปลอดภัย |
| ทุกเคส score = 1.0 เหมือนกัน | login รัวจน `login_count_24h ≥ 50` | เว้นเวลา + รอ 24 ชม. หรือใช้บัญชีที่ history สะอาด |
| VPN ไม่เปลี่ยน IP ใน Kali | VPN ต่อไม่ติด | `curl ipinfo.io` เช็ค / ลอง OpenVPN config แทน |
| tunnel URL หาย | restart tunnel | URL ใหม่ → ต้องอัปเดต Console + .env ใหม่ (ทำรอบเดียวจบ) |
| หลัง login หน้าสุดท้าย 404/โหลดไม่ขึ้น | tunnel ต่อแค่ backend ไม่ใช่ frontend | **ปกติ — ไม่ต้องแก้** session ถูก score + บันทึกใน callback แล้วก่อน redirect (นั่นคือสิ่งที่เราต้องการ) |

---

# หมายเหตุความปลอดภัย/จริยธรรม
- ✅ ทำกับ **บัญชี + ระบบของตัวเอง** เท่านั้น (authorized self-testing)
- ✅ Cloudflare Quick Tunnel เป็น URL ชั่วคราว สุ่ม — ปิดหลังใช้
- ⚠️ อย่าเปิด tunnel ทิ้งไว้ (ระบบ dev เข้าถึงได้จากเน็ต) — `stop` ทุกครั้งหลังเสร็จ
- ⚠️ VPN บางประเทศ IP อาจอยู่ใน ipsum blacklist → `is_attack_ip=1` (score สูงกว่าปกติ) ระบุใน note

---

## อ้างอิง
- สถานการณ์ + เกณฑ์: [RED_TEAM_GUIDE.md](RED_TEAM_GUIDE.md)
- Tunnel: `docker-compose.tunnel.yml` · `scripts/expose/quick-tunnel.sh`
- Script บันทึก: `hub/backend/scripts/redteam_report.py`
