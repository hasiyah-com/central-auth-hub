"""OAuth router — flow เต็มของการ login ผ่าน Subsystem.

Flow:
  1. Subsystem redirect ผู้ใช้มา  GET /oauth/authorize
       (client_id, redirect_uri, state, code_challenge)
  2. Hub ตรวจ client_id + redirect_uri -> เก็บ request ใน Redis -> ส่งไป Google
  3. Google ส่งกลับ  GET /oauth/callback
       Hub: หา user -> เช็ค access_list -> สร้าง authorization code -> redirect กลับ subsystem
  4. Subsystem เรียก  POST /oauth/token  (server-to-server)
       (code, client_id, client_secret, code_verifier)
       Hub: verify secret + verify PKCE -> ออก JWT (มี audience + ข้อมูลตาม scope)

ตัวช่วยทดสอบ (ใช้เฉพาะตอน dev):
  GET /oauth/pkce-helper   -> สร้างคู่ code_verifier/code_challenge
  GET /oauth/test-callback -> หน้าจำลอง redirect_uri ของ subsystem
"""
import json
import secrets

from authlib.integrations.starlette_client import OAuthError
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import get_client_ip
from app.models import AccessList, LoginSession, Subsystem, User
from app.redis_client import redis_client
from app.routers.auth import oauth          # ใช้ Authlib client ตัวเดียวกับ Week 2
from app.services.audit_service import log_action
from app.services.feature_extraction import extract_session_features
from app.services.hooks import (
    EVT_OAUTH_AUTHORIZED,
    EVT_OAUTH_FAILURE,
    emit,
)
from app.services.jwt_service import create_subsystem_token
from app.services.ml_client import get_anomaly_score
from app.services.pkce import generate_pkce_pair, verify_pkce
from app.services.secret_service import verify_secret

router = APIRouter()

AUTH_REQUEST_TTL = 600   # OAuth request เก็บใน Redis 10 นาที
AUTH_CODE_TTL = 60       # authorization code อายุ 60 วินาที


# ============ 1. /oauth/authorize — จุดเริ่มต้น ============

@router.get("/authorize")
async def authorize(
    request: Request,
    client_id: str,
    redirect_uri: str,
    state: str,
    code_challenge: str,
    scope: str = "",
    db: Session = Depends(get_db),
):
    """Subsystem redirect ผู้ใช้มาที่นี่เพื่อเริ่ม login."""
    # 1. ตรวจ client_id
    subsystem = db.query(Subsystem).filter(Subsystem.client_id == client_id).first()
    if not subsystem:
        raise HTTPException(status_code=400, detail="client_id ไม่ถูกต้อง")
    if subsystem.status != "active":
        raise HTTPException(
            status_code=403,
            detail=f"subsystem ยังเป็น '{subsystem.status}' — รอ admin อนุมัติก่อน",
        )

    # 2. ตรวจ redirect_uri ต้องตรงกับที่ลงทะเบียน (กัน open redirect)
    if redirect_uri not in subsystem.redirect_uris:
        raise HTTPException(
            status_code=400,
            detail="redirect_uri ไม่ตรงกับที่ลงทะเบียนไว้",
        )

    # 3. เก็บ OAuth request ใน Redis โดยใช้ "state token ของ Hub" เป็น key
    #    (state ที่ subsystem ส่งมาเก็บแยกเป็นข้อมูลภายใน)
    #
    #    การใช้ state token เป็น Redis key ทำให้:
    #    - เปิดหลาย tab พร้อมกันได้ (ไม่ทับกันใน session)
    #    - state ที่ Google ส่งกลับ = key ของ Redis ตรงๆ
    hub_state = secrets.token_urlsafe(24)
    redis_client.setex(
        f"authreq:{hub_state}",
        AUTH_REQUEST_TTL,
        json.dumps({
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": state,                  # state ของ subsystem (ส่งกลับตอน redirect)
            "code_challenge": code_challenge,
            "subsystem_id": str(subsystem.id),
            "scope": subsystem.scope,        # ใช้ scope ที่ลงทะเบียนไว้
        }),
    )

    # 4. ส่ง hub_state ของเราไปกับ Google — Authlib จะเก็บใน session
    #    แบบ keyed-by-state (_state_google_{hub_state}_data) ทำให้ multi-tab ใช้ได้
    return await oauth.google.authorize_redirect(
        request, settings.oauth_callback_uri, state=hub_state
    )


# ============ 2. /oauth/callback — Google ส่งกลับ ============

