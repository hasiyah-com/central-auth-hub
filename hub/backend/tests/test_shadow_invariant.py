"""Shadow invariant — นำ L3 เข้า L4 ได้ แต่ห้ามขยับการตัดสินจริงแม้แต่ครั้งเดียว.

เขียนก่อน implementation (RED) ตามแผน "นำ L3 เข้าช่วยคำนวณ Hybrid Risk ในเส้นทาง
Shadow จริง" ขั้นที่ 11

สิ่งที่แผนต้องการและยังไม่มีในโค้ด ณ ตอนเขียนไฟล์นี้:

    * โหมด `shadow_hybrid` (นับ L3 เข้า L4 แต่ไม่แตะ actual decision)
    * โหมด `monitor_only` (เรียก L3 เก็บ l3_investigate อย่างเดียว)
    * ผลสองชุดต่อหนึ่ง login — `baseline_shadow` (L1+L2) และ `hybrid_shadow` (L1+L2+L3)

โครงสร้างปัจจุบันเป็นสวิตช์สองทาง: `shadow` ปิด L3 ไม่ให้เข้า L4 เลย ส่วน
`hybrid_stepup` ให้ L3 มีผลต่อผู้ใช้จริง จึงยังไม่มีเส้นทางที่ "คำนวณ hybrid แล้ว
เก็บไว้เฉย ๆ" ซึ่งเป็นสิ่งเดียวที่จะตอบได้ว่า Isolation Forest เพิ่มประโยชน์เท่าไร

ทำไมต้องเทียบ "ทุกเส้นทาง login" — บทเรียน B66/B70 ตรงกันว่าเทสที่วัดผ่าน
เส้นทางที่ production ไม่ได้เรียก ให้ความมั่นใจปลอม จึงเรียกด้วย **ชุดพารามิเตอร์
เดียวกับที่ router แต่ละตัวส่งจริง** และมีเทสอ่านซอร์สของ router ยืนยันว่า
การตัดสินจริงยังมาจาก `risk["decision"]` เท่านั้น
"""

from __future__ import annotations

import copy
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.asyncio

ROUTERS = Path(__file__).resolve().parents[1] / "app" / "routers"

# ชุดพารามิเตอร์ที่ router แต่ละตัวส่งเข้า evaluate_login_risk จริง
# (ตรวจกับซอร์สแล้ว — ดู test_call_site_list_matches_source)
CALL_SITES = {
    "auth.google_callback": dict(subsystem_id=None, shadow_mode=True),
    "auth.line_callback": dict(subsystem_id=None, shadow_mode=True),
    "auth._refresh_risk_gate": dict(subsystem_id=None, shadow_mode=True),
    "oauth._finalize_subsystem_login": dict(
        subsystem_id="11111111-1111-1111-1111-111111111111", shadow_mode=True
    ),
    "passkey._build_login_session": dict(subsystem_id=None, shadow_mode=True),
}

MODE_OFF = "off"
MODE_MONITOR = "monitor_only"
MODE_SHADOW_HYBRID = "shadow_hybrid"


