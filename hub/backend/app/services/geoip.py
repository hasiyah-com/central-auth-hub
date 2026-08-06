"""GeoIP lookup — MaxMind GeoLite2-Country (offline, free).

ทำไม MaxMind:
  - offline lookup → ไม่ต้องเรียก API ภายนอกตอน login (latency + privacy)
  - free GeoLite2 license + อัพเดทเดือนละครั้ง
  - CLAUDE.md ระบุไว้ว่า geo_country ใช้ MaxMind GeoIP2 (Week 7+)

วิธีติดตั้งฐานข้อมูล (one-time setup):
  1) สมัครฟรีที่ https://www.maxmind.com/en/geolite2/signup
  2) ดาวน์โหลด GeoLite2-Country.mmdb
  3) วางที่ hub/backend/data/GeoLite2-Country.mmdb (gitignored)
  4) ตั้ง GEOIP_DB_PATH ใน .env (default: /app/data/GeoLite2-Country.mmdb)

Fail-safe: ทุก error → คืน None (geo features ใน feature_extraction
จะ fallback เป็น is_thailand=1 / is_new_country=0 = neutral)
"""

from __future__ import annotations

import ipaddress
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    import geoip2.database
    import geoip2.errors  # noqa: F401

    _GEOIP2_AVAILABLE = True
except ImportError:
    _GEOIP2_AVAILABLE = False
    logger.warning(
        "geoip2 package ไม่ได้ติดตั้ง — geo features ปิดอยู่ "
        "(เพิ่ม geoip2 ใน requirements.txt + rebuild)"
    )

from app.config import settings  # noqa: E402

# Singleton reader — เปิดครั้งเดียว, thread-safe (geoip2 รองรับ concurrent reads)
_reader: "geoip2.database.Reader | None" = None
_reader_loaded = False  # กัน retry การโหลด DB ที่หายซ้ำๆ


def _is_public_ip(ip: str) -> bool:
    """RFC1918 / loopback / link-local / reserved IPs ไม่ต้อง lookup."""
    try:
        ip_obj = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (
        ip_obj.is_private
        or ip_obj.is_loopback
        or ip_obj.is_link_local
        or ip_obj.is_reserved
        or ip_obj.is_multicast
        or ip_obj.is_unspecified
    )


def _get_reader():
    """โหลด MaxMind DB reader (singleton). คืน None ถ้า DB ไม่พร้อมใช้."""
    global _reader, _reader_loaded
    if _reader_loaded:
        return _reader
    _reader_loaded = True  # ลองโหลดครั้งเดียวเท่านั้น

    if not _GEOIP2_AVAILABLE:
        return None
    db_path = Path(settings.geoip_db_path)
    if not db_path.exists():
        logger.warning(
            f"GeoLite2 DB ไม่พบที่ {db_path} — geo features ปิด "
            f"(ดาวน์โหลดที่ https://www.maxmind.com/en/geolite2/signup)"
        )
        return None
    try:
        _reader = geoip2.database.Reader(str(db_path))
        logger.info(f"✅ GeoLite2 DB loaded: {db_path}")
    except Exception as e:
        logger.warning(f"เปิด GeoLite2 DB ไม่ได้: {e}")
        _reader = None
    return _reader


def lookup_geo(ip: str | None) -> tuple[str | None, str | None]:
    """คืน (country_iso, city_name) เช่น ('TH', 'Bangkok').

    รองรับทั้ง GeoLite2-**City** (ได้เมือง+ประเทศ) และ GeoLite2-**Country**
    (ได้แค่ประเทศ, เมือง=None) — ลอง .city() ก่อน ถ้า DB เป็น Country ค่อย fallback
    .country(). ไม่ต้องรู้ล่วงหน้าว่า mmdb เป็น edition ไหน.

    คืน (None, None) เมื่อ: ip ไม่ใช่ public / DB ไม่พร้อม / IP ไม่อยู่ในฐานข้อมูล.
    Fail-safe — ทุก exception ถูก catch ที่นี่ ไม่ propagate (login ห้ามล้ม เพราะ geo).
    """
    if not ip:
        return (None, None)
    ip = ip.strip()
    if not _is_public_ip(ip):
        return (None, None)

    reader = _get_reader()
    if reader is None:
        return (None, None)

    # 1) ลอง City edition (ได้ทั้งเมือง+ประเทศ)
    try:
        resp = reader.city(ip)
        return (resp.country.iso_code, resp.city.name)
    except Exception as e:  # noqa: BLE001
        if _GEOIP2_AVAILABLE:
            import geoip2.errors

            # IP ไม่อยู่ในฐานข้อมูลจริง → ไม่ต้อง fallback (Country ก็ไม่เจอ)
            if isinstance(e, geoip2.errors.AddressNotFoundError):
                return (None, None)
        # อื่นๆ (เช่น DB เป็น Country edition → .city() ใช้ไม่ได้) → ลอง .country()

    # 2) Fallback: Country edition (เมือง=None)
    try:
        resp = reader.country(ip)
        return (resp.country.iso_code, None)
    except Exception as e:  # noqa: BLE001
        if _GEOIP2_AVAILABLE:
            import geoip2.errors

            if isinstance(e, geoip2.errors.AddressNotFoundError):
                return (None, None)
        logger.warning(f"GeoIP lookup failed for {ip}: {type(e).__name__}: {e}")
        return (None, None)


def lookup_country(ip: str | None) -> str | None:
    """คืน ISO country code (เช่น 'TH') หรือ None — thin wrapper ของ lookup_geo.

    เก็บไว้เพื่อ backward-compat กับ caller ที่ต้องการแค่ประเทศ.
    """
    return lookup_geo(ip)[0]
