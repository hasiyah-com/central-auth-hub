"""SSRF guard สำหรับ subsystem health checker.

health checker ยิง GET {origin ของ redirect_uris[0]}/health เป็น background task
โดย redirect_uri มาจาก developer ตอนลงทะเบียน subsystem → เป็นช่อง SSRF
(หลอก Hub ยิงเข้า cloud metadata 169.254.169.254 / RFC1918 / docker internal).

_ping() ต้องบล็อก target ที่ไม่ปลอดภัยใน production **ก่อน** ทำ network I/O
(reuse guard เดียวกับ webhook_dispatcher).

รัน:
    docker compose exec hub-backend pytest tests/test_subsystem_health_ssrf.py -v
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import subsystem_health as sh
from app.services import webhook_dispatcher as wd


@pytest.fixture
def prod(monkeypatch):
    # _is_safe_webhook_url อ่าน wd.settings.app_env
    monkeypatch.setattr(wd.settings, "app_env", "production")


@pytest.fixture
def no_network(monkeypatch):
    """ถ้าโดนบล็อกจริง จะไม่แตะ httpx เลย — ถ้าเผลอยิงให้ระเบิดทันที."""

    def boom(*_a, **_k):
        raise AssertionError("SSRF guard ต้องบล็อกก่อน — ห้ามมี network I/O")

    monkeypatch.setattr(sh.httpx, "AsyncClient", boom)


def _sub(redirect_uri: str):
    return SimpleNamespace(id="sub-1", redirect_uris=[redirect_uri])


@pytest.mark.parametrize(
    "redirect_uri",
    [
        "https://169.254.169.254/callback",  # cloud metadata (link-local)
        "https://127.0.0.1/callback",  # loopback
        "https://10.0.0.5/callback",  # RFC1918 private
        "https://192.168.1.10/callback",  # RFC1918 private
        "http://93.184.216.34/callback",  # public IP แต่ไม่ใช่ https
    ],
)
@pytest.mark.asyncio
async def test_ping_blocks_unsafe_target_in_prod(prod, no_network, redirect_uri):
    result = await sh._ping(_sub(redirect_uri))
    assert result["status"] == "unknown"
    assert "SSRF" in (result.get("error") or "")


@pytest.mark.asyncio
async def test_ping_does_not_block_public_https_in_prod(prod, monkeypatch):
    """public https ต้องผ่าน guard (ไปต่อถึงขั้น fetch) — ไม่ใช่ error SSRF."""

    # ตัด network จริงออก: ให้ AsyncClient ระเบิดแบบ network error (ไม่ใช่ guard block)
    class _Boom:
        async def __aenter__(self):
            raise RuntimeError("network stubbed")

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(sh.httpx, "AsyncClient", lambda *a, **k: _Boom())
    # literal public IP + https → ผ่าน guard (ไม่ต้องพึ่ง DNS ในเทส)
    result = await sh._ping(_sub("https://93.184.216.34/callback"))
    # ผ่าน guard แล้ว → error (ถ้ามี) ต้องไม่ใช่ SSRF block
    assert "SSRF" not in (result.get("error") or "")
