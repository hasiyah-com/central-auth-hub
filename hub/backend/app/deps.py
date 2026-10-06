"""FastAPI dependencies — ใช้ร่วมกันหลาย router."""

import ipaddress
import secrets

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jwt.exceptions import InvalidTokenError as JWTError
from sqlalchemy.orm import Session

from app.config import settings
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


def _public_ip_or_none(candidate: str | None) -> str | None:
    """คืน IP ที่ routable บนอินเทอร์เน็ตเท่านั้น ไม่รับ Docker/LAN/loopback."""
    validated = _valid_ip_or_none(candidate)
    if not validated:
        return None
    return validated if ipaddress.ip_address(validated).is_global else None


def get_client_ip(request: Request) -> str | None:
    """คืน IP ของ client เมื่ออยู่หลัง Vercel/Traefik/Dokploy.

    ลำดับความน่าเชื่อถือ:
      1. x-client-ip ที่ Vercel proxy ลงนามด้วย shared secret
      2. public IP ขวาสุดใน X-Forwarded-For
      3. X-Real-IP (อาจเป็น private IP ของ Traefik ใน Dokploy)
      4. request.client.host

    การไล่ XFF จากขวาไปซ้ายและข้าม private proxy hops ทำให้เลือก client IP
    ที่ trusted proxy เติมไว้ โดยไม่หลงเลือก Docker/LAN address เช่น 192.168.x.x.
    """
    # 1. Next.js/Vercel proxy ส่ง IP พร้อม shared secret — ใช้เฉพาะเมื่อ
    # secret ตรงกันแบบ constant-time เพื่อกัน client ยิง header ปลอมเข้า backendโดยตรง
    supplied_secret = request.headers.get("x-proxy-secret", "")
    expected_secret = settings.proxy_shared_secret
    if (
        expected_secret
        and supplied_secret
        and secrets.compare_digest(supplied_secret, expected_secret)
    ):
        signed_client_ip = _valid_ip_or_none(
            (request.headers.get("x-client-ip") or "").strip()
        )
        if signed_client_ip:
            return signed_client_ip

    # 2. Traefik อาจใส่ private proxy hop ไว้ท้าย XFF จึงไล่จากขวาไปซ้าย
    # และคืน public IP ตัวแรกที่พบ ไม่เลือกค่าปลอมทางซ้ายก่อนค่าที่ proxy เติม.
    xff = request.headers.get("x-forwarded-for")
    if xff:
        candidates = [p.strip() for p in xff.split(",") if p.strip()]
        for candidate in reversed(candidates):
            public_ip = _public_ip_or_none(candidate)
            if public_ip:
                return public_ip

    # 3. เก็บ fallback สำหรับเครือข่ายภายใน/dev ที่ไม่มี public IP ใน XFF.
    xri = _valid_ip_or_none((request.headers.get("x-real-ip") or "").strip())
    if xri:
        return xri

    # 4. direct connection (dev / docker)
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
