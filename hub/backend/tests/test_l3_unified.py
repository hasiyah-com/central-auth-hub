"""L3 รวมสองมุมมอง — SHAP ของ sequence + duplicate ratio + unique_to_l3 (ของจริง).

ที่มา (รีวิว 31 ส.ค. 2026): ก่อนหน้านี้ L3 ทำได้ "แยกกันคนละครึ่ง" —

    point view (23 ฟีเจอร์)   มี SHAP ครบ  แต่คะแนน **บวกเข้า access decision**
    sequence view (18 มิติ)   ไม่แตะ access แต่ **ไม่มี SHAP** และไม่มี duplicate ratio

ไฟล์นี้ตรวจส่วนที่เพิ่มเข้ามาให้ครบทั้งสองมุมมอง โดยยิงผ่าน ml-service จริง
(ไม่ mock) — skip เองถ้า Redis/ml-service ไม่พร้อม

Run: docker compose exec hub-backend pytest tests/test_l3_unified.py -v -s
"""

from __future__ import annotations

import asyncio
import random

import pytest

from app.security import l3_sequence as L3
from app.services.l3_sequence_client import evaluate_l3

USER = "pytest-l3-unified"
KEY = L3._REDIS_KEY.format(user_id=USER)

# 18 มิติ = 6 residual dims x [mean, slope, ptp] — ชื่อต้องตรงกับ ml-service
DIM_NAMES = [
    "gap_log",
    "scope",
    "passkey_age_log",
    "weekday_usage",
    "hours_from_typical",
    "sub_rarity",
]
STAT_NAMES = ["mean", "slope", "ptp"]
EXPECTED_SEQ_FEATURES = {f"{d}_{s}_w{L3.WINDOW}" for s in STAT_NAMES for d in DIM_NAMES}


def _redis():
    try:
        from app.redis_client import redis_client

        redis_client.ping()
        return redis_client
    except Exception:  # noqa: BLE001
        return None


def _features(n: int = 23) -> list[float]:
    from app.security.rule_engine import FEAT

    v = [0.0] * n
    v[FEAT["permission_change_age"]] = 365.0
    return v


async def _ok(resid, access="allow", tries: int = 4) -> dict:
    """เรียกจนสำเร็จ — call แรกตอน cache เย็นอาจ timeout ตามที่ออกแบบไว้ (B63)."""
    for i in range(tries):
        out = await evaluate_l3(USER, _features(), resid, access)
        if out["error"] is None:
            return out
        assert out["error"] == "l3_timeout", f"ml-service ไม่พร้อม: {out['error']}"
        await asyncio.sleep(0.5 * (i + 1))
    raise AssertionError(f"ml-service ยัง warm ไม่เสร็จหลัง {tries} ครั้ง")


@pytest.fixture
def seeded():
    """residual ปกติ 1500 แถว -> ผ่าน tier warn (L3 sequence ขึ้นธงได้จริง)."""
    r = _redis()
    if r is None:
        pytest.skip("Redis ไม่พร้อม")
    r.delete(KEY)
    rng = random.Random(42)
    for _ in range(1500):
        L3.record_residual(r, USER, [rng.gauss(0, 1) for _ in range(L3.DIMS)])
    yield r
    r.delete(KEY)


def _reset_dup(r):
    r.delete("l3dup:flagged", "l3dup:dup")


# ══════════════════ 1. SHAP ของ sequence view (สิ่งที่ขาดไป) ══════════════════


@pytest.mark.asyncio
async def test_sequence_view_returns_shap(seeded):
    """residual สุดโต่ง -> sequence ยิง **และ** อธิบายได้ว่าฟีเจอร์ไหนดัน."""
    out = await _ok([9.0] * L3.DIMS)
    seq = out["sequence"]
    assert seq["fired"] is True, f"ควรยิงที่ residual สุดโต่ง (ได้ {seq})"
    assert "sequence_residual" in out["detected_by"]

    factors = [f for f in out["top_factors"] if f["owner"] == "l3_sequence"]
    assert factors, "sequence ยิงแล้วต้องมี SHAP อธิบาย — เดิมไม่มีเลย"
    for f in factors:
        assert f["feature"] in EXPECTED_SEQ_FEATURES, f"ชื่อฟีเจอร์แปลก: {f['feature']}"
        assert f["direction"] in ("anomaly", "normal")
        assert 0.0 <= f["contribution"] <= 1.0


@pytest.mark.asyncio
async def test_sequence_shap_names_cover_all_three_stats(seeded):
    """ชื่อฟีเจอร์ต้องอยู่ในรายการ 18 มิติ และครอบคลุมสถิติที่นิยามไว้.

    ลำดับ 18 มิติใน `_windows()` คือ [mean x6, slope x6, ptp x6] ถ้า map ชื่อผิด
    ลำดับ SHAP จะชี้ฟีเจอร์ผิดตัวโดยไม่มีใครรู้ (บทเรียนเดียวกับ B49)
    """
    seen: set[str] = set()
    for mag in (6.0, 9.0, 12.0):
        out = await _ok([mag] * L3.DIMS)
        seen |= {
            f["feature"] for f in out["top_factors"] if f["owner"] == "l3_sequence"
        }
    assert seen, "ไม่ได้ SHAP ของ sequence เลย"
    assert seen <= EXPECTED_SEQ_FEATURES, f"ชื่อนอกรายการ: {seen - EXPECTED_SEQ_FEATURES}"
    stats = {f.rsplit("_", 2)[1] for f in seen}
    assert stats <= set(STAT_NAMES)


