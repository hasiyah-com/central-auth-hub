"""สกัด feature vector 12 ตัวจาก login session + history ใน DB.

ลำดับต้องตรงกับ ml-service/app/features.py:
  [hour_of_day, day_of_week, is_weekend, hours_from_typical_login_time,
   is_thailand, is_new_country, country_change_count_30d,
   is_new_device, is_new_user_agent_family,
   log_minutes_since_last_login, login_count_24h, failed_logins_24h]

Cold Start Policy:
  - personalized features (hours_from_typical) require MIN_HISTORY ก่อนเริ่มคำนวณ
  - ถ้า history น้อยไป ให้ค่า neutral (0) — ไม่ลงโทษ user ใหม่
"""

import math
import re
import statistics
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import LoginSession

# ต้องมี history อย่างน้อยกี่ session ก่อนคำนวณ personalized features
MIN_HISTORY_FOR_PERSONALIZATION = 5


# ============ ตัวช่วย parse user-agent (ตรงกับ RBA dataset ของ Wiefling 2022) ============

_BROWSER_PATTERNS = [
    ("Edge", re.compile(r"\b(Edg|Edge)/", re.I)),
    ("Chrome", re.compile(r"\bChrome/", re.I)),
    ("Firefox", re.compile(r"\bFirefox/", re.I)),
    ("Safari", re.compile(r"\bSafari/", re.I)),
    ("Opera", re.compile(r"\b(OPR|Opera)/", re.I)),
]


def browser_family(user_agent: str | None) -> str:
    """แยก browser family จาก user-agent string. ลำดับสำคัญ (Edge ก่อน Chrome)."""
    if not user_agent:
        return "Unknown"
    for name, pat in _BROWSER_PATTERNS:
        if pat.search(user_agent):
            return name
    return "Other"


def parse_browser(user_agent: str | None) -> str:
    """Browser Name and Version — เช่น 'Chrome 120.0.3538', 'Firefox 115.0'.

    ตรงกับ column 'Browser Name and Version' ของ RBA dataset.
    """
    if not user_agent:
        return "Unknown"
    # ลำดับสำคัญ: Edge ก่อน Chrome (เพราะ Edge มี Chrome/ ด้วย)
    m = re.search(r"Edg(?:e)?/(\d+[\.\d]*)", user_agent)
    if m:
        return f"Edge {m.group(1)}"
    m = re.search(r"OPR/(\d+[\.\d]*)", user_agent)
    if m:
        return f"Opera {m.group(1)}"
    m = re.search(r"Chrome/(\d+[\.\d]*)", user_agent)
    if m:
        return f"Chrome {m.group(1)}"
    m = re.search(r"Firefox/(\d+[\.\d]*)", user_agent)
    if m:
        return f"Firefox {m.group(1)}"
    m = re.search(r"Version/(\d+[\.\d]*).*Safari/", user_agent)
    if m:
        return f"Safari {m.group(1)}"
    return "Other"


def parse_os_name(user_agent: str | None) -> str:
    """OS Name and Version — เช่น 'Windows 10', 'iOS 16.0', 'Android 13'.

    ตรงกับ column 'OS Name and Version' ของ RBA dataset.
    """
    if not user_agent:
        return "Unknown"
    # iOS (iPhone / iPad)
    m = re.search(r"(?:iPhone|iPad).*?OS (\d+)[_.](\d+)", user_agent)
    if m:
        return f"iOS {m.group(1)}.{m.group(2)}"
    # Android
    m = re.search(r"Android (\d+(?:\.\d+)?)", user_agent)
    if m:
        return f"Android {m.group(1)}"
    # Windows
    if "Windows NT 10.0" in user_agent:
        return "Windows 10"
    if "Windows NT 6.3" in user_agent:
        return "Windows 8.1"
    if "Windows NT 6.1" in user_agent:
        return "Windows 7"
    # macOS
    m = re.search(r"Mac OS X (\d+)[_.](\d+)", user_agent)
    if m:
        return f"macOS {m.group(1)}.{m.group(2)}"
    # Chrome OS
    if "CrOS" in user_agent:
        return "Chrome OS"
    # Linux
    if "Linux" in user_agent:
        return "Linux"
    return "Other"