async def _engine(
    monkeypatch,
    mode: str,
    *,
    point_raw: float = 0.0,
    point_available: bool = True,
    seq_raw: float = 0.0,
    seq_eligibility: str = "abstain",
    subsystem_id=None,
    shadow_mode: bool = True,
):
    """เรียก risk_engine ตัวจริง คุมเฉพาะผลที่ L3 ป้อนกลับมา."""
    from app.config import settings
    from app.security import l3_sequence as L3
    from app.security import risk_engine, rule_engine
    from app.services import l3_sequence_client as CLI

    monkeypatch.setattr(settings, "l3_mode", mode, raising=False)
    monkeypatch.setattr(settings, "l3_sequence_enabled", True, raising=False)
    monkeypatch.setattr(risk_engine, "get_user_profile", lambda db, uid: None)
    monkeypatch.setattr(L3, "residual_raw", lambda *a, **kw: [0.0] * L3.DIMS)
    monkeypatch.setattr(L3, "record_residual", lambda *a, **kw: None)
    # เส้นทาง oauth ส่ง subsystem_id มาด้วย ซึ่งจะแตะ DB — เทสนี้ไม่มี DB
    monkeypatch.setattr(
        rule_engine, "_check_cross_subsystem_risk", lambda *a, **kw: None
    )

    async def fake_l3(
        user_id, features, residual, access_decision="allow", explain=False
    ):
        out = copy.deepcopy(CLI.UNIFIED_QUIET)
        out["point"] = {
            "available": point_available,
            "anomaly_score": point_raw,
            "is_anomaly": point_raw >= 0.5,
            "explanation": [],
            "error": None,
            "explainer": "ready",
        }
        out["sequence"] = {
            **out["sequence"],
            "raw_score": seq_raw,
            "score": seq_raw,
            "eligibility": seq_eligibility,
            "n_history": 1200 if seq_eligibility != "abstain" else 12,
        }
        if point_raw >= 0.9 or seq_raw >= 0.9:
            out["monitoring_decision"] = "l3_investigate"
        return out

    monkeypatch.setattr(CLI, "evaluate_l3", fake_l3)

    from app.security.rule_engine import FEAT

    v = [0.0] * 23
    v[FEAT["permission_change_age"]] = 365.0
    return await risk_engine.evaluate_login_risk(
        v,
        "u-shadow-invariant",
        None,
        None,
        db=None,
        shadow_mode=shadow_mode,
        subsystem_id=subsystem_id,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 1. สัญญาของโหมด
# ══════════════════════════════════════════════════════════════════════════════


async def test_shadow_hybrid_is_a_known_mode(monkeypatch):
    """`shadow_hybrid` ต้องเป็นโหมดที่ระบบรู้จัก ไม่ใช่ค่าที่ตกไปเข้า else เงียบ ๆ."""
    from app.security import risk_engine

    assert MODE_SHADOW_HYBRID in risk_engine.L3_MODES
    out = await _engine(monkeypatch, MODE_SHADOW_HYBRID, point_raw=0.9)
    assert out["l3_mode"] == MODE_SHADOW_HYBRID


async def test_monitor_only_is_a_known_mode(monkeypatch):
    from app.security import risk_engine

    assert MODE_MONITOR in risk_engine.L3_MODES
    out = await _engine(monkeypatch, MODE_MONITOR, point_raw=0.99)
    assert out["l3_mode"] == MODE_MONITOR


async def test_monitor_only_records_l3_but_keeps_hybrid_equal_to_baseline(monkeypatch):
    """monitor_only: เห็น l3_investigate ได้ แต่ห้ามเอา L3 ไปรวมคะแนน."""
    out = await _engine(monkeypatch, MODE_MONITOR, point_raw=0.99)
    assert out["monitoring_decision"] == "l3_investigate"
    assert out["hybrid_shadow"]["final_risk"] == out["baseline_shadow"]["final_risk"]


async def test_unknown_mode_never_lets_l3_into_l4(monkeypatch):
    """โหมดที่ไม่รู้จักต้องไม่เปิดสิทธิ์เพิ่ม — fail closed."""
    off = await _engine(monkeypatch, MODE_OFF, point_raw=0.0)
    weird = await _engine(monkeypatch, "hybrid_block_someday", point_raw=1.0)
    assert weird["decision"] == off["decision"]
    assert weird["score"] == off["score"]


# ══════════════════════════════════════════════════════════════════════════════
# 2. Invariant หลัก — actual decision ต้องไม่ขยับ ทุกเส้นทาง login
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("call_site", sorted(CALL_SITES))
async def test_actual_decision_unchanged_by_l3(monkeypatch, call_site):
    """`actual_decision` ก่อนเพิ่ม L3 == หลังเพิ่ม L3 — ทุกเส้นทางที่เรียก risk engine."""
    kw = CALL_SITES[call_site]
    without = await _engine(monkeypatch, MODE_OFF, point_raw=0.0, **kw)
    with_l3 = await _engine(
        monkeypatch,
        MODE_SHADOW_HYBRID,
        point_raw=0.99,
        seq_raw=0.99,
        seq_eligibility="challenge",
        **kw,
    )
    assert with_l3["decision"] == without["decision"], call_site
    assert with_l3["score"] == without["score"], call_site


@pytest.mark.parametrize("call_site", sorted(CALL_SITES))
async def test_actual_decision_equals_baseline_shadow(monkeypatch, call_site):
    """ผลที่ผู้ใช้ได้รับต้องเป็นผลของ baseline เสมอ ไม่ใช่ของ hybrid."""
    out = await _engine(
        monkeypatch,
        MODE_SHADOW_HYBRID,
        point_raw=0.99,
        seq_raw=0.99,
        seq_eligibility="challenge",
        **CALL_SITES[call_site],
    )
    assert out["score"] == out["baseline_shadow"]["final_risk"], call_site


async def test_l3_alone_never_produces_would_block_in_hybrid(monkeypatch):
    """L3 เดี่ยวห้ามสร้าง would_block แม้ในผลจำลอง (ขั้นที่ 8 ของแผน)."""
    out = await _engine(
        monkeypatch,
        MODE_SHADOW_HYBRID,
        point_raw=1.0,
        seq_raw=1.0,
        seq_eligibility="challenge",
    )
    assert out["hybrid_shadow"]["decision"] != "would_block"


# ══════════════════════════════════════════════════════════════════════════════
# 3. ผลสองชุดต่อหนึ่ง login
# ══════════════════════════════════════════════════════════════════════════════


async def test_result_carries_both_shadow_results(monkeypatch):
    out = await _engine(monkeypatch, MODE_SHADOW_HYBRID, point_raw=0.5)
    for key in ("baseline_shadow", "hybrid_shadow"):
        assert key in out, key
        assert set(out[key]) >= {"final_risk", "decision"}, key


async def test_both_shadow_results_use_shadow_vocabulary(monkeypatch):
    """ผลจำลองต้องใช้คำ would_* เสมอ — กันสับสนกับการตัดสินจริง."""
    out = await _engine(
        monkeypatch,
        MODE_SHADOW_HYBRID,
        point_raw=0.99,
        seq_raw=0.99,
        seq_eligibility="challenge",
    )
    for key in ("baseline_shadow", "hybrid_shadow"):
        assert out[key]["decision"].startswith("would_"), (key, out[key])


async def test_hybrid_can_differ_from_baseline(monkeypatch):
    """ถ้า hybrid เท่ากับ baseline เสมอ แปลว่า L3 ไม่ได้ถูกคำนวณจริง."""
    out = await _engine(
        monkeypatch,
        MODE_SHADOW_HYBRID,
        point_raw=0.99,
        seq_raw=0.99,
        seq_eligibility="challenge",
    )
    assert out["hybrid_shadow"]["final_risk"] > out["baseline_shadow"]["final_risk"]
    assert out["l3"]["changed_shadow_decision"] is True


async def test_abstain_makes_hybrid_equal_baseline(monkeypatch):
    """ประวัติไม่พอ = ยังประเมินไม่ได้ ห้ามตีความว่า L3 ยืนยันว่าปลอดภัย.

    abstain จริงคือ **ไม่มีมุมมองไหนให้หลักฐานได้เลย** ไม่ใช่ให้คะแนน 0.0
    จึงปิดทั้ง point (available=False) และ sequence (ประวัติไม่ถึงเกณฑ์)
    """
    out = await _engine(
        monkeypatch,
        MODE_SHADOW_HYBRID,
        point_available=False,
        seq_eligibility="abstain",
    )
    assert out["l3"]["combined_evidence"] is None, "ต้องไม่มีหลักฐานเลย ไม่ใช่ 0.0"
    assert out["hybrid_shadow"]["final_risk"] == out["baseline_shadow"]["final_risk"]
    assert out["hybrid_shadow"]["decision"] == out["baseline_shadow"]["decision"]
    assert out["l3"]["changed_shadow_decision"] is False


async def test_zero_evidence_is_not_the_same_as_abstain(monkeypatch):
    """คะแนน 0.0 (ประเมินแล้วเงียบ) ต้องแยกจาก abstain (ยังประเมินไม่ได้) ให้ขาด."""
    quiet = await _engine(monkeypatch, MODE_SHADOW_HYBRID, point_raw=0.0)
    silent = await _engine(monkeypatch, MODE_SHADOW_HYBRID, point_available=False)
    assert quiet["l3"]["point_evidence"] == 0.0
    assert silent["l3"]["point_evidence"] is None


async def test_adding_l3_never_lowers_hybrid_below_baseline(monkeypatch):
    for raw in (0.0, 0.2, 0.5, 0.8, 1.0):
        out = await _engine(
            monkeypatch,
            MODE_SHADOW_HYBRID,
            point_raw=raw,
            seq_raw=raw,
            seq_eligibility="challenge",
        )
        assert (
            out["hybrid_shadow"]["final_risk"] >= out["baseline_shadow"]["final_risk"]
        )


# ══════════════════════════════════════════════════════════════════════════════
# 4. ฟิลด์ที่งานวิจัยต้องใช้ (ขั้นที่ 5 และ 10 ของแผน)
# ══════════════════════════════════════════════════════════════════════════════


async def test_two_views_recorded_separately_and_combined_with_max(monkeypatch):
    out = await _engine(
        monkeypatch,
        MODE_SHADOW_HYBRID,
        point_raw=0.40,
        seq_raw=0.90,
        seq_eligibility="challenge",
    )
    l3 = out["l3"]
    assert l3["combined_method"] == "max"
    assert l3["combined_evidence"] == max(l3["point_evidence"], l3["sequence_evidence"])


async def test_sequence_not_counted_when_history_insufficient(monkeypatch):
    """sequence ที่ abstain ต้องไม่ถูกนับเป็นคะแนน 0 แล้วดึงค่า max ลง."""
    out = await _engine(
        monkeypatch,
        MODE_SHADOW_HYBRID,
        point_raw=0.60,
        seq_raw=0.0,
        seq_eligibility="abstain",
    )
    l3 = out["l3"]
    assert l3["sequence_evidence"] is None
    assert l3["combined_evidence"] == l3["point_evidence"]


async def test_research_fields_present(monkeypatch):
    """ฟิลด์ตามขั้นที่ 10 ที่ risk engine เป็นผู้ผลิต."""
    out = await _engine(
        monkeypatch,
        MODE_SHADOW_HYBRID,
        point_raw=0.7,
        seq_raw=0.7,
        seq_eligibility="warn",
    )
    assert set(out["baseline_shadow"]) >= {"final_risk", "decision"}
    assert set(out["hybrid_shadow"]) >= {"final_risk", "decision"}
    assert set(out["l3"]) >= {
        "point_evidence",
        "sequence_evidence",
        "combined_evidence",
        "combined_method",
        "eligibility",
        "n_history",
        "changed_shadow_decision",
        "monitoring_decision",
    }


# ══════════════════════════════════════════════════════════════════════════════
# 5. โครงสร้าง router — การตัดสินจริงต้องไม่เคยอ่านผลจำลอง
# ══════════════════════════════════════════════════════════════════════════════

_CALL_SITE_FILES = ("auth.py", "oauth.py", "passkey.py")
_FORBIDDEN = re.compile(
    r"=\s*risk(?:\.get\(|\[)\s*[\"'](hybrid_shadow|baseline_shadow)[\"']"
)


@pytest.mark.parametrize("filename", _CALL_SITE_FILES)
async def test_router_never_assigns_shadow_result_to_a_variable(filename):
    """ผลจำลองห้ามถูกดึงออกมาใช้ใน router — ป้องกันการ "ต่อสาย" โดยไม่ผ่าน validation (B70)."""
    src = (ROUTERS / filename).read_text(encoding="utf-8")
    hits = [
        f"{filename}:{i}"
        for i, line in enumerate(src.splitlines(), 1)
        if _FORBIDDEN.search(line)
    ]
    assert not hits, f"router อ่านผลจำลองไปใช้: {hits}"


async def test_call_site_list_matches_source():
    """รายชื่อเส้นทางในไฟล์นี้ต้องตรงกับจำนวนจุดที่เรียก evaluate_login_risk จริง.

    ถ้ามีคนเพิ่มเส้นทาง login ใหม่แล้วลืมเพิ่มที่นี่ เทสนี้จะล้ม — กันไม่ให้
    invariant ครอบคลุมไม่ครบโดยไม่มีใครรู้
    """
    found = 0
    for filename in _CALL_SITE_FILES:
        src = (ROUTERS / filename).read_text(encoding="utf-8")
        found += len(re.findall(r"await evaluate_login_risk\(", src))
    assert found == len(
        CALL_SITES
    ), f"พบจุดเรียก {found} จุด แต่ CALL_SITES มี {len(CALL_SITES)} รายการ"


# ══════════════════════════════════════════════════════════════════════════════
# 6. บันทึกลง login_sessions (ขั้นที่ 10)
# ══════════════════════════════════════════════════════════════════════════════


async def test_shadow_columns_rejects_unknown_source():
    from app.services.shadow_record import shadow_columns

    with pytest.raises(ValueError):
        shadow_columns({}, source="somewhere_else")


async def test_shadow_columns_maps_engine_output(monkeypatch):
    from app.services.shadow_record import SOURCE_GOOGLE, shadow_columns

    risk = await _engine(
        monkeypatch,
        MODE_SHADOW_HYBRID,
        point_raw=0.99,
        seq_raw=0.99,
        seq_eligibility="challenge",
    )
    cols = shadow_columns(risk, source=SOURCE_GOOGLE)
    assert cols["actual_decision_source"] == SOURCE_GOOGLE
    assert cols["baseline_shadow_score"] == risk["baseline_shadow"]["final_risk"]
    assert cols["hybrid_shadow_decision"] == risk["hybrid_shadow"]["decision"]
    assert cols["l3_changed_shadow_decision"] is True
    assert cols["l3_n_history"] == 1200
    assert cols["latency_total_ms"] is not None


async def test_calibrated_flag_is_none_when_unknown():
    """ไม่มีข้อมูล = None ห้ามเดาว่า calibrate แล้ว (แยก "ไม่รู้" จาก "จริง/เท็จ")."""
    from app.services.shadow_record import SOURCE_PASSKEY, shadow_columns

    assert shadow_columns({}, source=SOURCE_PASSKEY)["calibrated"] is None
    assert (
        shadow_columns(
            {"breakdown": {"uncalibrated_layers": ["rule"]}}, source=SOURCE_PASSKEY
        )["calibrated"]
        is False
    )
    assert (
        shadow_columns(
            {"breakdown": {"uncalibrated_layers": []}}, source=SOURCE_PASSKEY
        )["calibrated"]
        is True
    )


async def test_every_login_session_site_records_shadow_columns():
    """ทุกจุดที่สร้าง/อัปเดต LoginSession ต้องบันทึกผลจำลองด้วย.

    ถ้ามีเส้นทางไหนลืม ข้อมูลวิจัยจะขาดเป็นช่วง ๆ โดยไม่มีอะไรฟ้อง — และเราจะ
    สรุปผลจากประชากรที่ปนกันโดยไม่รู้ตัว (อาการเดียวกับ B66)
    """
    sites = 0
    for filename in _CALL_SITE_FILES:
        src = (ROUTERS / filename).read_text(encoding="utf-8")
        sites += len(re.findall(r"shadow_columns\(risk, source=", src))
    assert sites == len(CALL_SITES), f"บันทึกแค่ {sites} จุด จาก {len(CALL_SITES)}"


async def test_columns_match_the_database(db):
    """ชื่อคอลัมน์ที่ shadow_columns คืนต้องมีจริงในตาราง — กัน typo ที่จะพังตอน login."""
    from sqlalchemy import inspect

    from app.models import LoginSession
    from app.services.shadow_record import SOURCE_OAUTH, shadow_columns

    actual = {c.name for c in inspect(LoginSession).columns}
    produced = set(shadow_columns({}, source=SOURCE_OAUTH))
    assert produced <= actual, f"คอลัมน์ที่ไม่มีในตาราง: {sorted(produced - actual)}"

    in_db = {
        row[0]
        for row in db.execute(
            __import__("sqlalchemy").text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'login_sessions'"
            )
        )
    }
    assert produced <= in_db, f"คอลัมน์ที่ยังไม่ได้ migrate: {sorted(produced - in_db)}"


