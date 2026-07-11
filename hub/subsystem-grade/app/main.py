"""ระบบเกรด (Grade System) — subsystem C, focused demo ของ Roster Sync + API key.

หน้าเหมือน subsystem ก่อน (dorm/library):
  /login          — landing page + ปุ่ม login ผ่าน Hub
  /login/start    — เริ่ม OAuth PKCE
  /oauth/callback — Hub ส่ง code กลับ → verify JWT → set session
  /               — redirect ตาม role (student→/grades, teacher/staff→/teacher)
  /grades         — เกรดของฉัน (นักศึกษา)
  /profile        — โปรไฟล์ (จาก JWT claims)
  /teacher        — นักศึกษาทั้งหมด (อาจารย์/เจ้าหน้าที่)
  /manage         — Sync ข้อมูล (อาจารย์/เจ้าหน้าที่ = "หน้านักพัฒนา")

session: itsdangerous signed cookie (HttpOnly) เก็บ claims จาก JWT.
"""

from __future__ import annotations

import secrets

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from app.config import settings
from app import db, hub_client, roster
from app.webhook import router as webhook_router

app = FastAPI(title="ระบบเกรด (Grade System)")
app.include_router(webhook_router)  # /internal/access-* (Hub back-channel)
templates = Jinja2Templates(directory="templates")

_signer = URLSafeTimedSerializer(settings.session_secret_key, salt="grade-session")
_oauth_flows: dict[str, str] = {}  # state → code_verifier (in-memory, demo)

_STAFF_ROLES = ("teacher", "staff")
_GPA_POINTS = {
    "A": 4.0,
    "B+": 3.5,
    "B": 3.0,
    "C+": 2.5,
    "C": 2.0,
    "D+": 1.5,
    "D": 1.0,
    "F": 0.0,
}

# ทุก claim ที่ Hub อาจส่งมาตาม scope (create_subsystem_token) — เก็บทุกตัวที่มี
# เพื่อให้ profile แสดงครบไม่ว่า subsystem จะตั้ง scope แบบไหน. sub/user_type
# ส่งมาเสมอ (ไม่ขึ้นกับ scope), ที่เหลือขึ้นกับ scope: email/profile/phone/address
_PROFILE_CLAIMS = (
    "email",
    "name",
    "student_id",
    "employee_id",
    "faculty",
    "major",
    "year",
    "position",
    "phone",
    "address",
)


@app.on_event("startup")
def _startup() -> None:
    db.init_db()


# ── session helpers ──


def _set_session(resp, data: dict) -> None:
    resp.set_cookie(
        settings.session_cookie_name,
        _signer.dumps(data),
        max_age=settings.session_max_age_seconds,
        httponly=True,
        samesite="lax",
    )


def _user(request: Request) -> dict | None:
    """อ่าน session cookie + เช็ค Hub revocation.

    ถ้า Hub push access_revoked/updated (scope/role เปลี่ยน) → session ที่ออก
    "ก่อน" เวลา re-auth ถือว่าหมดสิทธิ์ → คืน None (route จะ redirect ไป /login
    ให้ login ใหม่ = "เด้งออก" ทันทีไม่ต้องรอ JWT หมดอายุ).
    """
    raw = request.cookies.get(settings.session_cookie_name)
    if not raw:
        return None
    try:
        # return_timestamp → ได้เวลา issued ของ cookie มาเทียบกับ reauth_after
        data, issued_at = _signer.loads(
            raw, max_age=settings.session_max_age_seconds, return_timestamp=True
        )
    except (BadSignature, SignatureExpired):
        return None

    issued_epoch = int(issued_at.timestamp())
    uid = data.get("hub_user_id")
    reauth = max(
        db.reauth_after(uid) or 0 if uid else 0,
        db.reauth_after(db.GLOBAL_REAUTH) or 0,  # config ทั้งระบบเปลี่ยน
    )
    if reauth and reauth >= issued_epoch:
        return None  # session ออกก่อน re-auth → เด้งออก
    return data


def _compute_gpa(grades: list[dict]) -> float | None:
    if not grades:
        return None
    pts = sum(_GPA_POINTS.get(g["grade"], 0) * g["credits"] for g in grades)
    cr = sum(g["credits"] for g in grades)
    return round(pts / cr, 2) if cr else None


# ── auth flow ──


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if _user(request):
        return RedirectResponse("/")
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/login/start")
def login_start():
    state = secrets.token_urlsafe(16)
    verifier, challenge = hub_client.generate_pkce_pair()
    _oauth_flows[state] = verifier
    return RedirectResponse(hub_client.build_authorize_url(state, challenge))


