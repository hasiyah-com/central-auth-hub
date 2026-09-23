"""One-time client credential retrieval page."""

from datetime import datetime
from html import escape
from secrets import token_urlsafe

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_client_ip
from app.models import SecretRetrievalToken, Subsystem
from app.services.audit_service import log_action
from app.services.secret_service import decrypt_secret, hash_retrieval_token

router = APIRouter()

_PAGE_STYLE = """
@import url('https://fonts.googleapis.com/css2?family=Sarabun:wght@400;500;600;700;800&family=IBM+Plex+Mono:wght@400;500;600&display=swap');
:root { color-scheme: light; --ink:#111827; --muted:#68778c; --line:#dfe5ed; --signal:#34e8c4; --signal-dark:#087f70; }
* { box-sizing:border-box; }
body { margin:0; min-height:100vh; padding:32px 16px; display:grid; place-items:center;
  color:var(--ink); font-family:Sarabun,'Noto Sans Thai',system-ui,sans-serif;
  background:radial-gradient(circle at 88% 6%,rgba(52,232,196,.17),transparent 34rem),#f5f7fa; }
button { font:inherit; }
button:focus-visible { outline:3px solid var(--signal-dark); outline-offset:3px; }
.shell { width:min(100%,640px); border:1px solid var(--line); border-radius:20px;
  background:#fff; box-shadow:0 24px 72px rgba(10,14,23,.12); overflow:hidden; }
.top { background:#0a0e17; color:#fff; padding:23px 30px 26px; position:relative; }
.top:after { content:''; display:block; position:absolute; left:30px; bottom:0; width:54px;
  height:3px; border-radius:4px; background:var(--signal); }
.brand { display:flex; align-items:center; gap:12px; }
.mark { display:grid; place-items:center; width:36px; height:36px; flex:none;
  border:1px solid rgba(52,232,196,.55); border-radius:10px; color:var(--signal); font-weight:800; }
.brand strong { font-size:14px; line-height:1; }
.brand small { display:block; margin-top:4px; color:#99a9bc; font-size:10px;
  letter-spacing:.15em; text-transform:uppercase; }
.signal { margin-left:auto; width:9px; height:9px; border-radius:50%; background:var(--signal);
  box-shadow:0 0 0 4px rgba(52,232,196,.12),0 0 14px rgba(52,232,196,.6); }
.content { padding:30px; }
.kicker { color:var(--signal-dark); font-size:11px; font-weight:800;
  letter-spacing:.14em; text-transform:uppercase; }
h1 { margin:8px 0 10px; font-size:clamp(23px,4vw,29px); line-height:1.3; letter-spacing:-.03em; }
.lead { margin:0 0 24px; color:#526176; font-size:14px; line-height:1.7; }
.credential { margin:16px 0; }
.credential label { display:block; margin:0 0 8px; color:#526176; font-size:11px;
  font-weight:800; letter-spacing:.1em; text-transform:uppercase; }
.value { display:block; width:100%; padding:14px 16px; border:1px solid #26364a;
  border-radius:10px; background:#111726; color:#dafff6; font:500 13px/1.6 'IBM Plex Mono',ui-monospace,monospace;
  overflow-wrap:anywhere; user-select:all; }
.value.id { color:#b5d6fc; }
.copy-all { display:flex; justify-content:center; align-items:center; gap:10px;
  width:100%; min-height:48px; margin-top:24px; padding:11px 16px; cursor:pointer;
  border:0; border-radius:10px; color:#072f2a; background:var(--signal);
  font-size:14px; font-weight:800; transition:background .15s,transform .15s; }
.copy-all:hover { background:#61f4d7; transform:translateY(-1px); }
.copy-all:active { transform:translateY(0); }
.copy-all svg { width:18px; height:18px; }
.copy-status { min-height:22px; margin:7px 0 0; color:var(--signal-dark); font-size:12px; text-align:center; }
.note { margin-top:17px; padding:14px 16px; border:1px solid #f4d48a;
  border-left:3px solid #d68a10; border-radius:9px; background:#fffaf0;
  color:#77501a; font-size:13px; line-height:1.65; }
.note strong { display:block; margin-bottom:2px; }
code { font-family:'IBM Plex Mono',ui-monospace,monospace; font-size:.95em; }
.footer { padding:16px 30px; border-top:1px solid var(--line); color:#8090a3;
  font-size:11px; line-height:1.5; }
.icon { display:inline-grid; place-items:center; width:42px; height:42px; margin-bottom:16px;
  border-radius:11px; background:#ecfdf8; color:#087f70; font-size:20px; }
.icon.error { background:#fff1f2; color:#be123c; }
.icon.lock { background:#f1f5f9; color:#475569; }
@media (max-width:480px) {
  body { padding:16px 10px; align-items:start; }
  .top { padding:19px 20px 22px; }
  .top:after { left:20px; }
  .content { padding:24px 20px; }
  .footer { padding:15px 20px; }
}
"""

_COPY_SCRIPT = """
(function () {
  var button = document.getElementById('copy-all');
  if (!button) return;
  button.addEventListener('click', async function () {
    var clientId = document.getElementById('client-id').textContent.trim();
    var clientSecret = document.getElementById('client-secret').textContent.trim();
    var value = 'CLIENT_ID=' + clientId + '\\nCLIENT_SECRET=' + clientSecret;
    var status = document.getElementById('copy-status');
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(value);
      } else {
        var field = document.createElement('textarea');
        field.value = value;
        field.setAttribute('readonly', '');
        field.style.position = 'fixed';
        field.style.opacity = '0';
        document.body.appendChild(field);
        field.select();
        var copied = document.execCommand('copy');
        field.remove();
        if (!copied) throw new Error('clipboard unavailable');
      }
      status.textContent = 'คัดลอก Client ID และ Client Secret แล้ว';
      button.setAttribute('aria-label', 'คัดลอกข้อมูลทั้งสองอีกครั้ง');
    } catch (error) {
      status.textContent = 'คัดลอกไม่สำเร็จ กรุณาเลือกและคัดลอกข้อมูลด้านบนด้วยตนเอง';
    }
  });
})();
"""


