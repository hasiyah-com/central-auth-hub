"""คำอธิบายของ L3 ต้องเชื่อถือได้ในย่านที่ระบบขึ้นธงจริง (B67).

ที่มา (1 ก.ย. 2569): เดิมระบบส่ง SHAP ออกไปในชื่อ `top_factors` ราวกับเป็น
"ปัจจัยหลัก" ที่ทำให้ขึ้นธง · วัดแล้วพบว่า **ความแม่นของ tree_path_dependent SHAP
ในการระบุมิติที่ถูกทำให้ผิดปกติ เริ่มลดลงตั้งแต่ช่วงที่คะแนนผ่านเกณฑ์แจ้งเตือน
ซึ่งเกิดก่อนที่ anomaly score จะชนเพดาน** — คือพังในย่านที่เราใช้งานจริงพอดี

    ย่าน                       คะแนน            SHAP ถูก   robust deviation ถูก
    ยังไม่ยิง                  0.48-0.53          6/6            6/6
    เพิ่งผ่านเกณฑ์             0.59-0.64          4/6            6/6
    สูงขึ้น                    0.71-0.72          2/6            6/6
    ชนเพดาน                    0.7439 (คงที่)     1/6            6/6

จึงเปลี่ยนคำอธิบายหลักเป็น robust deviation รายมิติ (คำนวณตรงจากข้อมูล ไม่ผ่านโมเดล)
และเปลี่ยนชื่อ SHAP เป็น `model_attribution` พร้อมคำเตือนว่าไม่ใช่สาเหตุ

⚠️ ตัวเลขเพดาน 0.743853 เป็นค่าของ **โมเดลที่ fit จาก fixture นี้ + คอนฟิกนี้ +
ทิศทางการทดลองนี้** ไม่ใช่เพดานสากลของ IsolationForest ทุกตัว

Run: docker compose exec hub-backend pytest tests/test_l3_explainability.py -v -s
"""

from __future__ import annotations

import asyncio
import random
import statistics
import time

import pytest

from app.security import l3_sequence as L3
from app.services.l3_sequence_client import evaluate_l3

USER = "pytest-l3-explain"
KEY = L3._REDIS_KEY.format(user_id=USER)

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

# เพดานที่วัดได้จาก fixture นี้ (history N(0,1) 1,500 แถว seed 42)
MEASURED_CEILING = 0.743853


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


async def _ok(resid, explain=False, access="allow", tries: int = 5) -> dict:
    """เรียกจนสำเร็จ — call แรกตอน cache เย็นอาจ timeout ตามที่ออกแบบไว้ (B63)."""
    for i in range(tries):
        out = await evaluate_l3(USER, _features(), resid, access, explain=explain)
        if out["error"] is None:
            return out
        assert out["error"] == "l3_timeout", f"ml-service ไม่พร้อม: {out['error']}"
        await asyncio.sleep(0.5 * (i + 1))
    raise AssertionError(f"ml-service ยัง warm ไม่เสร็จหลัง {tries} ครั้ง")


def _spike(base: float, spike: float, j: int) -> list[float]:
    v = [float(base)] * L3.DIMS
    v[j] = float(spike)
    return v


@pytest.fixture(scope="module")
def seeded():
    """history ปกติ 1,500 แถว seed 42 — ตรงกับ fixture ที่ใช้วัดตัวเลขในรายงาน."""
    r = _redis()
    if r is None:
        pytest.skip("Redis ไม่พร้อม")
    r.delete(KEY)
    rng = random.Random(42)
    for _ in range(1500):
        L3.record_residual(r, USER, [rng.gauss(0, 1) for _ in range(L3.DIMS)])
    yield r
    r.delete(KEY)


# ══════════════ 1. เพดานของคะแนน — มีจริงและวัดซ้ำได้ ══════════════


@pytest.mark.asyncio
async def test_score_saturates_at_measured_ceiling(seeded):
    """ผิดปกติ 8 เท่า กับ 100,000 เท่า ต้องได้คะแนนเท่ากันทุกหลัก.

    นี่คือหลักฐานว่าเพดานมีอยู่จริง ไม่ใช่การตีความ — และเป็นเหตุผลที่ห้ามอ่าน
    ขนาดของ anomaly score ว่าเป็น "ระดับความผิดปกติ" เกินย่านที่มันแยกแยะได้
    """
    a = (await _ok([8.0] * L3.DIMS))["sequence"]["raw_score"]
    b = (await _ok([100000.0] * L3.DIMS))["sequence"]["raw_score"]
    assert a == b, f"คาดว่าชนเพดานเท่ากัน แต่ได้ {a} กับ {b}"
    assert a == pytest.approx(MEASURED_CEILING, abs=1e-4), (
        f"เพดานของ fixture นี้เปลี่ยนไป ({a}) — ถ้าตั้งใจเปลี่ยนโมเดล/คอนฟิก "
        f"ต้องอัปเดตตัวเลขในรายงานด้วย"
    )