@router.get("/callback")
async def oauth_callback(
    request: Request,
    state: str | None = None,
    db: Session = Depends(get_db),
):
    """Google ส่งผู้ใช้กลับมาที่นี่ — Hub ตรวจสิทธิ์แล้วออก authorization code.

    state ที่ Google ส่งกลับ = hub_state ที่ใช้เป็น Redis key (ใน /authorize)
    """
    if not state:
        raise HTTPException(status_code=400, detail="ไม่พบ state parameter")

    raw = redis_client.get(f"authreq:{state}")
    if not raw:
        raise HTTPException(status_code=400, detail="OAuth request หมดอายุ — เริ่มใหม่")
    authreq = json.loads(raw)

    # แลก code ของ Google เป็น token
    try:
        token = await oauth.google.authorize_access_token(request)
    except OAuthError as e:
        raise HTTPException(status_code=400, detail=f"Google OAuth ล้มเหลว: {e.error}")

    userinfo = token.get("userinfo")
    if not userinfo:
        raise HTTPException(status_code=400, detail="ไม่ได้รับข้อมูลจาก Google")
    email = userinfo["email"]
    client_ip = get_client_ip(request)

    # หา user ใน Hub
    user = db.query(User).filter(User.email == email).first()
    if not user:
        log_action(
            db, actor_id=None,
            action="oauth_login_failed_unknown_email",
            target_type="subsystem", target_id=authreq["subsystem_id"], ip=client_ip,
            metadata={"email": email, "client_id": authreq["client_id"]},
        )
        db.commit()
        await emit(EVT_OAUTH_FAILURE, {
            "client_id": authreq["client_id"], "reason": "unknown_email", "ip": client_ip,
        })
        raise HTTPException(
            status_code=403,
            detail=f"อีเมล {email} ไม่ใช่ผู้ใช้ของมหาวิทยาลัย",
        )
    if user.status != "active":
        log_action(
            db, actor_id=user.id,
            action="oauth_login_failed_inactive",
            target_type="user", target_id=user.id, ip=client_ip,
            metadata={"email": email, "status": user.status,
                      "subsystem_id": authreq["subsystem_id"]},
        )
        db.commit()
        await emit(EVT_OAUTH_FAILURE, {
            "user_id": str(user.id), "client_id": authreq["client_id"],
            "reason": f"inactive_{user.status}", "ip": client_ip,
        })
        raise HTTPException(status_code=403, detail=f"บัญชีถูก {user.status}")

    # *** เช็ค Access List — user มีสิทธิ์เข้า subsystem นี้ไหม ***
    access = (
        db.query(AccessList)
        .filter(
            AccessList.subsystem_id == authreq["subsystem_id"],
            AccessList.user_id == user.id,
            AccessList.revoked_at.is_(None),
        )
        .first()
    )
    if not access:
        log_action(
            db, actor_id=user.id,
            action="oauth_login_failed_not_in_whitelist",
            target_type="subsystem", target_id=authreq["subsystem_id"], ip=client_ip,
            metadata={"email": email, "user_id": str(user.id),
                      "client_id": authreq["client_id"]},
        )
        db.commit()
        await emit(EVT_OAUTH_FAILURE, {
            "user_id": str(user.id), "client_id": authreq["client_id"],
            "reason": "not_in_whitelist", "ip": client_ip,
        })
        raise HTTPException(
            status_code=403,
            detail="คุณไม่อยู่ใน whitelist ของระบบย่อยนี้ — ติดต่อ admin",
        )

    # ผูก google_sub ครั้งแรก — ถ้ามีอยู่แล้วต้องตรงกัน (กัน account hijack)
    google_sub = userinfo["sub"]
    if user.google_sub and user.google_sub != google_sub:
        log_action(
            db, actor_id=user.id,
            action="oauth_login_failed_google_sub_mismatch",
            target_type="user", target_id=user.id, ip=client_ip,
            metadata={"email": email, "subsystem_id": authreq["subsystem_id"]},
        )
        db.commit()
        await emit(EVT_OAUTH_FAILURE, {
            "user_id": str(user.id), "client_id": authreq["client_id"],
            "reason": "google_sub_mismatch", "ip": client_ip,
        })
        raise HTTPException(
            status_code=403,
            detail="Google account นี้ไม่ตรงกับบัญชีที่เคยใช้ login — ติดต่อ admin",
        )
    if not user.google_sub:
        user.google_sub = google_sub

    # ===== ML Anomaly Detection =====
    client_ip = get_client_ip(request)
    user_agent = request.headers.get("user-agent")

    # 1) สกัด feature vector จาก session + history
    features = extract_session_features(
        db,
        user_id=user.id,
        ip=client_ip,
        user_agent=user_agent,
    )

    # 2) เรียก ML service (fail-safe ถ้า ML ล่ม -> pass + 0.0)
    ml_result = await get_anomaly_score(features)
    anomaly_score = ml_result["anomaly_score"]
    ml_decision = ml_result["decision"]   # ML's recommendation: pass/mfa/block

    # 3) ตัดสินใจตาม policy
    if settings.ml_shadow_mode:
        # Shadow Mode: ปล่อยผ่านทุกคน แต่ log สิ่งที่ ML แนะนำไว้
        if ml_decision == "block":
            actual_decision = "would_block"
        elif ml_decision == "mfa":
            actual_decision = "would_mfa"
        else:
            actual_decision = "pass"
    else:
        # Enforce Mode: ทำตาม ML จริง
        actual_decision = ml_decision

    # 4) บันทึก login session พร้อม score + decision
    db.add(LoginSession(
        user_id=user.id,
        subsystem_id=authreq["subsystem_id"],
        ip=client_ip,
        user_agent=user_agent,
        anomaly_score=anomaly_score,
        decision=actual_decision,
    ))

    # 5) ถ้าเป็น Enforce mode และ ML สั่ง block -> ปฏิเสธก่อนสร้าง code
    if actual_decision == "block":
        log_action(
            db,
            actor_id=user.id,
            action="login_blocked_by_ml",
            target_type="subsystem",
            target_id=authreq["subsystem_id"],
            ip=client_ip,
            metadata={"score": anomaly_score, "features": features},
        )
        db.commit()
        await emit(EVT_OAUTH_FAILURE, {
            "user_id": str(user.id), "client_id": authreq["client_id"],
            "reason": "ml_blocked", "ip": client_ip, "anomaly_score": anomaly_score,
        })
        raise HTTPException(
            status_code=403,
            detail=(
                f"การ login ถูกบล็อกโดยระบบตรวจสอบความปลอดภัย "
                f"(anomaly_score={anomaly_score}) — ติดต่อ admin หากเป็นเรื่องผิดพลาด"
            ),
        )

    # (ถ้า ml_decision='mfa' ใน Enforce mode — Week 5 ยังไม่มี MFA flow
    #  จะ implement ใน Week ถัดไป — ตอนนี้ปล่อยผ่าน + log)

    # สร้าง authorization code (อายุ 60 วินาที, ใช้ครั้งเดียว)
    auth_code = secrets.token_urlsafe(32)
    redis_client.setex(
        f"authcode:{auth_code}",
        AUTH_CODE_TTL,
        json.dumps({
            "user_id": str(user.id),
            "client_id": authreq["client_id"],
            "subsystem_id": authreq["subsystem_id"],
            "code_challenge": authreq["code_challenge"],
            "scope": authreq["scope"],
            "role_in_sub": access.role_in_sub,
        }),
    )

    log_action(
        db,
        actor_id=user.id,
        action="oauth_authorized",
        target_type="subsystem",
        target_id=authreq["subsystem_id"],
        ip=client_ip,
        metadata={"anomaly_score": anomaly_score, "ml_decision": ml_decision,
                  "actual_decision": actual_decision, "ml_error": ml_result.get("error")},
    )
    db.commit()

    await emit(EVT_OAUTH_AUTHORIZED, {
        "user_id": str(user.id),
        "client_id": authreq["client_id"],
        "subsystem_id": authreq["subsystem_id"],
        "ip": client_ip,
    })

    # cleanup + redirect กลับ subsystem พร้อม code + state
    redis_client.delete(f"authreq:{state}")

    sep = "&" if "?" in authreq["redirect_uri"] else "?"
    callback_url = (
        f"{authreq['redirect_uri']}{sep}code={auth_code}&state={authreq['state']}"
    )
    return RedirectResponse(url=callback_url)


