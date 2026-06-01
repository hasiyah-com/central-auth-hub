"""FastAPI dependencies — ใช้ร่วมกันหลาย router."""

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jwt.exceptions import InvalidTokenError as JWTError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.services.jwt_service import verify_token

# ดึง token จาก header: Authorization: Bearer <token>
bearer_scheme = HTTPBearer()


def get_client_ip(request: Request) -> str | None:
    """คืน IP ของ client โดยให้ความสำคัญกับ X-Forwarded-For (เมื่ออยู่หลัง proxy).

    ใน production ถ้าวางหลัง nginx/cloudflare ต้องการ IP ตัวจริงเพื่อ audit + ML.
    Docker network ก็ใช้ตัวนี้กัน 172.x.x.x ไม่ตรงกับ IP จริง
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else None


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
        raise HTTPException(status_code=403, detail=f"บัญชีถูก {user.status}")
    return user


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
