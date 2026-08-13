"""Secret retrieval router — one-time link สำหรับดู client_secret.

ความปลอดภัยเรื่อง URL:
  - หน้า retrieve คืนเป็น HTML + JavaScript history.replaceState()
    ทำให้ token หายจาก address bar ทันทีหลังโหลด
  - token ใช้ครั้งเดียว + หมดอายุ 15 นาที (ถึงรั่วก็ใช้ไม่ได้)
  - refresh หน้าหลัง replaceState จะไปที่ /secret/retrieved (ไม่มี token)
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_client_ip
from app.models import SecretRetrievalToken, Subsystem
from app.services.audit_service import log_action
from app.services.secret_service import decrypt_secret, hash_retrieval_token

router = APIRouter()


# ============ HTML templates ============

_PAGE_STYLE = """
  @import url('https://fonts.googleapis.com/css2?family=Sarabun:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap');
  * { box-sizing: border-box; }
  body { font-family: 'Sarabun', system-ui, -apple-system, 'Segoe UI', sans-serif;
         background: linear-gradient(160deg,#0f172a,#1e293b 55%,#312e81);
         margin: 0; min-height: 100vh; display: grid; place-items: center;
         padding: 40px 16px; color: #0f172a; }
  .box { max-width: 520px; width: 100%; background: #fff; border-radius: 20px;
         overflow: hidden; box-shadow: 0 24px 60px rgba(2,6,23,.45); }
  .brandbar { display: flex; align-items: center; gap: 11px; padding: 16px 28px;
              border-bottom: 1px solid #eef2ff; }
  .mark { width: 34px; height: 34px; border-radius: 10px;
          background: linear-gradient(135deg,#6366f1,#312e81); color: #fff;
          display: grid; place-items: center; font-weight: 800; font-size: 16px; }
  .brandname { font-weight: 800; font-size: 13px; color: #0f172a; line-height: 1.1; }
  .brandsub { font-size: 9.5px; letter-spacing: .18em; color: #94a3b8;
              font-weight: 700; text-transform: uppercase; margin-top: 2px; }
  .hero { padding: 26px 28px 4px; text-align: center; }
  .hicon { width: 60px; height: 60px; border-radius: 16px; margin: 0 auto 14px;
           display: grid; place-items: center; font-size: 28px; }
  .hicon.ok { background: #ecfdf5; border: 1px solid #a7f3d0; }
  .hicon.err { background: #fff1f2; border: 1px solid #fecdd3; }
  .hicon.lock { background: #f1f5f9; border: 1px solid #e2e8f0; }
  .eyebrow { font-size: 11px; letter-spacing: .14em; text-transform: uppercase;
             font-weight: 700; color: #64748b; }
  h1 { font-size: 20px; margin: 8px 0 0; font-weight: 800; color: #0f172a; }
  h1.ok { color: #047857; } h1.err { color: #be123c; }
  .pad { padding: 14px 30px 26px; }
  p { font-size: 14px; line-height: 1.65; color: #475569; margin: 10px 0; }
  .label { font-size: 11px; font-weight: 700; letter-spacing: .05em;
           text-transform: uppercase; color: #94a3b8; margin: 18px 0 6px; }
  .secret { font-family: 'JetBrains Mono', ui-monospace, monospace; background: #0f172a;
            color: #86efac; padding: 13px 15px; border-radius: 11px;
            word-break: break-all; font-size: 13.5px; display: flex; gap: 10px;
            align-items: center; justify-content: space-between; }
  .secret.id { color: #93c5fd; }
  .copy { background: rgba(255,255,255,.12); color: #fff; border: 0; padding: 7px 13px;
          border-radius: 8px; cursor: pointer; font-size: 12px; font-weight: 700;
          font-family: inherit; white-space: nowrap; flex-shrink: 0; }
  .copy:hover { background: rgba(255,255,255,.24); }
  .mono { font-family: 'JetBrains Mono', monospace; background: #f1f5f9;
          padding: 2px 6px; border-radius: 4px; font-size: 13px; }
  .warn { background: #fffbeb; border: 1px solid #fde68a; border-left: 4px solid #d97706;
          padding: 13px 15px; border-radius: 10px; font-size: 13px; margin-top: 20px;
          color: #92400e; line-height: 1.6; }
  .footer { padding: 14px 30px; font-size: 11px; color: #94a3b8;
            border-top: 1px solid #f1f5f9; text-align: center; }
"""


def _clean_url_script(target: str = "/secret/retrieved") -> str:
    """JS ลบ token ออกจาก address bar + history ทันทีที่หน้าโหลด."""
    return f"<script>history.replaceState({{}}, '', '{target}');</script>"


def _error_page(title: str, message: str, status: int = 410) -> HTMLResponse:
    html = f"""<!DOCTYPE html><html lang="th"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · Central Auth Hub</title><style>{_PAGE_STYLE}</style></head><body>
<div class="box">
  <div class="brandbar">
    <div class="mark">H</div>
    <div><div class="brandname">Central Auth Hub</div>
         <div class="brandsub">Identity &amp; Access</div></div>
  </div>
  <div class="hero">
    <div class="hicon err">⚠️</div>
    <div class="eyebrow">ไม่สามารถแสดง Client Secret</div>
    <h1 class="err">{title}</h1>
  </div>
  <div class="pad">
    <p>{message}</p>
    <p class="label" style="text-transform:none;letter-spacing:0;color:#64748b;font-weight:400;font-size:13px;margin-top:8px">
      หากต้องการ client_secret ใหม่ ให้ rotate key ที่ Developer Portal
    </p>
  </div>
  <div class="footer">Central Auth Hub · one-time secret delivery</div>
</div>
{_clean_url_script()}
</body></html>"""
    return HTMLResponse(content=html, status_code=status)


# ============ 1. retrieve — ดู secret ครั้งเดียว ============


@router.get("/retrieve", response_class=HTMLResponse)
def retrieve_secret(
    token: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """ดู client_secret ผ่าน one-time link.

    หน้านี้คืน HTML + JS ที่ลบ token ออกจาก URL ทันที — address bar
    จะแสดง /secret/retrieved (ไม่มี token) หลังโหลดเสร็จ
    """
    # DB เก็บ HMAC ของ token — ต้อง hash ก่อน lookup
    token_hash = hash_retrieval_token(token)
    rt = (
        db.query(SecretRetrievalToken)
        .filter(SecretRetrievalToken.token == token_hash)
        .first()
    )
    if not rt:
        return _error_page("ลิงก์ไม่ถูกต้อง", "ไม่พบ token นี้ในระบบ", status=404)

    if rt.used_at is not None:
        return _error_page(
            "ลิงก์ถูกใช้ไปแล้ว",
            "client_secret ถูกแสดงไปแล้วครั้งหนึ่ง — ดูซ้ำไม่ได้",
        )

    if rt.expires_at < datetime.utcnow():
        return _error_page(
            "ลิงก์หมดอายุแล้ว",
            "ลิงก์นี้มีอายุ 15 นาที และหมดเวลาแล้ว",
        )

    # ผ่านทุกเงื่อนไข — ถอดรหัส secret
    client_secret = decrypt_secret(rt.secret_encrypted)
    subsystem = db.query(Subsystem).filter(Subsystem.id == rt.subsystem_id).first()
    client_id = subsystem.client_id if subsystem else "(unknown)"
    sub_name = subsystem.name if subsystem else "(unknown)"

    # mark used + ลบ encrypted secret ทันที (one-time)
    rt.used_at = datetime.utcnow()
    rt.secret_encrypted = ""
    log_action(
        db,
        actor_id=subsystem.owner_user_id if subsystem else None,
        action="secret_retrieved",
        target_type="subsystem",
        target_id=rt.subsystem_id,
        ip=get_client_ip(request),
    )
    db.commit()

    html = f"""<!DOCTYPE html><html lang="th"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Client Secret · Central Auth Hub</title><style>{_PAGE_STYLE}</style></head><body>
<div class="box">
  <div class="brandbar">
    <div class="mark">H</div>
    <div><div class="brandname">Central Auth Hub</div>
         <div class="brandsub">Identity &amp; Access</div></div>
  </div>
  <div class="hero">
    <div class="hicon ok">🔑</div>
    <div class="eyebrow">ลงทะเบียนระบบย่อยสำเร็จ</div>
    <h1 class="ok">{sub_name}</h1>
  </div>
  <div class="pad">
    <p style="text-align:center;margin-top:2px">นี่คือ credentials ของระบบย่อยคุณ — <strong>แสดงเพียงครั้งเดียวเท่านั้น</strong></p>

    <div class="label">Client ID (เปิดเผยได้)</div>
    <div class="secret id">
      <span id="clientid">{client_id}</span>
      <button class="copy" onclick="navigator.clipboard.writeText(document.getElementById('clientid').innerText);this.textContent='✓ คัดลอกแล้ว'">คัดลอก</button>
    </div>

    <div class="label">Client Secret (ความลับ — เก็บให้ดี)</div>
    <div class="secret">
      <span id="secretval">{client_secret}</span>
      <button class="copy" onclick="navigator.clipboard.writeText(document.getElementById('secretval').innerText);this.textContent='✓ คัดลอกแล้ว'">คัดลอก</button>
    </div>

    <div class="warn">
      <strong>เก็บ secret นี้ทันที</strong> — ใส่ใน <span class="mono">.env</span> ของระบบย่อย
      หากปิดหน้านี้แล้วจะดูซ้ำไม่ได้ ต้อง rotate key เพื่อสร้างใหม่
    </div>
  </div>
  <div class="footer">Central Auth Hub · one-time secret delivery · ลิงก์นี้ใช้ได้ครั้งเดียว</div>
</div>
{_clean_url_script()}
</body></html>"""
    return HTMLResponse(content=html)


# ============ 2. retrieved — หน้าปลายทางหลัง replaceState ============


@router.get("/retrieved", response_class=HTMLResponse)
def secret_retrieved_landing():
    """หน้าที่ address bar ชี้ไปหลังลบ token — refresh มาที่นี่ก็ปลอดภัย."""
    html = f"""<!DOCTYPE html><html lang="th"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Secret Retrieved · Central Auth Hub</title><style>{_PAGE_STYLE}</style></head><body>
<div class="box">
  <div class="brandbar">
    <div class="mark">H</div>
    <div><div class="brandname">Central Auth Hub</div>
         <div class="brandsub">Identity &amp; Access</div></div>
  </div>
  <div class="hero">
    <div class="hicon lock">🔒</div>
    <div class="eyebrow">One-time secret · ปิดการแสดงผลแล้ว</div>
    <h1>client_secret ถูกแสดงไปแล้ว</h1>
  </div>
  <div class="pad">
    <p style="text-align:center">ด้วยเหตุผลด้านความปลอดภัย client_secret แสดงเพียงครั้งเดียว
       และไม่สามารถเรียกดูซ้ำได้</p>
    <p class="label" style="text-transform:none;letter-spacing:0;color:#64748b;font-weight:400;font-size:13px;text-align:center;margin-top:8px">
       หากยังไม่ได้บันทึก secret ไว้ ให้ไปที่ Developer Portal แล้วกด &quot;Rotate Key&quot; เพื่อสร้าง secret ใหม่</p>
  </div>
  <div class="footer">Central Auth Hub · one-time secret delivery</div>
</div>
</body></html>"""
    return HTMLResponse(content=html)
