"""FastAPI dependencies — ใช้ร่วมกันหลาย router."""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.services.jwt_service import verify_token

# ดึง token จาก header: Authorization: Bearer <token>
bearer_scheme = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """ตรวจสอบ JWT แล้วคืน User object ของคนที่ login อยู่.

    ใช้ใน endpoint ที่ต้อง login ก่อน:
        @router.get("/me")
        def me(user: User = Depends(get_current_user)):
            return user
    """
    token = credentials.credentials
    try:
        payload = verify_token(token)
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