@pytest.mark.asyncio
async def test_score_still_discriminates_below_ceiling(seeded):
    """ใต้เพดาน คะแนนต้องยังไล่ระดับ — ไม่งั้นแปลว่าอิ่มตัวตั้งแต่ต้น."""
    scores = [(await _ok([v] * L3.DIMS))["sequence"]["raw_score"] for v in (2, 3, 4, 6)]
    assert scores == sorted(scores), f"คะแนนไม่ไล่ระดับตามความผิดปกติ: {scores}"
    assert len(set(scores)) == len(scores), "คะแนนซ้ำกันใต้เพดาน"


# ══════════════ 2. robust deviation ต้องชี้ถูกทุกย่าน รวมย่านที่ชนเพดาน ══════════════

BANDS = [
    pytest.param(0, 25, id="ยังไม่ยิง"),
    pytest.param(2, 5, id="ใกล้เกณฑ์"),
    pytest.param(3, 6, id="เพิ่งผ่านเกณฑ์"),
    pytest.param(4, 8, id="สูงขึ้น"),
    pytest.param(5, 10, id="ใกล้เพดาน"),
    pytest.param(8, 30, id="ชนเพดาน"),
    pytest.param(20, 60, id="เกินเพดานมาก"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("base", "spike"), BANDS)
async def test_diagnostic_points_at_the_right_dimension(seeded, base, spike):
    """ทำให้มิติเดียวเด่นกว่าเพื่อน -> คำอธิบายหลักต้องชี้มิตินั้น ครบทั้ง 6 มิติ.

    นี่คือคุณสมบัติที่ SHAP ทำไม่ได้ในย่านที่ยิง และเป็นเหตุผลทั้งหมดของการเปลี่ยน
    """
    wrong = []
    for j, dim in enumerate(DIM_NAMES):
        out = await _ok(_spike(base, spike, j))
        factors = out["diagnostic_factors"]
        if not factors:
            # ย่านที่ยังไม่ยิง sequence view ไม่ขึ้นธง จึงไม่มีคำอธิบายตามการออกแบบ
            assert (
                not out["is_anomaly"] or "sequence_residual" not in out["detected_by"]
            )
            continue
        top = factors[0]["feature"]
        if not top.startswith(dim + "_"):
            wrong.append(f"{dim} -> {top}")
    assert not wrong, f"คำอธิบายชี้มิติผิดที่ base={base} spike={spike}: {wrong}"


@pytest.mark.asyncio
async def test_diagnostic_factors_shape(seeded):
    """ทุกรายการต้องมีค่าที่ตรวจสอบย้อนได้ ไม่ใช่แค่ชื่อกับตัวเลขลอยๆ."""
    out = await _ok(_spike(8, 30, 1))
    factors = out["diagnostic_factors"]
    assert factors, "ยิงแล้วต้องมีคำอธิบาย"
    for f in factors:
        assert f["feature"] in EXPECTED_SEQ_FEATURES, f"ชื่อนอกรายการ 18 มิติ: {f}"
        assert f["owner"] == "l3_sequence"
        assert f["direction"] in ("above", "below")
        assert isinstance(f["deviation"], (int, float))
        # ต้องมี baseline ติดมาด้วย ไม่งั้นตรวจย้อนไม่ได้ว่าเทียบกับอะไร
        assert "baseline_median" in f and "baseline_iqr" in f
        assert f["baseline_iqr"] > 0
    devs = [abs(f["deviation"]) for f in factors]
    assert devs == sorted(devs, reverse=True), "ต้องเรียงตามขนาดส่วนเบี่ยงเบน"


@pytest.mark.asyncio
async def test_diagnostic_names_cover_all_18_and_never_duplicate(seeded):
    """ชื่อที่ออกมาต้องอยู่ในรายการ 18 มิติ และไม่ซ้ำกันเอง (index mapping ถูก)."""
    seen: set[str] = set()
    for j in range(L3.DIMS):
        out = await _ok(_spike(8, 30, j))
        names = [f["feature"] for f in out["diagnostic_factors"]]
        assert len(names) == len(set(names)), f"ชื่อซ้ำ: {names}"
        seen |= set(names)
    assert seen <= EXPECTED_SEQ_FEATURES, f"ชื่อนอกรายการ: {seen - EXPECTED_SEQ_FEATURES}"
    stats = {n.rsplit("_", 2)[1] for n in seen}
    assert stats <= set(STAT_NAMES)


# ══════════════ 3. SHAP ต้องไม่ถูกนำเสนอเป็นสาเหตุอีกต่อไป ══════════════


def test_top_factors_field_is_gone():
    """`top_factors` อ่านแล้วเข้าใจว่าเป็นปัจจัยหลัก — ต้องไม่มีชื่อนี้อีก."""
    from app.services.l3_sequence_client import UNIFIED_QUIET

    assert "top_factors" not in UNIFIED_QUIET
    assert "diagnostic_factors" in UNIFIED_QUIET
    assert "model_attribution" in UNIFIED_QUIET


@pytest.mark.asyncio
async def test_attribution_carries_caveat(seeded):
    """ทุกคำตอบต้องมีคำเตือนกำกับ SHAP ไม่ใช่ให้ผู้อ่านเดาเอง."""
    out = await _ok(_spike(8, 30, 0), explain=True)
    caveat = out["model_attribution_caveat"]
    assert caveat and "ไม่ใช่สาเหตุ" in caveat


@pytest.mark.asyncio
async def test_shap_is_opt_in(seeded):
    """ไม่ขอ -> ไม่คำนวณ SHAP ของ sequence (ประหยัดเวลาบน login path)."""
    off = await _ok(_spike(8, 30, 0), explain=False)
    on = await _ok(_spike(8, 30, 0), explain=True)
    seq_off = [f for f in off["model_attribution"] if f["owner"] == "l3_sequence"]
    seq_on = [f for f in on["model_attribution"] if f["owner"] == "l3_sequence"]
    assert not seq_off, "ไม่ได้ขอ SHAP แต่ยังคำนวณให้"
    assert seq_on, "ขอ SHAP แล้วแต่ไม่ได้"


@pytest.mark.asyncio
async def test_explanation_never_changes_the_score(seeded):
    """เปิด/ปิดคำอธิบาย -> คะแนนและการยิงต้องเท่ากันทุกบิต.

    คำอธิบายต้องเป็นการ *สังเกต* ไม่ใช่ส่วนหนึ่งของการตัดสิน
    """
    for resid in ([9.0] * L3.DIMS, _spike(3, 6, 2), [0.05] * L3.DIMS):
        off = (await _ok(resid, explain=False))["sequence"]
        on = (await _ok(resid, explain=True))["sequence"]
        assert off["raw_score"] == on["raw_score"], f"คะแนนขยับเมื่อขอคำอธิบาย: {resid}"
        assert off["fired"] == on["fired"]
        assert off["tier"] == on["tier"]


# ══════════════ 4. ที่มาของคำตอบต้องบันทึกไว้ในผลลัพธ์ ══════════════


@pytest.mark.asyncio
async def test_result_records_method_and_versions(seeded):
    """ผลลัพธ์ต้องบอกได้เองว่าคำนวณด้วยวิธีใด baseline ไหน โมเดลรุ่นใด."""
    out = await _ok(_spike(8, 30, 0))
    assert out["diagnostic_method"] == "robust_window_deviation_v1"
    assert out["baseline_version"] == "win-median-iqr-v1"
    assert out["sequence"]["model_version"] == L3.MODEL_VERSION
    assert out["model_version"].get("sequence") == L3.MODEL_VERSION
    assert out["model_version"].get("point")


# ══════════════ 5. latency + concurrency หลังเพิ่มคำอธิบายหลัก ══════════════


@pytest.mark.asyncio
async def test_latency_within_login_budget(seeded):
    """คำอธิบายหลักคำนวณทุกครั้ง — ต้องไม่ทำให้ L3 เกินครึ่งของงบ timeout."""
    from app.config import settings

    await _ok([0.1] * L3.DIMS)  # อุ่น cache ก่อนวัด
    lat = []
    for _ in range(30):
        t = time.perf_counter()
        out = await evaluate_l3(USER, _features(), [0.1] * L3.DIMS, "allow")
        lat.append((time.perf_counter() - t) * 1000)
        assert out["error"] is None
    lat.sort()
    p50, p95 = lat[len(lat) // 2], lat[int(len(lat) * 0.95)]
    budget = settings.l3_timeout_seconds * 1000 / 2
    print(
        f"\n  latency p50={p50:.1f}ms p95={p95:.1f}ms max={lat[-1]:.1f}ms งบ={budget:.0f}ms"
    )
    assert p95 < budget, f"p95 {p95:.1f}ms เกินครึ่งของงบ {budget:.0f}ms"


@pytest.mark.asyncio
async def test_concurrent_requests_agree(seeded):
    """ยิงพร้อมกันหลายอัน -> ผลต้องตรงกันทุกอัน (ไม่มี race ใน baseline/cache)."""
    await _ok([0.1] * L3.DIMS)
    resid = _spike(8, 30, 3)
    outs = await asyncio.gather(
        *[evaluate_l3(USER, _features(), resid, "allow") for _ in range(20)]
    )
    ok = [o for o in outs if o["error"] is None]
    assert len(ok) >= 18, f"สำเร็จเพียง {len(ok)}/20"
    scores = {o["sequence"]["raw_score"] for o in ok}
    tops = {
        o["diagnostic_factors"][0]["feature"] for o in ok if o["diagnostic_factors"]
    }
    assert len(scores) == 1, f"คะแนนไม่ตรงกัน: {scores}"
    assert len(tops) <= 1, f"คำอธิบายไม่ตรงกัน: {tops}"
    print(f"\n  concurrency 20 -> สำเร็จ {len(ok)} · คะแนนเดียว {scores}")


@pytest.mark.asyncio
async def test_stdev_of_repeated_calls_is_zero(seeded):
    """เรียกซ้ำต้องได้ค่าเดิมเป๊ะ — คำอธิบายต้อง deterministic."""
    vals = [
        (await _ok(_spike(8, 30, 4)))["diagnostic_factors"][0]["deviation"]
        for _ in range(5)
    ]
    assert statistics.pstdev(vals) == 0.0, f"ค่าไม่คงที่: {vals}"