@pytest.mark.asyncio
async def test_abstain_user_has_no_sequence_factors():
    """ประวัติไม่พอ -> abstain และต้องไม่มีคำอธิบายหลอกๆ ออกมา."""
    r = _redis()
    if r is None:
        pytest.skip("Redis ไม่พร้อม")
    r.delete(KEY)
    out = await evaluate_l3(USER, _features(), [0.1] * L3.DIMS, "allow")
    assert out["sequence"]["eligibility"] == "abstain"
    assert "sequence_residual" not in out["detected_by"]
    assert not [f for f in out["top_factors"] if f["owner"] == "l3_sequence"]


# ══════════════════ 2. duplicate ratio + unique_to_l3 (runtime) ══════════════════


@pytest.mark.asyncio
async def test_unique_to_l3_true_when_access_allows(seeded):
    """L3 ยิง แต่ L1/L2 ปล่อยผ่าน -> นี่คือคุณค่าที่แท้จริงของ L3."""
    _reset_dup(seeded)
    out = await _ok([9.0] * L3.DIMS, access="allow")
    assert out["is_anomaly"] is True
    assert out["unique_to_l3"] is True


@pytest.mark.asyncio
async def test_unique_to_l3_false_when_access_already_caught(seeded):
    """L1/L2 จับได้อยู่แล้ว -> L3 ยิงซ้ำ ไม่ใช่ของใหม่."""
    _reset_dup(seeded)
    out = await _ok([9.0] * L3.DIMS, access="challenge")
    assert out["is_anomaly"] is True
    assert out["unique_to_l3"] is False


@pytest.mark.asyncio
async def test_duplicate_ratio_counts_only_flagged_events(seeded):
    """ratio ต้องมีตัวหารที่อ่านออก และนับเฉพาะเหตุการณ์ที่ L3 ยิงจริง."""
    _reset_dup(seeded)
    # 2 ครั้งที่ L1/L2 จับได้อยู่แล้ว + 2 ครั้งที่ L3 เห็นคนเดียว
    for access in ("challenge", "block", "allow", "allow"):
        out = await _ok([9.0] * L3.DIMS, access=access)
        assert out["is_anomaly"] is True

    assert out["duplicate_window"] == 4, "ตัวหารต้องเท่ากับจำนวนครั้งที่ยิง"
    assert out["duplicate_ratio"] == pytest.approx(0.5), "2 ใน 4 ครั้งเป็นของซ้ำ"


@pytest.mark.asyncio
async def test_quiet_event_does_not_move_duplicate_counter(seeded):
    """ไม่ยิง -> ตัวนับต้องไม่ขยับ (ไม่งั้น ratio จะเจือจางด้วย login ปกติ)."""
    _reset_dup(seeded)
    await _ok([9.0] * L3.DIMS, access="allow")  # ยิง 1 ครั้ง
    before = (await _ok([9.0] * L3.DIMS, access="allow"))["duplicate_window"]

    out = await _ok([0.05] * L3.DIMS, access="allow")  # ปกติ ไม่ยิง
    assert out["is_anomaly"] is False
    assert out["duplicate_window"] == before, "เหตุการณ์ที่ไม่ยิงไม่ควรเข้าตัวนับ"


# ══════════════════ 3. contract รวม — ต้องไม่มีคำในแกน access ══════════════════


@pytest.mark.asyncio
async def test_unified_contract_shape(seeded):
    """ฟิลด์ที่ตกลงไว้ต้องมีครบ และค่าต้องอยู่ในโลกของ monitoring เท่านั้น."""
    out = await _ok([9.0] * L3.DIMS)
    for key in (
        "monitoring_decision",
        "is_anomaly",
        "unique_to_l3",
        "detected_by",
        "duplicate_ratio",
        "duplicate_window",
        "top_factors",
    ):
        assert key in out, f"ขาดฟิลด์ {key}"
    assert out["monitoring_decision"] in ("normal", "l3_investigate")
    assert set(out["detected_by"]) <= {"point_iforest", "sequence_residual"}
    # ห้ามมีฟิลด์ที่อ่านแล้วเข้าใจว่าเป็น access decision
    assert "decision" not in out
    assert "access_decision" not in out


@pytest.mark.asyncio
async def test_every_factor_declares_its_owner(seeded):
    """ทุก factor ต้องบอกว่ามาจากมุมมองไหน — ไม่งั้นอ่าน top_factors ไม่ออก."""
    out = await _ok([9.0] * L3.DIMS)
    assert out["top_factors"], "ยิงแล้วต้องมีคำอธิบาย"
    for f in out["top_factors"]:
        assert f["owner"] in ("l3_point", "l3_sequence"), f"owner ไม่ถูกต้อง: {f}"
        assert f["feature"]


