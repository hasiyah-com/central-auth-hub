# GeoIP Database (MaxMind GeoLite2)

วางไฟล์ `GeoLite2-Country.mmdb` ที่นี่เพื่อให้ระบบ ML ตรวจ geo features ได้

## วิธีดาวน์โหลด (free)

1. สมัครฟรีที่ <https://www.maxmind.com/en/geolite2/signup>
2. ไปที่ "Download Files" → เลือก **GeoLite2 Country** → format **MaxMind DB binary (.mmdb)**
3. แตก zip แล้วเอา `GeoLite2-Country.mmdb` มาวางในโฟลเดอร์นี้

## หรือใช้ permalink (ต้องมี license key)

```bash
curl -L -o GeoLite2-Country.tar.gz \
  "https://download.maxmind.com/app/geoip_download?edition_id=GeoLite2-Country&license_key=YOUR_KEY&suffix=tar.gz"
tar -xzf GeoLite2-Country.tar.gz --strip-components=1 \
  --wildcards '*/GeoLite2-Country.mmdb'
```

## หลังวางไฟล์เสร็จ

ระบบจะโหลดอัตโนมัติเมื่อ hub-backend restart:

```bash
docker compose restart hub-backend
docker compose logs hub-backend | grep -i geo
# ควรเห็น: ✅ GeoLite2 DB loaded: /app/data/GeoLite2-Country.mmdb
```

## ถ้าไฟล์ไม่มี

ระบบยัง login ได้ปกติ แต่ geo features (is_thailand / is_new_country /
country_change_30d) จะใช้ neutral defaults (is_thailand=1, is_new_country=0).
จะเห็น log warning: `GeoLite2 DB ไม่พบที่ ... — geo features ปิด`