def parse_device_type(user_agent: str | None) -> str:
    """Device Type — 'mobile', 'desktop', 'tablet', 'bot', 'unknown'.

    ตรงกับ column 'Device Type' ของ RBA dataset.
    """
    if not user_agent:
        return "unknown"
    ua = user_agent.lower()
    if "bot" in ua or "crawl" in ua or "spider" in ua:
        return "bot"
    if "ipad" in ua or "tablet" in ua:
        return "tablet"
    if "iphone" in ua or "mobile" in ua:
        return "mobile"
    # Android ที่ไม่มี "Mobile" = tablet
    if "android" in ua:
        return "tablet" if "mobile" not in ua else "mobile"
    return "desktop"


# ============ Main extraction ============


def extract_session_features(
    db: Session,
    user_id,
    ip: str | None,
    user_agent: str | None,
    geo_country: str | None = None,
    now: datetime | None = None,
) -> list[float]:
    """คืน feature vector 12 ตัว."""
    now = now or datetime.utcnow()

    # === Temporal ===
    hour = float(now.hour)
    day = float(now.weekday())
    is_weekend = 1.0 if now.weekday() >= 5 else 0.0

    # hours_from_typical_login_time — เทียบกับ median ของชั่วโมง login เก่า
    # Cold Start: ถ้ามี history < 5 session ให้ค่า 0 (neutral, ไม่ penalize user ใหม่)
    past_sessions = (
        db.query(LoginSession.created_at)
        .filter(LoginSession.user_id == user_id)
        .order_by(LoginSession.created_at.desc())
        .limit(50)
        .all()
    )
    if len(past_sessions) >= MIN_HISTORY_FOR_PERSONALIZATION:
        past_hours = [row[0].hour for row in past_sessions]
        typical = statistics.median(past_hours)
        diff = abs(hour - typical)
        hours_from_typical = float(min(diff, 24 - diff))  # circular distance
    else:
        hours_from_typical = 0.0  # cold start — neutral

    # === Geographic ===
    is_thailand = (
        0.0 if (geo_country and geo_country.upper() not in ("TH", "THAILAND")) else 1.0
    )

    is_new_country = 0.0
    if geo_country:
        seen = (
            db.query(LoginSession.geo_country)
            .filter(
                LoginSession.user_id == user_id,
                LoginSession.geo_country.is_not(None),
            )
            .distinct()
            .all()
        )
        seen_set = {row[0] for row in seen}
        if seen_set and geo_country not in seen_set:
            is_new_country = 1.0

    # country_change_count_30d — # ประเทศต่างกันใน 30 วันล่าสุด
    cutoff_30d = now - timedelta(days=30)
    countries_30d = (
        db.query(LoginSession.geo_country)
        .filter(
            LoginSession.user_id == user_id,
            LoginSession.geo_country.is_not(None),
            LoginSession.created_at >= cutoff_30d,
        )
        .distinct()
        .all()
    )
    country_change_30d = float(len({c[0] for c in countries_30d}))

    # === Device ===
    is_new_device = 0.0
    is_new_ua_family = 0.0
    if user_agent:
        seen_ua = (
            db.query(LoginSession.user_agent)
            .filter(
                LoginSession.user_id == user_id,
                LoginSession.user_agent.is_not(None),
            )
            .distinct()
            .all()
        )
        seen_ua_set = {row[0] for row in seen_ua}
        if seen_ua_set and user_agent not in seen_ua_set:
            is_new_device = 1.0

        # ตรวจ browser family
        current_family = browser_family(user_agent)
        seen_families = {browser_family(ua) for ua in seen_ua_set}
        if seen_families and current_family not in seen_families:
            is_new_ua_family = 1.0

    # === Velocity ===
    last = (
        db.query(LoginSession)
        .filter(LoginSession.user_id == user_id)
        .order_by(LoginSession.created_at.desc())
        .first()
    )
    if last:
        delta_min = (now - last.created_at).total_seconds() / 60.0
        log_min = math.log(max(delta_min, 0.5))
    else:
        log_min = 6.0

    cutoff_24h = now - timedelta(hours=24)
    login_count_24h = (
        db.query(func.count(LoginSession.id))
        .filter(
            LoginSession.user_id == user_id,
            LoginSession.created_at >= cutoff_24h,
        )
        .scalar()
        or 0
    )

    # === Brute force ===
    failed_24h = (
        db.query(func.count(LoginSession.id))
        .filter(
            LoginSession.user_id == user_id,
            LoginSession.decision.in_(["block", "would_block"]),
            LoginSession.created_at >= cutoff_24h,
        )
        .scalar()
        or 0
    )

    return [
        hour,
        day,
        is_weekend,
        hours_from_typical,
        is_thailand,
        is_new_country,
        country_change_30d,
        is_new_device,
        is_new_ua_family,
        float(log_min),
        float(login_count_24h),
        float(failed_24h),
    ]
