"""Boot-time GeoIP DB provisioner — สำหรับ Dokploy ที่ SSH เข้า server ไม่ได้.

Container จะดาวน์โหลดไฟล์ mmdb เข้า volume เองตอน start ถ้ายังไม่มี — ตั้ง env
อย่างใดอย่างหนึ่งใน Dokploy UI:

  MAXMIND_LICENSE_KEY : license key ฟรีจาก maxmind.com (ทางการ, แนะนำ) → ดาวน์โหลด
                        edition ตาม MAXMIND_EDITION (default GeoLite2-City = ได้เมือง+ประเทศ)
                        แล้วแตก .mmdb จาก tar.gz ให้อัตโนมัติ
  GEOIP_DB_URL        : direct-download URL ของไฟล์ .mmdb ตรงๆ (เช่น GitHub Release asset)

ปลายทาง = GEOIP_DB_PATH (default /app/data/GeoLite2-Country.mmdb — ตั้งเป็น
GeoLite2-City.mmdb ถ้าต้องการเมือง). มีไฟล์แล้ว / ไม่ตั้ง env → ข้าม.
Fail-safe: ดาวน์โหลดพลาด = ข้าม ไม่ทำให้ boot ล้ม (login ยังทำงาน, geo = NULL).

รันตอน boot: python -m scripts.fetch_geoip
"""

from __future__ import annotations

import os
import tarfile
import tempfile
import urllib.request
from pathlib import Path


def _download_direct(url: str, dest: Path) -> None:
    urllib.request.urlretrieve(url, dest)  # noqa: S310 — URL มาจาก env ของ operator เอง


def _download_maxmind(key: str, edition: str, dest: Path) -> None:
    """ดาวน์โหลด tar.gz จาก MaxMind แล้วแตกเฉพาะไฟล์ .mmdb ออกมาที่ dest."""
    url = (
        "https://download.maxmind.com/app/geoip_download"
        f"?edition_id={edition}&license_key={key}&suffix=tar.gz"
    )
    tmp = tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False)
    tmp.close()
    try:
        urllib.request.urlretrieve(url, tmp.name)  # noqa: S310
        with tarfile.open(tmp.name, "r:gz") as tar:
            member = next(
                (m for m in tar.getmembers() if m.name.endswith(".mmdb")), None
            )
            if member is None:
                raise RuntimeError("ไม่พบไฟล์ .mmdb ใน tarball ของ MaxMind")
            member.name = dest.name  # แตกเป็นชื่อปลายทางตรงๆ (ไม่เอาโฟลเดอร์ลงวันที่)
            tar.extract(member, path=dest.parent)
    finally:
        os.unlink(tmp.name)


def main() -> None:
    dest = Path(os.getenv("GEOIP_DB_PATH", "/app/data/GeoLite2-Country.mmdb"))
    if dest.exists() and dest.stat().st_size > 0:
        print(f"[geoip] มีไฟล์อยู่แล้ว: {dest} — ข้าม")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)

    key = os.getenv("MAXMIND_LICENSE_KEY", "").strip()
    url = os.getenv("GEOIP_DB_URL", "").strip()
    try:
        if key:
            edition = os.getenv("MAXMIND_EDITION", "GeoLite2-City").strip()
            print(f"[geoip] ดาวน์โหลดจาก MaxMind edition={edition} → {dest}")
            _download_maxmind(key, edition, dest)
        elif url:
            print(f"[geoip] ดาวน์โหลดจาก URL → {dest}")
            _download_direct(url, dest)
        else:
            print(
                "[geoip] ไม่ได้ตั้ง MAXMIND_LICENSE_KEY / GEOIP_DB_URL — ข้าม "
                "(geo_country/geo_city จะเป็น NULL)"
            )
            return
        print(f"[geoip] สำเร็จ ({dest.stat().st_size} bytes)")
    except Exception as e:  # noqa: BLE001 — fail-safe: ห้ามให้ boot ล้มเพราะ geo
        print(f"[geoip] ดาวน์โหลดพลาด: {type(e).__name__}: {e} — ข้าม (geo = NULL)")


if __name__ == "__main__":
    main()