# ══════════════════════════════════════════════════════════════════════════════
# 7. เส้นทางจริงเขียนคอลัมน์จริง (ไม่ใช่แค่ฟังก์ชันแปลงค่าถูก)
# ══════════════════════════════════════════════════════════════════════════════


def _fake_request(user_agent: str = "pytest-shadow-invariant"):
    """Request จริงของ starlette — get_client_ip/headers ต้องอ่านได้เหมือน production."""
    from starlette.requests import Request

    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "root_path": "",
            "scheme": "http",
            "query_string": b"",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 12345),
            "headers": [(b"user-agent", user_agent.encode())],
        }
    )


async def test_real_login_path_writes_shadow_columns(monkeypatch, db, student_user):
    """เรียก `passkey._build_login_session` ตัวจริง แล้วตรวจแถวที่ได้.

    ไม่สร้างสำเนาของตรรกะขึ้นมาทดสอบ — เรียกฟังก์ชันที่ production เรียกจริง
    เพราะบทเรียน B66/B70 คือเทสที่วัดผ่านเส้นทางที่ production ไม่ได้ใช้
    ให้ความมั่นใจปลอม · ไม่ commit (rollback ท้ายเทส) เพื่อไม่ทิ้ง state ข้ามรอบ
    """
    from types import SimpleNamespace

    from app.config import settings
    from app.models import LoginSession
    from app.routers import passkey

    monkeypatch.setattr(settings, "l3_mode", MODE_SHADOW_HYBRID, raising=False)

    result = SimpleNamespace(user=student_user, counter_regression=False)
    session = await passkey._build_login_session(
        result, _fake_request(), jti="jti-shadow-invariant", db=db, method="passkey"
    )

    try:
        db.add(session)
        db.flush()
        row = db.query(LoginSession).filter(LoginSession.id == session.id).one()

        assert row.actual_decision_source == "passkey_login"
        # ผลจำลองต้องถูกบันทึกทั้งคู่ และใช้คำ would_ ทั้งคู่
        assert row.baseline_shadow_score is not None
        assert row.hybrid_shadow_score is not None
        assert row.baseline_shadow_decision.startswith("would_")
        assert row.hybrid_shadow_decision.startswith("would_")
        # การตัดสินจริงต้องยังเท่ากับ baseline — L3 ไม่ได้ขยับอะไรของผู้ใช้
        assert float(row.risk_score) == float(row.baseline_shadow_score)
        assert row.l3_changed_shadow_decision is not None
        assert row.latency_total_ms is not None and row.latency_total_ms >= 0
        # ที่มาของคอนฟิกตอนนี้ยังว่าง เพราะยังไม่มี calibration artifact — ต้องเป็น
        # None ไม่ใช่ค่าเดา (ดู §11 ของรายงาน test_isolation)
        assert row.calibration_version == settings.calibration_version
        assert row.shadow_epoch_id == settings.shadow_epoch_id
    finally:
        db.rollback()
