"""ตัวตัดสินของ ML Capacity Gate — แต่ละเกณฑ์ต้องล้มได้จริงเมื่อข้อมูลไม่ผ่าน.

หมายเหตุลำดับงาน: เทสนี้เขียน**หลัง** `scripts/ml_capacity_gate.py::evaluate` (ผิดลำดับ
TDD ของโปรเจกต์) จึงตรวจแบบกลับด้าน — เริ่มจากผลที่ผ่าน แล้วทำให้เสียทีละเกณฑ์ ต้องเห็น
เกณฑ์นั้นล้ม ถ้าเกณฑ์ใดล้มไม่ได้ แปลว่าเกณฑ์นั้นไม่ได้ตรวจอะไร

เกณฑ์ทั้งหมดกำหนดก่อนวัดครั้งแรก (ดู docstring ของสคริปต์) — เทสนี้ล็อกค่าไว้ด้วย
"""

from __future__ import annotations

import copy
import json

import pytest

G = pytest.importorskip("scripts.ml_capacity_gate")


def _stats(workers: int, fits: int, rss: int = 200_000) -> dict:
    return {
        1000 + i: {
            "pid": 1000 + i,
            "fits_total": fits,
            "max_fits_per_user": 1 if fits else 0,
            "users_fitted": fits,
            "cache_entries": fits,
            "rss_kb": rss,
        }
        for i in range(workers)
    }


def _score(seq=0.1234):
    return json.dumps(
        {
            "seq_score": seq,
            "seq_raw": 0.4,
            "seq_percentile": 0.5,
            "seq_n_history": 2000,
            "seq_eligibility": "challenge",
            "point_score": 0.2,
        },
        sort_keys=True,
    )


def _scores():
    return {f"cap-user-{i:02d}|[0]": {_score()} for i in range(G.N_USERS)}


def _level(p95=120.0, errors=0):
    return {
        "latency": {"p95_ms": p95, "errors": errors},
        "scores": _scores(),
    }


def _passing(workers=2):
    rounds = [
        {
            "levels": {str(c): _level() for c in G.CONCURRENCY},
            "stats": _stats(workers, G.N_USERS),
        }
        for _ in range(G.STEADY_ROUNDS)
    ]
    return dict(
        workers=workers,
        cold={"scores": _scores(), "latency": {}, "error_kinds": []},
        cold_stats=_stats(workers, 10),
        warm={"rounds": 3, "stable": True, "fits_total": workers * G.N_USERS},
        warm_stats=_stats(workers, G.N_USERS),
        rounds=rounds,
        elapsed=1.0,
    )


def _eval(kw):
    return G.evaluate(**kw)


def test_thresholds_are_the_preregistered_values():
    assert G.P95_BUDGET_MS == 250.0
    assert G.RSS_GROWTH_MAX == 0.05
    assert G.CONCURRENCY == (1, 5, 10, 20)
    assert G.L3_DEADLINE_MS == 500.0


def test_passing_input_passes():
    out = _eval(_passing())
    assert out["passed"], {k: v["pass"] for k, v in out["checks"].items()}


def test_p95_over_budget_fails_p1():
    kw = _passing()
    kw["rounds"][1]["levels"]["10"]["latency"]["p95_ms"] = 251.0
    out = _eval(kw)
    assert not out["checks"]["P1_steady_p95"]["pass"] and not out["passed"]


def test_any_error_fails_p1():
    kw = _passing()
    kw["rounds"][0]["levels"]["1"]["latency"]["errors"] = 1
    assert not _eval(kw)["checks"]["P1_steady_p95"]["pass"]


def test_refit_of_a_user_fails_p2():
    kw = _passing()
    pid = next(iter(kw["cold_stats"]))
    kw["cold_stats"][pid]["max_fits_per_user"] = 2
    assert not _eval(kw)["checks"]["P2_fit_storm"]["pass"]


def test_fits_growing_during_steady_fails_p2():
    kw = _passing()
    pid = next(iter(kw["rounds"][-1]["stats"]))
    kw["rounds"][-1]["stats"][pid]["fits_total"] = G.N_USERS + 1
    assert not _eval(kw)["checks"]["P2_fit_storm"]["pass"]


def test_missing_worker_fails_p2():
    kw = _passing(workers=4)
    kw["rounds"][-1]["stats"] = _stats(3, G.N_USERS)
    assert not _eval(kw)["checks"]["P2_fit_storm"]["pass"]


def test_unstable_warmup_fails_p2():
    kw = _passing()
    kw["warm"]["stable"] = False
    assert not _eval(kw)["checks"]["P2_fit_storm"]["pass"]


def test_score_disagreement_fails_p3():
    kw = _passing()
    key = next(iter(kw["rounds"][2]["levels"]["20"]["scores"]))
    kw["rounds"][2]["levels"]["20"]["scores"][key] = {_score(0.1235)}
    out = _eval(kw)
    assert not out["checks"]["P3_score_agreement"]["pass"]
    assert out["checks"]["P3_score_agreement"]["disagreements"]


def test_cold_versus_warm_disagreement_fails_p3():
    kw = _passing()
    key = next(iter(kw["cold"]["scores"]))
    kw["cold"]["scores"][key] = {_score(0.9)}
    assert not _eval(kw)["checks"]["P3_score_agreement"]["pass"]


def test_abstaining_probe_fails_p3():
    """probe ที่ไม่มีคะแนน sequence พิสูจน์ความสอดคล้องไม่ได้."""
    kw = _passing()
    key = next(iter(kw["cold"]["scores"]))
    for src in [kw["cold"]] + [
        lvl for r in kw["rounds"] for lvl in r["levels"].values()
    ]:
        src["scores"][key] = {_score(None)}
    assert not _eval(kw)["checks"]["P3_score_agreement"]["pass"]


