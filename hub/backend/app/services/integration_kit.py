"""Build the non-secret Developer Integration Kit for one OAuth client."""

from __future__ import annotations

import io
import json
import re
import zipfile
from dataclasses import dataclass


@dataclass(frozen=True)
class IntegrationKit:
    filename: str
    content: bytes


def _env_value(value: str) -> str:
    """Reject line injection and quote values using dotenv-compatible JSON syntax."""
    value = str(value)
    if "\n" in value or "\r" in value or "\x00" in value:
        raise ValueError("integration-kit value contains a control character")
    return json.dumps(value, ensure_ascii=False)


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", (name or "subsystem").strip())
    return cleaned.strip("-.")[:80] or "subsystem"


def build_integration_kit(
    *,
    subsystem_name: str,
    client_id: str,
    redirect_uris: list[str],
    scopes: list[str],
    issuer: str,
    hub_base_url: str,
) -> IntegrationKit:
    """Return a ZIP containing current registration data, env example, and Thai guide."""
    redirects = [str(v).strip() for v in redirect_uris if str(v).strip()]
    scope_values = [str(v).strip() for v in scopes if str(v).strip()]
    callback = redirects[0] if redirects else "https://your-app.example/auth/callback"
    base = hub_base_url.rstrip("/")

    env_text = "\n".join(
        [
            "# Central Auth Hub — server-side only",
            f"CENTRAL_AUTH_ISSUER={_env_value(issuer)}",
            f"CENTRAL_AUTH_BASE_URL={_env_value(base)}",
            f"CENTRAL_AUTH_CLIENT_ID={_env_value(client_id)}",
            'CENTRAL_AUTH_CLIENT_SECRET="replace-with-the-secret-from-the-one-time-email-link"',
            f"CENTRAL_AUTH_REDIRECT_URI={_env_value(callback)}",
            f"CENTRAL_AUTH_SCOPES={_env_value(' '.join(scope_values))}",
            "",
        ]
    )

    registration = {
        "subsystem_name": subsystem_name,
        "client_id": client_id,
        "issuer": issuer,
        "hub_base_url": base,
        "redirect_uris": redirects,
        "scopes": scope_values,
        "authorization_endpoint": f"{base}/oauth/authorize",
        "token_endpoint": f"{base}/oauth/token",
        "jwks_uri": f"{base}/.well-known/jwks.json",
    }

    guide = f"""# คู่มือเชื่อมต่อ Central Auth Hub

ระบบย่อย: **{subsystem_name}**

## ไฟล์ในชุดนี้

- `.env.example` — ตัวอย่างค่าตั้งฝั่ง Backend
- `registration.json` — ค่าทะเบียน OAuth/OIDC ล่าสุดจาก Hub
- `README_TH.md` — คู่มือฉบับนี้

## ขั้นตอน

1. คัดลอก `.env.example` เป็น `.env` บน Backend ของระบบย่อย
2. เปิดลิงก์ Client Secret แบบครั้งเดียวจากอีเมล แล้วใส่ค่าใน
   `CENTRAL_AUTH_CLIENT_SECRET`
3. ตรวจว่า callback ของระบบย่อยตรงกับ Redirect URI ใน `registration.json`
   ทุกตัวอักษร รวม scheme, host, port, path และ trailing slash
4. เริ่ม Authorization Code flow และส่ง `redirect_uri` ค่าเดียวกับที่ลงทะเบียน
5. แลก authorization code ที่ token endpoint จากฝั่ง Backendเท่านั้น
6. ตรวจลายเซ็น JWT ด้วย JWKS และตรวจ `iss`, `aud`, `exp` ก่อนสร้าง session

## ข้อควรระวัง

- ห้ามใส่ Client Secret ในตัวแปร `NEXT_PUBLIC_*` หรือส่งไป JavaScript ฝั่ง browser
- ห้าม commit `.env` หรือ Client Secret เข้า Git
- ZIP นี้ไม่มี Client Secret จริง หากลิงก์หมดอายุหรือถูกเปิดแล้ว ให้ rotate secret
  จาก Developer Portal
"""

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(".env.example", env_text)
        archive.writestr(
            "registration.json",
            json.dumps(registration, ensure_ascii=False, indent=2) + "\n",
        )
        archive.writestr("README_TH.md", guide)

    return IntegrationKit(
        filename=f"central-auth-{_safe_filename(subsystem_name)}-integration.zip",
        content=buffer.getvalue(),
    )