def _page(
    request: Request,
    title: str,
    kicker: str,
    lead: str,
    body: str = "",
    *,
    icon: str = "",
    icon_class: str = "",
    status: int = 200,
    clean_url: bool = False,
    copy_script: bool = False,
) -> HTMLResponse:
    """Render the same branded page for success, expiry and refresh."""
    nonce = token_urlsafe(16)
    request.state.csp_nonce = nonce
    scripts = (
        '<script nonce="' + nonce + '">history.replaceState({}, "", "/secret/retrieved");</script>'
        if clean_url else ""
    )
    if copy_script:
        scripts += '<script nonce="' + nonce + '">' + _COPY_SCRIPT + '</script>'
    icon_markup = (
        '<span class="icon ' + icon_class + '" aria-hidden="true">' + icon + '</span>'
        if icon else ""
    )
    html = f"""<!DOCTYPE html><html lang="th"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>{escape(title)} · Central Auth Hub</title>
<style nonce="{nonce}">{_PAGE_STYLE}</style></head><body>
<div class="shell">
  <header class="top"><div class="brand">
    <span class="mark" aria-hidden="true">H</span>
    <span><strong>Central Auth Hub</strong><small>Identity &amp; Access</small></span>
    <span class="signal" aria-hidden="true"></span>
  </div></header>
  <main class="content">
    {icon_markup}
    <div class="kicker">{escape(kicker)}</div>
    <h1>{escape(title)}</h1>
    <p class="lead">{escape(lead)}</p>
    {body}
  </main>
  <footer class="footer">Central Auth Hub · ส่งข้อมูลยืนยันตัวตนแบบใช้ครั้งเดียว</footer>
</div>
{scripts}
</body></html>"""
    return HTMLResponse(
        content=html,
        status_code=status,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


def _error_page(request: Request, title: str, message: str, status: int = 410) -> HTMLResponse:
    return _page(
        request, title, "ไม่สามารถแสดงข้อมูลได้", message,
        body='<div class="note">หากต้องการ Client Secret ใหม่ ให้สร้างคีย์ใหม่ใน Developer Portal</div>',
        icon="!", icon_class="error", status=status, clean_url=True,
    )


@router.get("/retrieve", response_class=HTMLResponse)
def retrieve_secret(
    token: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Reveal the secret once, then remove the token from browser history."""
    token_hash = hash_retrieval_token(token)
    rt = (
        db.query(SecretRetrievalToken)
        .filter(SecretRetrievalToken.token == token_hash)
        .first()
    )
    if not rt:
        return _error_page(request, "ลิงก์ไม่ถูกต้อง", "ไม่พบลิงก์นี้ในระบบ", status=404)
    if rt.used_at is not None:
        return _error_page(request, "ลิงก์ถูกใช้ไปแล้ว", "Client Secret ถูกแสดงไปแล้วครั้งหนึ่ง และไม่สามารถดูซ้ำได้")
    if rt.expires_at < datetime.utcnow():
        return _error_page(request, "ลิงก์หมดอายุแล้ว", "ลิงก์นี้มีอายุ 15 นาที และหมดเวลาแล้ว")

    client_secret = decrypt_secret(rt.secret_encrypted)
    subsystem = db.query(Subsystem).filter(Subsystem.id == rt.subsystem_id).first()
    client_id = subsystem.client_id if subsystem else "(unknown)"
    sub_name = subsystem.name if subsystem else "(unknown)"

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

    body = f"""
    <section class="credential">
      <label for="client-id">Client ID</label>
      <code class="value id" id="client-id">{escape(client_id)}</code>
    </section>
    <section class="credential">
      <label for="client-secret">Client Secret</label>
      <code class="value" id="client-secret">{escape(client_secret)}</code>
    </section>
    <button type="button" class="copy-all" id="copy-all">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <rect x="8" y="8" width="12" height="12" rx="2"></rect>
        <path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"></path>
      </svg>
      คัดลอก Client ID และ Client Secret
    </button>
    <p class="copy-status" id="copy-status" role="status" aria-live="polite"></p>
    <div class="note"><strong>บันทึกข้อมูลนี้ทันที</strong>
      ระบบแสดง Client Secret เพียงครั้งเดียว เมื่อลองเปิดลิงก์ใหม่หรือรีเฟรชจะดูซ้ำไม่ได้
      วางข้อมูลที่คัดลอกลงใน <code>.env</code> ของระบบย่อยและเก็บให้ปลอดภัย
    </div>"""
    return _page(
        request, sub_name, "ข้อมูลเชื่อมต่อระบบย่อย",
        "คัดลอกข้อมูลทั้งสองรายการได้ในครั้งเดียว ลิงก์นี้ใช้แสดง Client Secret ได้เพียงครั้งเดียว",
        body, icon="✦", clean_url=True, copy_script=True,
    )


@router.get("/retrieved", response_class=HTMLResponse)
def secret_retrieved_landing(request: Request):
    """Safe destination after removing the one-time token from the URL."""
    return _page(
        request, "Client Secret ถูกแสดงไปแล้ว", "ปิดการแสดงผล",
        "ข้อมูลนี้แสดงได้ครั้งเดียว หากยังไม่ได้บันทึก ให้ไปที่ Developer Portal และสร้างคีย์ใหม่",
        icon="×", icon_class="lock",
    )