@app.get("/oauth/callback")
async def oauth_callback(request: Request, code: str = "", state: str = ""):
    verifier = _oauth_flows.pop(state, None)
    if not verifier or not code:
        return RedirectResponse("/login?error=oauth_state")
    try:
        token_resp = await hub_client.exchange_code_for_token(code, verifier)
        claims = await hub_client.verify_hub_jwt(token_resp["access_token"])
    except Exception as e:
        return RedirectResponse(f"/login?error=verify:{type(e).__name__}")

    sess = {
        "hub_user_id": claims["sub"],
        "user_type": claims.get("user_type"),
    }
    # เก็บทุก profile claim ที่ Hub ส่งมา (ตาม scope ที่ subsystem ตั้งไว้)
    for key in _PROFILE_CLAIMS:
        if claims.get(key) is not None:
            sess[key] = claims[key]

    resp = RedirectResponse("/")
    _set_session(resp, sess)
    return resp


@app.post("/logout")
async def logout(request: Request):
    u = _user(request)
    if u:
        await hub_client.notify_hub_logout(u["hub_user_id"])
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(settings.session_cookie_name)
    return resp


# ── pages ──


@app.get("/")
def index(request: Request):
    u = _user(request)
    if not u:
        return RedirectResponse("/login")
    if u.get("user_type") in _STAFF_ROLES:
        return RedirectResponse("/teacher")
    return RedirectResponse("/grades")


@app.get("/grades", response_class=HTMLResponse)
def my_grades(request: Request):
    u = _user(request)
    if not u:
        return RedirectResponse("/login")
    grades = db.grades_for(u["hub_user_id"])
    return templates.TemplateResponse(
        "grades.html",
        {
            "request": request,
            "user": u,
            "active": "grades",
            "grades": grades,
            "gpa": _compute_gpa(grades),
            "total_credits": sum(g["credits"] for g in grades),
        },
    )


# label ไทยของแต่ละ claim (สำหรับแสดงใน profile) + ลำดับ
_CLAIM_LABELS = [
    ("email", "อีเมล"),
    ("student_id", "รหัสนักศึกษา"),
    ("employee_id", "รหัสพนักงาน"),
    ("faculty", "คณะ"),
    ("major", "สาขา"),
    ("year", "ชั้นปี"),
    ("position", "ตำแหน่ง"),
    ("phone", "เบอร์โทร"),
    ("address", "ที่อยู่"),
]


@app.get("/profile", response_class=HTMLResponse)
def profile(request: Request):
    u = _user(request)
    if not u:
        return RedirectResponse("/login")
    # เฉพาะ field ที่มีค่าจริงใน session (มาตาม scope) → หน้า profile ปรับตามได้เอง
    fields = [(label, u[key]) for key, label in _CLAIM_LABELS if u.get(key)]
    # scope ที่ "ไม่มา" (subsystem ไม่ได้ขอ) — โชว์ให้เห็นว่าถ้าอยากได้ต้องเพิ่ม scope
    missing = [label for key, label in _CLAIM_LABELS if not u.get(key)]
    return templates.TemplateResponse(
        "profile.html",
        {
            "request": request,
            "user": u,
            "active": "profile",
            "fields": fields,
            "missing": missing,
        },
    )


@app.get("/teacher", response_class=HTMLResponse)
def teacher_dashboard(request: Request, q: str = ""):
    u = _user(request)
    if not u:
        return RedirectResponse("/login")
    if u.get("user_type") not in _STAFF_ROLES:
        return RedirectResponse("/grades")  # นักศึกษาเข้าหน้านี้ไม่ได้
    students = db.all_students(q or None)
    rows = [
        {
            **s,
            "grades": (gr := db.grades_for(s["hub_user_id"])),
            "gpa": _compute_gpa(gr),
        }
        for s in students
    ]
    return templates.TemplateResponse(
        "teacher.html",
        {
            "request": request,
            "user": u,
            "active": "teacher",
            "students": rows,
            "q": q,
            "stats": db.stats(),
        },
    )


@app.get("/manage", response_class=HTMLResponse)
def manage(request: Request):
    u = _user(request)
    if not u:
        return RedirectResponse("/login")
    if u.get("user_type") not in _STAFF_ROLES:
        return RedirectResponse("/grades")
    return templates.TemplateResponse(
        "manage.html",
        {"request": request, "user": u, "active": "manage", "stats": db.stats()},
    )


@app.post("/manage/sync")
def manage_sync(request: Request):
    """Sync roster — เฉพาะ teacher/staff (ย้ายจากหน้า public มาไว้ที่นี่)."""
    u = _user(request)
    if not u or u.get("user_type") not in _STAFF_ROLES:
        return RedirectResponse("/login", status_code=303)
    try:
        result = roster.sync()
    except Exception as e:
        return RedirectResponse(f"/manage?error=sync:{e}", status_code=303)
    return RedirectResponse(
        f"/manage?msg=Sync สำเร็จ — {result['students']} นักศึกษา, "
        f"{result['grade_rows']} รายการเกรด",
        status_code=303,
    )


@app.get("/health")
def health():
    return {"status": "ok", **db.stats()}
