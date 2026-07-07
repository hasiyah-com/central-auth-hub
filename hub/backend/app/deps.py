"""FastAPI dependencies — ใช้ร่วมกันหลาย router."""

import ipaddress

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jwt.exceptions import InvalidTokenError as JWTError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.services.jwt_service import verify_token

# ดึง token จาก header: Authorization: Bearer <token>
bearer_scheme = HTTPBearer()


def _valid_ip_or_none(candidate: str | None) -> str | None:
    """คืน candidate ถ้าเป็น IPv4/IPv6 ที่ถูกต้อง — ไม่งั้น None.

    กัน:
      - INET column insert crash (audit_logs.ip, login_sessions.ip,
        request_logs.ip เป็น type INET — ค่าที่ไม่ใช่ IP จะ raise DataError → 500)
      - Malformed X-Forwarded-For DoS / log injection — attacker ส่ง
        header garbage ทำให้ audit/log insert ล้มทั้ง request ไม่ได้
    """
    if not candidate:
        return None
    try:
        ip = ipaddress.ip_address(candidate)
    except ValueError:
        return None
    # normalize IPv4-mapped IPv6 (::ffff:172.18.0.1 → 172.18.0.1)
    # — สวยขึ้น + GeoIP/ML ทำงานกับ IPv4 ตรงๆ
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return str(ip.ipv4_mapped)
    return str(ip)


def get_client_ip(request: Request) -> str | None:
    """คืน IP ของ client โดยให้ความสำคัญกับ X-Forwarded-For (เมื่ออยู่หลัง proxy).

    ใน production ถ้าวางหลัง nginx/cloudflare ต้องการ IP ตัวจริงเพื่อ audit + ML.
    Docker network ก็ใช้ตัวนี้กัน 172.x.x.x ไม่ตรงกับ IP จริง

    Validate ผลลัพธ์เป็น IP ที่ถูกต้องเสมอ (กัน INET insert crash +
    malformed-header DoS) — ถ้าไม่ใช่ IP คืน None
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        first = xff.split(",")[0].strip()
        validated = _valid_ip_or_none(first)
        if validated:
            return validated
        # XFF ไม่ใช่ IP (ปลอม/garbage) → fallback ไป request.client.host
    client_host = request.client.host if request.client else None
    return _valid_ip_or_none(client_host)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """ตรวจสอบ JWT แล้วคืน User object ของคนที่ login อยู่.

    verify_token() บังคับ aud = jwt_hub_audience ทำให้ subsystem token
    ที่มี aud=client_id ไม่สามารถใช้ที่ Hub ได้
    """
    token = credentials.credentials
    try:
        payload = verify_token(token)  # default audience = jwt_hub_audience
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token ไม่ถูกต้อง: {e}",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="ไม่พบผู้ใช้")
    if user.status != "active":
        raise HTTPException(status_code=403, detail=_status_block_message(user.status))
    return user


# ข้อความบล็อกตาม status — บาง status เป็น passive (ถูกกระทำ: suspended/deleted)
# บาง status เป็น active voice (จบ/ลาออกเอง: graduated/resigned) ข้อความเลย
# ต้องต่างกันให้อ่านเป็นธรรมชาติ
_STATUS_BLOCK_MESSAGES = {
    "suspended": "บัญชีถูกระงับการใช้งาน",
    "deleted": "บัญชีถูกลบออกจากระบบ",
    "graduated": "บัญชีนี้จบการศึกษาแล้ว ไม่สามารถ login ได้",
    "resigned": "บัญชีนี้ลาออกจากระบบแล้ว ไม่สามารถ login ได้",
}


def _status_block_message(status_value: str) -> str:
    return _STATUS_BLOCK_MESSAGES.get(status_value, f"บัญชีถูก {status_value}")


def require_hub_admin(user: User = Depends(get_current_user)) -> User:
    """ใช้ใน endpoint ที่ต้องเป็น Hub admin เท่านั้น."""
    if not user.is_hub_admin:
        raise HTTPException(status_code=403, detail="ต้องเป็น Hub admin")
    return user


def require_developer(user: User = Depends(get_current_user)) -> User:
    """ใช้ใน Developer Portal — อนุญาตเฉพาะ teacher/staff/admin.

    นักศึกษาไม่สามารถลงทะเบียนระบบย่อยได้ — เป็นไปตามนโยบาย:
    'ระบบกลางใช้สำหรับบุคลากร — นักศึกษาเข้าระบบผ่านระบบย่อยเท่านั้น'
    """
    if user.user_type == "student":
        raise HTTPException(
            status_code=403,
            detail=(
                "นักศึกษาไม่สามารถลงทะเบียนระบบย่อยได้ — "
                "endpoint นี้สำหรับอาจารย์ เจ้าหน้าที่ หรือ admin เท่านั้น"
            ),
        )
    return user
