"""Passkey input-validation & attack-surface tests (API level, plan v3).

ทดสอบว่า login/register endpoints ป้องกัน:
  - non-email input (format validation via EmailStr)
  - SQL injection (ORM parameterization + format reject)
  - XSS payloads (format reject)
  - oversized payload (max_length DoS guard)
  - missing fields (422)

หลัก anti-enumeration ยังคงอยู่: email ที่ format ถูกแต่ไม่มีใน DB
→ ยังได้ challenge (200) เหมือน email ที่มีจริง (กันเดา account)

ใช้ TestClient (conftest `client` fixture) — ยิง HTTP จริงผ่าน FastAPI stack
รวม Pydantic validation layer.
"""

import pytest

LOGIN_START = "/auth/passkey/login/start"
LOGIN_FINISH = "/auth/passkey/login/finish"

# Inputs ที่ "ไม่ใช่ email" — ต้องโดน 422 ทุกตัว
NON_EMAIL_INPUTS = [
    "notanemail",  # ไม่มี @
    "x' OR '1'='1",  # SQLi classic
    "a@b.com'; DROP TABLE users;--",  # SQLi DROP
    "<script>alert(1)</script>",  # XSS
    "admin@",  # ไม่มี domain
    "@uni.ac.th",  # ไม่มี local part
    "a b@uni.ac.th",  # space ใน local
    "../../etc/passwd",  # path traversal
    "{{7*7}}",  # template injection
    "user@uni..ac.th",  # double dot domain
]


@pytest.mark.smoke
@pytest.mark.parametrize("bad", NON_EMAIL_INPUTS)
def test_login_start_rejects_non_email(client, bad):
    """ทุก non-email input → 422 (Pydantic EmailStr reject)."""
    r = client.post(LOGIN_START, json={"email": bad})
    assert r.status_code == 422, f"{bad!r} ควรโดน reject แต่ได้ {r.status_code}"
    body = r.json()
    assert body["detail"][0]["loc"] == ["body", "email"]


@pytest.mark.smoke
def test_login_start_missing_email_returns_422(client):
    """ไม่มี field email → 422 missing."""
    r = client.post(LOGIN_START, json={})
    assert r.status_code == 422
    assert r.json()["detail"][0]["type"] == "missing"


@pytest.mark.smoke
def test_login_start_oversized_email_returns_422(client):
    """email ยาวเกิน (320+ chars) → 422 (กัน DoS)."""
    huge = "a" * 320 + "@uni.ac.th"
    r = client.post(LOGIN_START, json={"email": huge})
    assert r.status_code == 422


@pytest.mark.smoke
def test_login_start_valid_email_returns_options(client):
    """email format ถูก (แม้ไม่มีใน DB) → 200 + challenge (anti-enumeration)."""
    r = client.post(LOGIN_START, json={"email": "nonexistent-xyz@uni.ac.th"})
    assert r.status_code == 200
    body = r.json()
    assert "challenge" in body
    assert body["userVerification"] == "required"
    # Anti-enum: ไม่มี Passkey → คืน decoy descriptor (list ไม่ว่าง) เพื่อให้
    # shape เหมือน email ที่มี passkey — แยกไม่ออกว่ามีจริงไหม
    assert len(body.get("allowCredentials", [])) >= 1


@pytest.mark.smoke
def test_login_start_sqli_does_not_execute(client):
    """SQLi payload → reject ที่ format layer + DB ยังอยู่ครบ.

    (ถ้า ORM ไม่ parameterize, DROP TABLE จะลบ users — ทดสอบว่าไม่เกิด)
    """
    before = client.post(LOGIN_START, json={"email": "probe@uni.ac.th"})
    assert before.status_code == 200  # baseline ok

    # ยิง SQLi — โดน 422 ที่ format ก่อนถึง DB
    r = client.post(LOGIN_START, json={"email": "a@b.com'; DROP TABLE users;--"})
    assert r.status_code == 422

    # baseline ยังทำงาน = users table ไม่ถูกแตะ
    after = client.post(LOGIN_START, json={"email": "probe@uni.ac.th"})
    assert after.status_code == 200


# ─── login/finish ───────────────────────────────────────────────────────────


@pytest.mark.smoke
@pytest.mark.parametrize("bad", ["notanemail", "x' OR 1=1--", "<img src=x>"])
def test_login_finish_rejects_non_email(client, bad):
    """finish ก็ต้อง validate email format."""
    r = client.post(LOGIN_FINISH, json={"email": bad, "credential": {}})
    assert r.status_code == 422