def test_memory_growth_over_limit_fails_p4():
    kw = _passing()
    last = kw["rounds"][-1]["stats"]
    pid = next(iter(last))
    last[pid]["rss_kb"] = int(200_000 * 1.06)
    assert not _eval(kw)["checks"]["P4_memory"]["pass"]


def test_memory_growth_within_limit_passes_p4():
    kw = _passing()
    last = kw["rounds"][-1]["stats"]
    pid = next(iter(last))
    last[pid]["rss_kb"] = int(200_000 * 1.04)
    assert _eval(kw)["checks"]["P4_memory"]["pass"]


def test_unknown_memory_fails_p4():
    kw = _passing()
    for st in (kw["rounds"][0]["stats"], kw["rounds"][-1]["stats"]):
        for s in st.values():
            s["rss_kb"] = None
    assert not _eval(kw)["checks"]["P4_memory"]["pass"]


def test_refuses_dev_and_test_redis_databases():
    assert G._db_index("redis://redis:6379/0") in G.FORBIDDEN_DBS
    assert G._db_index("redis://redis:6379/15") in G.FORBIDDEN_DBS
    assert G._db_index("redis://redis:6379") in G.FORBIDDEN_DBS  # ไม่ระบุ = DB 0
    assert G._db_index("redis://redis:6379/13") not in G.FORBIDDEN_DBS


def test_score_signature_ignores_duplicate_state():
    """duplicate_ratio เปลี่ยนตามการส่งซ้ำโดยออกแบบ — ห้ามนับเป็นความไม่สอดคล้อง."""
    base = {
        "sequence": {"score": 0.1, "raw_score": 0.2},
        "point": {"anomaly_score": 0.3},
    }
    a = G._score_of({**base, "duplicate_ratio": 0.0, "monitoring_decision": "none"})
    b = G._score_of(
        {**base, "duplicate_ratio": 0.9, "monitoring_decision": "investigate"}
    )
    assert a == b


def test_stats_open_a_new_connection_every_call():
    """บั๊กที่เจอในรอบแรก: keep-alive พาทุก request ไป worker เดิม → เห็น pid เดียว
    ทั้งที่รัน 4 worker · P2/P4 จึงล้มเพราะตัววัด ไม่ใช่เพราะ ml-service."""
    import asyncio

    import httpx

    seen = []

    def handler(request):
        seen.append(request.headers.get("connection"))
        return httpx.Response(
            200,
            json={
                "data": {
                    "pid": len(seen) % 2,
                    "fits_total": 0,
                    "max_fits_per_user": 0,
                    "cache_entries": 0,
                    "rss_kb": 1,
                }
            },
        )

    gate = G.Gate.__new__(G.Gate)
    gate.url = "http://ml"
    gate.workers = 2

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await gate.stats(c)

    out = asyncio.run(go())
    assert len(out) == 2
    assert seen and all(v == "close" for v in seen)


def test_load_uses_a_new_connection_per_request_like_the_hub():
    """hub สร้าง httpx.AsyncClient ใหม่ทุกครั้ง (l3_sequence_client.py) = connection ใหม่
    ทุก request · ถ้าตัววัดใช้ keep-alive ตัวเลขจะดีกว่าจริงและกระจาย worker ไม่เหมือนจริง."""
    import asyncio

    import httpx

    seen = []

    def handler(request):
        seen.append(request.headers.get("connection"))
        return httpx.Response(200, json={"data": {"sequence": {}, "point": {}}})

    gate = G.Gate("http://ml", "redis://localhost:6379/13", 2, 1)
    gate.features = [0.0] * 23

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            await gate.cold_burst(c)
            await gate.steady(c, 5)

    asyncio.run(go())
    assert seen and all(v == "close" for v in seen), set(seen)


def test_waits_until_every_worker_answers_before_measuring():
    """health ตอบจาก worker ตัวเดียวก็ผ่าน — ต้องรอจนเห็นครบทุก pid ก่อน cold burst."""
    import asyncio

    import httpx

    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        pid = 1 if calls["n"] < 5 else (calls["n"] % 3) + 1  # 4 ครั้งแรกเห็นแค่ pid 1
        return httpx.Response(
            200,
            json={
                "data": {
                    "pid": pid,
                    "fits_total": 0,
                    "max_fits_per_user": 0,
                    "cache_entries": 0,
                    "rss_kb": 1,
                }
            },
        )

    gate = G.Gate.__new__(G.Gate)
    gate.url = "http://ml"
    gate.workers = 3

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await gate.wait_ready(c, timeout_s=5)

    assert asyncio.run(go()) == 3


def test_reports_how_steady_load_was_shared_between_workers():
    """ข้อมูลประกอบของข้อ 4 — ไม่ใช่เกณฑ์ผ่าน (เกณฑ์กำหนดไว้ก่อนวัดแล้ว)."""
    kw = _passing(workers=2)
    for s in kw["warm_stats"].values():
        s["l3_requests"] = 100
    last = kw["rounds"][-1]["stats"]
    a, b = list(last)
    last[a]["l3_requests"] = 100 + 900
    last[b]["l3_requests"] = 100 + 300
    out = _eval(kw)
    share = out["load_share"]
    assert share["per_process"] == {str(a): 900, str(b): 300}
    assert share["max_over_mean"] == 1.5
    assert out["passed"]  # ไม่กระทบผลผ่าน/ไม่ผ่าน


def test_load_share_is_unknown_without_counters():
    out = _eval(_passing())
    assert out["load_share"]["max_over_mean"] is None


def test_passing_input_is_not_mutated():
    kw = _passing()
    snap = copy.deepcopy(kw)
    _eval(kw)
    assert kw == snap