@pytest.mark.asyncio
async def test_factors_sorted_by_contribution(seeded):
    out = await _ok([9.0] * L3.DIMS)
    contribs = [f["contribution"] for f in out["top_factors"]]
    assert contribs == sorted(contribs, reverse=True)


# ══════════════════ 4. fail-safe (B21) ของเส้นทางรวม ══════════════════


@pytest.mark.asyncio
async def test_bad_residual_falls_back_to_point_view_only():
    """residual ผิดมิติ -> ไม่ใช่ error ทั้งก้อน · point view ต้องยังทำงาน."""
    out = await evaluate_l3(USER, _features(), [1.0, 2.0], "allow")
    assert out["error"] is None, "residual ผิดรูปไม่ควรทำให้ L3 ทั้งชั้นล่ม"
    assert out["sequence"]["eligibility"] == "abstain"
    assert out["point"]["available"] is True, "point view ควรทำงานต่อได้"


@pytest.mark.asyncio
async def test_ml_service_unreachable_is_quiet(monkeypatch):
    """ml-service ล่ม -> คืนค่าเงียบ + error code ไม่ raise ขึ้น login flow."""
    from app.config import settings

    monkeypatch.setattr(settings, "ml_service_url", "http://127.0.0.1:1", raising=False)
    out = await evaluate_l3(USER, _features(), [0.1] * L3.DIMS, "allow")
    assert out["error"] is not None
    assert out["monitoring_decision"] == "normal"
    assert out["is_anomaly"] is False
    assert out["top_factors"] == []


# ══════════════ 5. parity ของลำดับ 18 มิติ (ความเสี่ยงแบบ B49) ══════════════


@pytest.mark.asyncio
async def test_shap_names_point_at_the_right_dimension(seeded):
    """ทำให้ **มิติเดียว** ผิดปกติ แล้วตรวจว่า SHAP ชี้ชื่อมิตินั้นจริง — ครบทั้ง 6 มิติ.

    ลำดับ 18 มิติใน `_windows()` คือ [mean x6, slope x6, ptp x6] และ
    `SEQ_FEATURE_NAMES` ต้องเรียงตรงกันเป๊ะ ถ้าเลื่อนไปแม้ตำแหน่งเดียว SHAP จะชี้
    ฟีเจอร์ผิดตัวเงียบๆ — คำอธิบายดูสมเหตุสมผลแต่ผิด ซึ่งอันตรายกว่าไม่มีคำอธิบายเลย
    (บทเรียน B49: ลำดับ feature คือสัญญา ผิดแล้วไม่มี error ให้เห็น)

    **อ่าน `sequence.explanation` ไม่ใช่ `top_factors`** โดยตั้งใจ: มิติเดียวที่ผิดปกติ
    ไม่ทำให้โมเดล joint-residual ยิง (คุณสมบัติจริง ดู reports/l3_unified_2026-08-31.md
    §2.1) ซึ่งเป็นย่านที่ SHAP ยัง *แยกแยะมิติได้* — ต่างจากตอนทุกมิติหลุด
    distribution พร้อมกันที่ SHAP อิ่มตัว

    ไม่บันทึก residual ทดสอบลง history โดยตั้งใจ — ปนเปื้อนแล้ว threshold p99.9
    จะถูกดันขึ้นเหนือตัวที่กำลังทดสอบเอง
    """
    mismatched = []
    for j, dim in enumerate(DIM_NAMES):
        cur = [0.0] * L3.DIMS
        cur[j] = 25.0
        out = await _ok(cur)
        expl = out["sequence"]["explanation"]
        assert expl, f"{dim}: ไม่ได้ SHAP กลับมาเลย"
        top = expl[0]["feature"]
        if not top.startswith(dim + "_"):
            mismatched.append(f"{dim} -> {top}")
    assert not mismatched, (
        "SHAP ชี้มิติผิด: "
        + ", ".join(mismatched)
        + " -> ลำดับ SEQ_FEATURE_NAMES เลื่อนจาก _windows()"
    )


@pytest.mark.asyncio
async def test_all_shap_names_are_valid_and_unique(seeded):
    """ชื่อที่ออกมาต้องอยู่ในรายการ 18 ตัว และไม่ซ้ำกันเอง (mask keep map ถูกต้อง)."""
    out = await _ok([9.0] * L3.DIMS)
    names = [f["feature"] for f in out["sequence"]["explanation"]]
    assert names, "ไม่ได้ SHAP"
    assert (
        set(names) <= EXPECTED_SEQ_FEATURES
    ), f"ชื่อนอกรายการ: {set(names) - EXPECTED_SEQ_FEATURES}"
    assert len(names) == len(set(names)), f"ชื่อซ้ำ -> map index ผิด: {names}"
