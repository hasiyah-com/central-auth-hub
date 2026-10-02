"""ชั้นที่ 3 เป็นตัวสำรองระดับ warn — ชั้นที่ 1+2 ตัดสิน allow และคะแนน point view ≥ เกณฑ์ → warn

หลักฐาน: tests/reports (branch exp/l3-capped-score) l3_fallback_result_2026-10-01.md —
recall@warn 52.39% → 67.33% (+14.94 [+13.02, +16.78]) · warn FPR 1.22% → 4.14% · challenge ไม่เปลี่ยน
เกณฑ์ 0.4606 เลือกบนชุดปรับค่า · โครงสร้างแยกตามประเภทผู้ใช้ (ค่าเริ่มต้นเท่ากันทุกประเภท)

ข้อตกลงที่บังคับด้วยเทส:
  - ยกได้จาก allow เท่านั้น และยกได้ถึง warn เท่านั้น — ไม่เคยถึง challenge/block
  - เฉพาะ point view · sequence view ยังอยู่แกนเฝ้าระวังอย่างเดียว
  - คะแนนความเสี่ยงไม่เปลี่ยน · มีเหตุผลใน reasons · มีรายละเอียดใน breakdown
  - L3 ล่ม/ไม่มีคะแนน หรือปิดแฟล็ก → การตัดสินเหมือนเดิมทุกประการ

Run: docker compose exec hub-backend pytest tests/test_l3_fallback_warn.py -v
"""

from __future__ import annotations

import pytest

from app.config import settings
from app.security import l3_fallback as FBK
from tests.test_l3_access_monitoring_split import _run as _run_split

ACCESS = ("allow", "warn", "challenge", "block")


# ── หน่วยย่อย ────────────────────────────────────────────────────────────────


def test_default_threshold_matches_experiment():
    assert FBK.DEFAULT_THRESHOLD == pytest.approx(0.4606, abs=1e-4)


@pytest.mark.parametrize("utype", ["student", "teacher", "staff", "admin"])
def test_threshold_per_user_type_defaults_equal(utype):
    assert FBK.threshold_for(utype) == FBK.DEFAULT_THRESHOLD


@pytest.mark.parametrize("utype", [None, "", "unknown"])
def test_unknown_user_type_uses_default(utype):
    assert FBK.threshold_for(utype) == FBK.DEFAULT_THRESHOLD


@pytest.mark.parametrize(
    "decision,score,shadow,expected",
    [
        ("allow", 0.75, False, "warn"),
        ("allow", 0.75, True, "would_warn"),
        ("allow", 0.30, False, "allow"),
        ("allow", FBK.DEFAULT_THRESHOLD, False, "warn"),  # ถึงเกณฑ์พอดี = ยก
        ("warn", 0.99, False, "warn"),
        ("challenge", 0.99, False, "challenge"),
        ("block", 0.99, False, "block"),
        ("would_challenge", 0.99, True, "would_challenge"),
        ("would_warn", 0.99, True, "would_warn"),
    ],
)
def test_apply_matrix(decision, score, shadow, expected):
    out, reason = FBK.apply(decision, score, "student", shadow)
    assert out == expected
    assert (reason is not None) == (out != decision)


def test_apply_never_exceeds_warn():
    for d in ACCESS:
        out, _ = FBK.apply(d, 1.0, "student", False)
        assert ACCESS.index(out) <= max(ACCESS.index(d), ACCESS.index("warn"))
        assert ACCESS.index(out) >= ACCESS.index(d)


@pytest.mark.parametrize("score", [None, float("nan")])
def test_apply_without_score_keeps_decision(score):
    assert FBK.apply("allow", score, "student", False) == ("allow", None)


# ── ผ่าน risk_engine ─────────────────────────────────────────────────────────


async def _run(
    monkeypatch, *, enabled=True, point_score=0.0, fired=False, l3_enabled=True
):
    return await _run_split(
        monkeypatch,
        l3_enabled=l3_enabled,
        fired=fired,
        point_score=point_score,
        fallback=enabled,
    )


@pytest.mark.asyncio
async def test_allow_with_high_point_score_becomes_warn(monkeypatch):
    base = await _run(monkeypatch, point_score=0.0)
    out = await _run(monkeypatch, point_score=0.75)
    assert base["decision"] == "allow"
    assert out["decision"] == "warn"
    assert out["score"] == base["score"], "ตัวสำรองต้องไม่เปลี่ยนคะแนน"
    assert out["reasons"][-1].startswith(FBK.REASON)
    assert out["breakdown"]["l3_fallback"]["applied"] is True
    assert out["breakdown"]["l3_fallback"]["threshold"] == FBK.DEFAULT_THRESHOLD


@pytest.mark.asyncio
async def test_below_threshold_unchanged(monkeypatch):
    out = await _run(monkeypatch, point_score=0.30)
    assert out["decision"] == "allow"
    assert out["breakdown"]["l3_fallback"]["applied"] is False


@pytest.mark.asyncio
async def test_disabled_flag_keeps_monitoring_only(monkeypatch):
    out = await _run(monkeypatch, enabled=False, point_score=0.99)
    assert out["decision"] == "allow"
    assert not any(r.startswith(FBK.REASON) for r in out["reasons"])
    assert "l3_fallback" not in out["breakdown"]


@pytest.mark.asyncio
async def test_sequence_view_does_not_trigger_fallback(monkeypatch):
    out = await _run(monkeypatch, point_score=0.0, fired=True)
    assert out["decision"] == "allow"


@pytest.mark.asyncio
async def test_l3_error_keeps_decision(monkeypatch):
    from app.services import l3_sequence_client as CLI

    async def boom(*a, **kw):
        raise RuntimeError("ml down")

    monkeypatch.setattr(settings, "l3_fallback_warn_enabled", True, raising=False)
    from app.security import l3_sequence as L3
    from app.security import risk_engine

    monkeypatch.setattr(settings, "l3_sequence_enabled", True, raising=False)
    monkeypatch.setattr(risk_engine, "get_user_profile", lambda db, uid: None)
    monkeypatch.setattr(CLI, "evaluate_l3", boom)
    monkeypatch.setattr(L3, "residual_raw", lambda *a, **kw: [0.0] * L3.DIMS)
    monkeypatch.setattr(L3, "record_residual", lambda *a, **kw: None)
    from app.security.rule_engine import FEAT

    v = [0.0] * 23
    v[FEAT["permission_change_age"]] = 365.0
    out = await risk_engine.evaluate_login_risk(v, "u-fb", None, None, db=None)
    assert out["decision"] == "allow"
