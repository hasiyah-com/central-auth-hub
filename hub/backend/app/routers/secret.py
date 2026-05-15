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
from app.models import SecretRetrievalToken, Subsystem
from app.services.audit_service import log_action
from app.services.secret_service import decrypt_secret

router = APIRouter()


# ============ HTML templates ============

_PAGE_STYLE = """
  body { font-family: system-ui, -apple-system, "Sarabun", sans-serif;
         background: #f1f5f9; margin: 0; padding: 40px 16px; color: #0f172a; }
  .box { max-width: 540px; margin: 0 auto; background: #fff; border-radius: 12px;
         padding: 28px 32px; box-shadow: 0 1px 3px rgba(0,0,0,.1); }
  h1 { font-size: 20px; margin: 0 0 8px; }
  .secret { font-family: "JetBrains Mono", monospace; background: #1f2937;
            color: #86efac; padding: 14px 16px; border-radius: 8px;
            word-break: break-all; font-size: 14px; margin: 14px 0; }
  .label { font-size: 12px; color: #64748b; margin-top: 12px; }
  .mono { font-family: monospace; background: #f1f5f9; padding: 2px 6px;
          border-radius: 4px; font-size: 13px; }
  .warn { background: #fef2f2; border-left: 4px solid #dc2626; padding: 12px 14px;
          border-radius: 4px; font-size: 13px; margin-top: 16px; color: #991b1b; }
  .ok { color: #16a34a; } .err { color: #dc2626; }
  button { background: #534ab7; color: #fff; border: 0; padding: 8px 16px;
           border-radius: 6px; cursor: pointer; font-size: 13px; }
"""


def _clean_url_script(target: str = "/secret/retrieved") -> str:
    """JS ลบ token ออกจาก address bar + history ทันทีที่หน้าโหลด."""
    return f"<script>history.replaceState({{}}, '', '{target}');</script>"


def _error_page(title: str, message: str, status: int = 410) -> HTMLResponse:
    html = f"""<!DOCTYPE html><html lang="th"><head><meta charset="UTF-8">
<title>{title}</title><style>{_PAGE_STYLE}</style></head><body>
<div class="box">
  <h1 class="err">⚠️ {title}</h1>
  <p>{message}</p>
  <p class="label">หากต้องการ client_secret ใหม่ ให้ rotate key ที่ Developer Portal</p>
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
    rt = (
        db.query(SecretRetrievalToken)
        .filter(SecretRetrievalToken.token == token)
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
        ip=request.client.host if request.client else None,
    )
    db.commit()

    html = f"""<!DOCTYPE html><html lang="th"><head><meta charset="UTF-8">
<title>Client Secret</title><style>{_PAGE_STYLE}</style></head><body>
<div class="box">
  <h1 class="ok">✓ ลงทะเบียนสำเร็จ — {sub_name}</h1>
  <p>นี่คือ credentials ของระบบย่อยคุณ <strong>แสดงเพียงครั้งเดียวเท่านั้น</strong></p>

  <div class="label">Client ID (เปิดเผยได้)</div>
  <div class="secret" style="color:#93c5fd">{client_id}</div>

  <div class="label">Client Secret (ความลับ — เก็บให้ดี)</div>
  <div class="secret" id="secret">{client_secret}</div>
  <button onclick="navigator.clipboard.writeText(document.getElementById('secret').innerText)">
    คัดลอก Client Secret
  </button>

  <div class="warn">
    <strong>เก็บ secret นี้ทันที</strong> — ใส่ใน <span class="mono">.env</span> ของระบบย่อย
    หากปิดหน้านี้แล้วจะดูซ้ำไม่ได้ ต้อง rotate key เพื่อสร้างใหม่
  </div>
</div>
{_clean_url_script()}
</body></html>"""
    return HTMLResponse(content=html)


# ============ 2. retrieved — หน้าปลายทางหลัง replaceState ============

@router.get("/retrieved", response_class=HTMLResponse)
def secret_retrieved_landing():
    """หน้าที่ address bar ชี้ไปหลังลบ token — refresh มาที่นี่ก็ปลอดภัย."""
    html = f"""<!DOCTYPE html><html lang="th"><head><meta charset="UTF-8">
<title>Secret Retrieved</title><style>{_PAGE_STYLE}</style></head><body>
<div class="box">
  <h1>🔒 client_secret ถูกแสดงไปแล้ว</h1>
  <p>ด้วยเหตุผลด้านความปลอดภัย client_secret แสดงเพียงครั้งเดียว
     และไม่สามารถเรียกดูซ้ำได้</p>
  <p class="label">หากยังไม่ได้บันทึก secret ไว้ ให้ไปที่ Developer Portal
     แล้วกด "Rotate Key" เพื่อสร้าง secret ใหม่</p>
</div>
</body></html>"""
    return HTMLResponse(content=html)
