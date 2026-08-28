"""L3 sequence — hub เรียก ml-service แทนการคำนวณเอง (สถาปัตยกรรม: hub ไม่มี numpy/sklearn).

ที่มา (tests/reports/exp_final_gate_2026-08-26.md + การรันจริงใน Docker):
  hub-backend image ไม่มี numpy/sklearn โดยตั้งใจ (ML แยก container ตั้งแต่ Week 5)
  -> L3 numeric core ต้องอยู่ที่ ml-service เหมือน IForest 23 ฟีเจอร์ที่มีอยู่แล้ว

การแบ่งหน้าที่:
  hub        : residual_raw() · apply_channel() · to_contract() · record_residual()  (pure python)
  ml-service : fit / score / model cache — อ่าน history จาก Redis เอง (compose network เดียวกัน)

ทุกอย่าง fail-safe ตาม B21: ml-service ล่ม -> L3 เงียบ ไม่กระทบ decision ของ L1/L2/L4

Run: docker compose exec hub-backend pytest tests/test_l3_sequence_client.py -v
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.security import l3_sequence as L3
from app.services import l3_sequence_client as C

_P = Path(__file__).resolve().parents
# ในคอนเทนเนอร์ tests อยู่ที่ /app/tests (ไม่มี repo root ให้ไต่) -> test นี้ skip เอง
ML_SEQ = (
    _P[3] / "ml-service" / "app" / "sequence.py"
    if len(_P) > 3
    else Path("/nonexistent")
)

OK_PAYLOAD = {
    "fired": True,
    "score": 0.42,
    "raw_score": 0.61,
    "percentile": 0.998,
    "tier": "anomaly",
    "eligibility": "warn",
    "shadow_decision": "would_warn",
    "n_history": 1500,
    "model_version": "iforest-l3-seq-v1",
}


class _FakeResp:
    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self._body


class _FakeClient:
    """AsyncClient ปลอม — post คืน body ที่กำหนด หรือ raise exc."""

    def __init__(self, body=None, exc=None, **kw):
        self._body, self._exc = body, exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, *a, **kw):
        if self._exc:
            raise self._exc
        return _FakeResp({"data": self._body})


def _patch(monkeypatch, body=None, exc=None):
    monkeypatch.setattr(
        C.httpx, "AsyncClient", lambda **kw: _FakeClient(body=body, exc=exc)
    )


# ── 1. fail-safe (B21) ──────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_client_failsafe_when_ml_unreachable(monkeypatch):
    """ml-service ล่ม -> คืนค่าเงียบ + error code ไม่ raise ขึ้น flow หลัก."""
    _patch(monkeypatch, exc=ConnectionError("boom"))
    out = await C.get_sequence_score("u1", [0.0] * L3.DIMS)
    assert out["fired"] is False
    assert out["eligibility"] == "abstain"
    assert out["error"]


@pytest.mark.asyncio
async def test_client_failsafe_on_garbage_payload(monkeypatch):
    """payload ผิดรูป -> เงียบ ไม่ระเบิด."""
    _patch(monkeypatch, body={"fired": "yes-please", "n_history": None})
    out = await C.get_sequence_score("u1", [0.0] * L3.DIMS)
    assert out["fired"] in (True, False)
    assert isinstance(out["n_history"], int)


# ── 2. parse payload ปกติ ───────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_client_parses_payload(monkeypatch):
    _patch(monkeypatch, body=OK_PAYLOAD)
    out = await C.get_sequence_score("u1", [0.1] * L3.DIMS)
    assert out["fired"] is True
    assert out["tier"] == "anomaly"
    assert out["eligibility"] == "warn"
    assert out["n_history"] == 1500
    assert out["error"] is None


@pytest.mark.asyncio
async def test_client_skips_call_when_residual_invalid(monkeypatch):
    """residual มิติไม่ครบ -> ไม่ต้องยิง HTTP เลย."""
    called = {"n": 0}

    class _Counting(_FakeClient):
        async def post(self, *a, **kw):
            called["n"] += 1
            return _FakeResp({"data": OK_PAYLOAD})

    monkeypatch.setattr(C.httpx, "AsyncClient", lambda **kw: _Counting())
    out = await C.get_sequence_score("u1", [0.1, 0.2])
    assert out["fired"] is False
    assert called["n"] == 0


# ── 3. evaluate_login_remote — ทำงานได้โดยไม่ต้องมี numpy ──────────────────
@pytest.mark.asyncio
async def test_evaluate_login_remote_without_numpy(monkeypatch):
    """แม้ hub ไม่มี numpy/sklearn เลย ก็ต้องได้ผล L3 ครบ (นี่คือเหตุผลที่ย้ายไป ml-service)."""
    monkeypatch.setattr(L3, "_numeric", lambda: None)

    async def fake(user_id, residual):
        return {**OK_PAYLOAD, "error": None}

    monkeypatch.setattr(L3, "get_sequence_score", fake, raising=False)

    from app.security.rule_engine import FEAT

    v = [0.0] * 23
    v[FEAT["permission_change_age"]] = 365.0
    profile = {"total": 1500, "subsystem_counts": {"sub-a": 1400}}
    res, resid = await L3.evaluate_login_remote(None, "u1", v, profile, "sub-b")

    assert res.fired is True
    assert res.reason == L3.REASON
    assert res.eligibility == "warn"
    assert res.n_history == 1500
    assert resid is not None and len(resid) == L3.DIMS
    assert all(isinstance(x, float) for x in resid)


@pytest.mark.asyncio
async def test_evaluate_login_remote_no_profile_skips(monkeypatch):
    """ผู้ใช้ใหม่ (ไม่มี profile) -> ไม่ยิง ml-service, คืน abstain."""
    called = {"n": 0}

    async def fake(user_id, residual):
        called["n"] += 1
        return OK_PAYLOAD

    monkeypatch.setattr(L3, "get_sequence_score", fake, raising=False)
    res, resid = await L3.evaluate_login_remote(None, "u1", [0.0] * 23, None, None)
    assert res.fired is False
    assert resid is None
    assert called["n"] == 0


# ── 4. contract ต้องได้ n_history จาก result เมื่อไม่มี model object ────────
def test_contract_uses_result_n_history_when_model_none():
    """remote path ไม่มี L3Model ในมือ -> n_history ต้องมาจาก result (ไม่งั้น replay อ่านเป็น 0)."""
    r = L3.L3Result(
        fired=True, score=0.4, tier="anomaly", eligibility="warn", n_history=1500
    )
    assert L3.to_contract(r, None)["n_history"] == 1500


# ── 5. constants ต้องตรงกันสองฝั่ง (contract แบบเดียวกับ B49 feature order) ─
@pytest.mark.skipif(not ML_SEQ.exists(), reason="ml-service ไม่ได้ mount ใน container นี้")
def test_constants_parity_hub_vs_ml_service():
    """DIMS/WINDOW/threshold/tier ต้องตรงกัน — ต่างกัน = คนละโมเดลโดยไม่รู้ตัว."""
    src = ML_SEQ.read_text(encoding="utf-8")
    expect = {
        "DIMS": L3.DIMS,
        "WINDOW": L3.WINDOW,
        "MAX_HISTORY": L3.MAX_HISTORY,
        "CAL_FPR": L3.CAL_FPR,
        "EXTREME_FPR": L3.EXTREME_FPR,
        "TIER_DIAGNOSTIC": L3.TIER_DIAGNOSTIC,
        "TIER_WARN": L3.TIER_WARN,
        "TIER_CHALLENGE": L3.TIER_CHALLENGE,
    }
    ns: dict = {}
    for line in src.splitlines():
        for k in expect:
            if line.startswith(f"{k} ="):
                ns[k] = eval(line.split("=", 1)[1].split("#")[0].strip())  # noqa: S307
    assert set(ns) == set(expect), f"ml-service ขาดค่าคงที่ {set(expect) - set(ns)}"
    assert ns == expect, f"ค่าคงที่ไม่ตรง: {ns} != {expect}"
    assert f'"{L3.MODEL_VERSION}"' in src, "MODEL_VERSION ไม่ตรงกัน"