# ============ 3. /oauth/token — แลก code เป็น JWT (server-to-server) ============

@router.post("/token")
def token_exchange(
    request: Request,
    grant_type: str = Form(...),
    code: str = Form(...),
    client_id: str = Form(...),
    client_secret: str = Form(...),
    code_verifier: str = Form(...),
    db: Session = Depends(get_db),
):
    """Subsystem เรียก endpoint นี้แบบ server-to-server เพื่อแลก code เป็น JWT."""
    if grant_type != "authorization_code":
        raise HTTPException(
            status_code=400, detail="grant_type ต้องเป็น 'authorization_code'"
        )

    # 1. ดึง authorization code จาก Redis แบบ atomic (get + delete พร้อมกัน)
    #    กัน race: 2 requests ใช้ code เดียวกันแล้วผ่านทั้งคู่
    #    code ที่ผ่าน redis getdel ไปแล้วใช้ซ้ำไม่ได้แน่นอน
    raw = redis_client.getdel(f"authcode:{code}")
    if not raw:
        raise HTTPException(
            status_code=400,
            detail="authorization code ไม่ถูกต้องหรือหมดอายุ (อายุแค่ 60 วินาที)",
        )
    code_data = json.loads(raw)

    # 2. ตรวจ client_id ตรงกับตอนสร้าง code ไหม
    if code_data["client_id"] != client_id:
        raise HTTPException(status_code=400, detail="client_id ไม่ตรงกับ code")

    # 3. ตรวจ client_secret (Argon2id verify)
    subsystem = db.query(Subsystem).filter(Subsystem.client_id == client_id).first()
    if not subsystem or not verify_secret(subsystem.client_secret_hash, client_secret):
        raise HTTPException(status_code=401, detail="client_secret ไม่ถูกต้อง")

    # 4. ตรวจ PKCE — SHA256(code_verifier) ต้องตรงกับ code_challenge
    if not verify_pkce(code_verifier, code_data["code_challenge"]):
        raise HTTPException(status_code=400, detail="PKCE verification ล้มเหลว")

    # 5. หา user แล้วออก JWT (มี audience + ข้อมูลตาม scope)
    #    (code ถูกลบไปแล้วตอน getdel ที่ขั้น 1)
    user = db.query(User).filter(User.id == code_data["user_id"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="ไม่พบ user")

    access_token = create_subsystem_token(
        user=user,
        client_id=client_id,
        scope=code_data["scope"],
        role_in_sub=code_data["role_in_sub"],
    )

    log_action(
        db,
        actor_id=user.id,
        action="token_issued",
        target_type="subsystem",
        target_id=code_data["subsystem_id"],
        ip=get_client_ip(request),
    )
    db.commit()

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": settings.jwt_access_token_expire_minutes * 60,
        "scope": code_data["scope"],
        "role_in_subsystem": code_data["role_in_sub"],
    }