@pytest.mark.smoke
def test_login_finish_missing_credential_returns_422(client):
    """ไม่มี credential field → 422."""
    r = client.post(LOGIN_FINISH, json={"email": "user@uni.ac.th"})
    assert r.status_code == 422


@pytest.mark.smoke
def test_login_finish_valid_email_bad_credential_not_422(client):
    """email ถูก + credential เป็น dict (แม้ว่าง) → ผ่าน Pydantic.

    จากนั้น service layer reject (400 challenge missing / 401 invalid) —
    ไม่ใช่ 422 (Pydantic). พิสูจน์ว่า validation layer แยกจาก business logic.
    """
    r = client.post(
        LOGIN_FINISH,
        json={"email": "user@uni.ac.th", "credential": {"rawId": "AAAA"}},
    )
    assert r.status_code in (400, 401)  # business-layer reject, ไม่ใช่ 422


# ─── content-type / malformed body ──────────────────────────────────────────


@pytest.mark.smoke
def test_login_start_non_json_body_returns_422(client):
    """ส่ง body ที่ไม่ใช่ JSON → 422."""
    r = client.post(
        LOGIN_START,
        content="email=notjson",
        headers={"Content-Type": "text/plain"},
    )
    assert r.status_code in (422, 415)


# ─── Console /account/passkeys/* = developer only (RBAC, กัน student) ────────
#
# เดิม endpoint พวกนี้เป็น admin-only แต่ commit 53ab5cd (2026-07-05) เปลี่ยนเป็น
# require_developer (teacher/staff/admin) เพื่อแก้ deadlock: developer ต้องมี passkey
# ก่อนถึงจะลงทะเบียน subsystem ผ่าน step-up gate ได้ แต่เดิมเพิ่ม passkey ไม่ได้เพราะ
# ไม่ใช่ admin. RBAC ปัจจุบัน = กัน student เท่านั้น (ดู passkey.py docstring).

ACCOUNT_ENDPOINTS = [
    ("post", "/account/passkeys/register/start"),
    ("post", "/account/passkeys/register/finish"),
    ("post", "/account/passkeys/backup-codes/acknowledge"),
    ("get", "/account/passkeys/backup-codes/status"),
    ("get", "/account/passkeys"),  # Phase 3 — list
]


@pytest.mark.smoke
@pytest.mark.parametrize("method,path", ACCOUNT_ENDPOINTS)
def test_account_endpoints_require_auth(client, method, path):
    """ไม่มี token → 403 (HTTPBearer auto_error)."""
    if method == "post":
        r = client.post(path, json={})
    else:
        r = client.get(path)
    assert r.status_code in (401, 403)


@pytest.mark.smoke
@pytest.mark.parametrize("method,path", ACCOUNT_ENDPOINTS)
def test_account_endpoints_reject_student(
    client, auth_headers, student_token, method, path
):
    """student token → 403 (require_developer block student ก่อน body validation)."""
    headers = auth_headers(student_token)
    if method == "post":
        r = client.post(path, json={}, headers=headers)
    else:
        r = client.get(path, headers=headers)
    assert r.status_code == 403, f"{path} ควร block student แต่ได้ {r.status_code}"


@pytest.mark.smoke
@pytest.mark.parametrize("method,path", ACCOUNT_ENDPOINTS)
def test_account_endpoints_allow_developer(
    client, auth_headers, staff_token, method, path
):
    """staff token (developer) → ผ่าน RBAC = ไม่โดน 403.

    (register/finish จะได้ 422 จาก body ว่าง, GET status/list ได้ 200 —
    ทั้งหมดพิสูจน์ว่า require_developer ปล่อยผ่าน ไม่ block เหมือน student.)
    """
    headers = auth_headers(staff_token)
    if method == "post":
        r = client.post(path, json={}, headers=headers)
    else:
        r = client.get(path, headers=headers)
    assert r.status_code != 403, f"{path} ควรปล่อย developer ผ่าน แต่ได้ 403"


@pytest.mark.smoke
def test_account_status_allows_admin(client, auth_headers, admin_token):
    """admin token → backup-codes/status ผ่าน (200)."""
    r = client.get(
        "/account/passkeys/backup-codes/status",
        headers=auth_headers(admin_token),
    )
    assert r.status_code == 200
    assert "generation" in r.json()