# ============ ตัวช่วยทดสอบ (dev only) ============

@router.get("/pkce-helper")
def pkce_helper():
    """สร้างคู่ code_verifier / code_challenge สำหรับทดสอบ.

    ในระบบจริง subsystem จะสร้างคู่นี้เอง — endpoint นี้มีไว้ช่วยทดสอบ Week 4
    """
    verifier, challenge = generate_pkce_pair()
    return {
        "code_verifier": verifier,
        "code_challenge": challenge,
        "note": "ใช้ code_challenge ตอนเรียก /oauth/authorize และ code_verifier ตอน /oauth/token",
    }


@router.get("/test-callback", response_class=HTMLResponse)
def test_callback(code: str = "", state: str = ""):
    """หน้าจำลอง redirect_uri ของ subsystem — แสดง code + state ที่ Hub ส่งกลับมา.

    ตอนทดสอบ: ลงทะเบียน subsystem ด้วย
        redirect_uri = http://localhost:8000/oauth/test-callback
    """
    html = f"""<!DOCTYPE html><html lang="th"><head><meta charset="UTF-8">
<title>OAuth Test Callback</title>
<style>
  body {{ font-family: system-ui, "Sarabun", sans-serif; background: #f1f5f9;
          padding: 40px 16px; }}
  .box {{ max-width: 600px; margin: 0 auto; background: #fff; border-radius: 12px;
          padding: 28px 32px; box-shadow: 0 1px 3px rgba(0,0,0,.1); }}
  h1 {{ font-size: 20px; color: #16a34a; }}
  .field {{ font-family: monospace; background: #1f2937; color: #86efac;
            padding: 12px 14px; border-radius: 8px; word-break: break-all;
            margin: 8px 0; font-size: 13px; }}
  .label {{ font-size: 12px; color: #64748b; margin-top: 12px; }}
  .step {{ background: #eff6ff; border-left: 4px solid #2563eb; padding: 12px 14px;
           border-radius: 4px; margin-top: 16px; font-size: 13px; }}
</style></head><body>
<div class="box">
  <h1>✓ Hub ส่ง authorization code กลับมาแล้ว</h1>
  <p>นี่คือหน้าจำลอง redirect_uri ของ subsystem — ในระบบจริง subsystem
     จะเอา code นี้ไปแลก token เอง</p>

  <div class="label">authorization code</div>
  <div class="field">{code or "(ไม่มี code)"}</div>

  <div class="label">state (subsystem ต้องเช็คว่าตรงกับที่ส่งไป)</div>
  <div class="field">{state or "(ไม่มี state)"}</div>

  <div class="step">
    <strong>ขั้นต่อไป — แลก code เป็น token:</strong><br>
    ไปที่ <code>/docs</code> -> <code>POST /oauth/token</code> -> ใส่:<br>
    grant_type = <code>authorization_code</code><br>
    code = code ด้านบน<br>
    client_id = client_id ของ subsystem<br>
    client_secret = client_secret ของ subsystem<br>
    code_verifier = code_verifier ที่คู่กับ code_challenge ที่ใช้ตอน authorize
  </div>
</div>
</body></html>"""
    return HTMLResponse(content=html)
