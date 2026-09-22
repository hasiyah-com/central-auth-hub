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


def test_result_records_whether_point_shap_was_on():
    """ผลของการทดลองข้าม SHAP ต้องแยกได้จากผลปกติ — ไม่งั้นเอาไปเทียบผิดชุด."""
    kw = _passing()
    for s in kw["rounds"][-1]["stats"].values():
        s["point_shap"] = False
    assert _eval(kw)["point_shap"] is False

    kw = _passing()
    for s in kw["rounds"][-1]["stats"].values():
        s["point_shap"] = True
    assert _eval(kw)["point_shap"] is True


def test_mixed_or_unknown_point_shap_mode_is_reported_as_unknown():
    kw = _passing()
    vals = [True, False]
    for s, v in zip(kw["rounds"][-1]["stats"].values(), vals):
        s["point_shap"] = v
    assert _eval(kw)["point_shap"] is None
    assert _eval(_passing())["point_shap"] is None  # ml-service รุ่นที่ยังไม่รายงาน


def _gate(share):
    g = G.Gate("http://ml", "redis://localhost:6379/13", 4, 1, high_score_share=share)
    g.set_feature_names(
        [
            "is_new_country",
            "is_new_device",
            "failed_logins_24h",
            "is_thailand",
            "permission_change_age",
        ]
    )
    return g


@pytest.mark.parametrize("share,expected", [(0.0, 0), (0.33, 7), (1.0, 20)])
def test_probe_mix_follows_the_high_score_share(share, expected):
    """SHAP ของ point view คำนวณเฉพาะคะแนน >= 0.50 · feature ชุดเดียวที่คะแนน 0.405
    จะทำให้ข้าม SHAP ทุก request = วัดผิดสิ่ง จึงต้องผสม probe คะแนนสูงตามสัดส่วน."""
    g = _gate(share)
    high = [f for f in g.probe_features if f != g.normal_features]
    assert len(high) == expected


def test_high_score_features_carry_anomaly_signals():
    g = _gate(1.0)
    f = g.probe_features[0]
    assert f[0] == 1.0 and f[1] == 1.0 and f[2] >= 1.0  # new country / device / failed
    assert g.normal_features[4] == 365.0  # permission_change_age ค่ากลางตามสัญญา


def test_each_probe_keeps_the_same_features_every_call():
    """P3 เทียบคะแนนต่อ probe — feature ของ probe ต้องคงที่ทุกครั้ง."""
    import asyncio

    import httpx

    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"data": {"sequence": {}, "point": {}}})

    g = _gate(0.33)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            await g.steady(c, 5)

    asyncio.run(go())
    by_user = {}
    for b in bodies:
        by_user.setdefault(b["user_id"], set()).add(tuple(b["features"]))
    assert all(len(v) == 1 for v in by_user.values())


def test_share_must_be_a_fraction():
    with pytest.raises(ValueError):
        G.Gate("http://ml", "redis://localhost:6379/13", 4, 1, high_score_share=1.5)


# ── วิธีวัด v2 (กำหนดก่อนวัด 2026-09-22, รายงาน §13) ─────────────────────────


def test_pooled_p95_uses_every_request_of_every_round():
    """v2 ตัดสินจาก p95 ของทุก request ในทุกรอบ ไม่ใช่ค่าแย่สุดของรอบเดียว."""
    raw = [
        {"20": [100.0] * 95 + [300.0] * 5},
        {"20": [100.0] * 100},
        {"20": [100.0] * 100},
    ]
    pooled = G.pool_levels(raw)
    assert pooled["20"]["n"] == 300
    assert pooled["20"]["p95_ms"] == 100.0  # 5/300 ช้า < 5% → p95 ไม่ใช่ 300


def test_steady_returns_raw_latencies_for_pooling():
    import asyncio

    import httpx

    def handler(request):
        return httpx.Response(200, json={"data": {"sequence": {}, "point": {}}})

    g = _gate(0.0)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await g.steady(c, 5)

    out = asyncio.run(go())
    assert len(out["raw_ms"]) == G.REQUESTS_PER_LEVEL


def test_arrival_times_are_poisson_and_reproducible():
    a = G.arrival_times(rate=50.0, seconds=60.0, seed=7)
    b = G.arrival_times(rate=50.0, seconds=60.0, seed=7)
    assert a == b
    assert all(0.0 <= t < 60.0 for t in a)
    assert a == sorted(a)
    assert 2700 <= len(a) <= 3300  # ~ rate × seconds = 3000


def test_open_loop_fires_on_schedule_and_counts_misses():
    import asyncio

    import httpx

    def handler(request):
        return httpx.Response(200, json={"data": {"sequence": {}, "point": {}}})

    g = _gate(0.0)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await g.open_loop(c, rate=20.0, seconds=1.0, seed=3)

    out = asyncio.run(go())
    assert out["offered"] == len(G.arrival_times(20.0, 1.0, 3))
    assert out["latency"]["n"] == out["offered"]
    assert out["latency"]["errors"] == 0
    assert "over_deadline" in out["latency"]


def test_permutation_test_detects_a_clear_difference():
    a = [230, 240, 235, 245, 238, 242, 236, 244, 239, 241]
    b = [200, 205, 198, 210, 202, 207, 199, 204, 201, 206]
    p = G.permutation_p_value(a, b)
    assert p < 0.001


def test_permutation_test_does_not_invent_a_difference():
    a = [230, 200, 245, 205, 238, 198, 236, 210, 239, 202]
    b = [240, 207, 235, 204, 242, 199, 244, 201, 241, 206]
    assert G.permutation_p_value(a, b) > 0.2


def test_permutation_test_is_exact_and_two_sided():
    # สลับฝั่งแล้ว p เท่าเดิม
    a, b = [1, 2, 3, 4], [5, 6, 7, 8]
    assert G.permutation_p_value(a, b) == G.permutation_p_value(b, a)
    # 4 ต่อ 4 ที่แยกขาด: เป็นไปได้ 70 แบบ สุดขั้วสองทาง 2 แบบ → p = 2/70
    assert abs(G.permutation_p_value(a, b) - 2 / 70) < 1e-12


def test_v2_decision_rule():
    """ผ่าน = median ของ p95 รวมต่อครั้ง ≤ 225 และอย่างน้อย 9/10 ครั้ง ≤ 250."""
    ok = [200] * 9 + [260]
    assert G.p1_v2_pass(ok)
    assert not G.p1_v2_pass([200] * 8 + [260, 260])  # 8/10
    assert not G.p1_v2_pass([230] * 10)  # median เกิน 225 แม้ทุกครั้ง ≤ 250


# ── fit นอกเส้นทาง request (§15) ─────────────────────────────────────────────

WARMING = {
    "sequence": {"eligibility": "abstain", "abstain_reason": "model_warming"},
    "point": {"anomaly_score": 0.4},
}
SCORED = {
    "sequence": {"score": 0.1, "raw_score": 0.3, "eligibility": "challenge"},
    "point": {"anomaly_score": 0.4},
}


def _mock(bodies_to_return):
    import httpx

    it = iter(bodies_to_return)

    def handler(request):
        return httpx.Response(200, json={"data": next(it)})

    return httpx.MockTransport(handler)


def test_warming_answers_are_counted_not_compared():
    """P3 ที่ปรับการตีความแล้ว (อนุมัติ 2026-09-22): model_warming ไม่มีคะแนน จึงไม่เข้า
    การเทียบ แต่ต้องนับแยกไว้."""
    import asyncio

    import httpx

    g = _gate(0.0)
    answers = [WARMING] * 12 + [SCORED] * 8

    async def go():
        async with httpx.AsyncClient(transport=_mock(answers)) as c:
            return await g.cold_burst(c)

    out = asyncio.run(go())
    assert out["warming"] == 12
    for sigs in out["scores"].values():
        assert all(json.loads(s)["seq_score"] is not None for s in sigs)


def test_cold_open_loop_sends_distinct_users_first():
    """กรณีแย่สุดหลัง restart: N arrival แรกเป็นคนละคนทั้งหมด (ยังไม่มีใครมีโมเดล)."""
    order = G.cold_user_order(n_users=50, n_arrivals=120)
    assert len(set(order[:50])) == 50
    assert order[50:100] == order[:50]


def test_cold_open_loop_reports_warming_share_over_time():
    import asyncio

    import httpx

    g = _gate(0.0)
    g.cold_users = [f"cold-{i:04d}" for i in range(10)]
    n = len(G.arrival_times(20.0, 1.0, 5))
    answers = [WARMING] * (n // 2) + [SCORED] * (n - n // 2)

    async def go():
        async with httpx.AsyncClient(transport=_mock(answers)) as c:
            return await g.cold_open_loop(c, rate=20.0, seconds=1.0, seed=5)

    out = asyncio.run(go())
    assert out["offered"] == n
    assert out["warming"] == n // 2
    assert 0.0 <= out["warming_share"] <= 1.0
    assert out["buckets"] and all("warming_share" in b for b in out["buckets"])


def test_cold_criterion_is_preregistered():
    assert G.COLD_RATE == 60.0
    assert G.COLD_SECONDS == 60.0
    assert G.COLD_USERS == 400
    assert G.COLD_OVER_DEADLINE_MAX == 0.01


def test_cold_decision():
    ok = {"latency": {"p95_ms": 240.0, "errors": 0, "over_deadline": 10, "n": 3600}}
    assert G.cold_pass(ok)
    assert not G.cold_pass({"latency": {**ok["latency"], "p95_ms": 251.0}})
    assert not G.cold_pass({"latency": {**ok["latency"], "errors": 1}})
    assert not G.cold_pass({"latency": {**ok["latency"], "over_deadline": 37}})


def test_p2_counts_cap_fits_on_top_of_the_cold_phase():
    """บั๊กที่ smoke ของ §15 จับได้: ช่วงเย็น fit ผู้ใช้ชุด cold อีก 400 คน · P2 ต้องนับเฉพาะ
    fit ที่เกิดหลังช่วงเย็น (ผู้ใช้ชุด cap 20 คน) ไม่ใช่ยอดรวม."""
    kw = _passing(workers=2)
    baseline = {pid: 170 for pid in kw["rounds"][-1]["stats"]}
    for st in (
        kw["warm_stats"],
        kw["rounds"][-1]["stats"],
        *(r["stats"] for r in kw["rounds"]),
    ):
        for s in st.values():
            s["fits_total"] = 170 + G.N_USERS
    out = G.evaluate(**kw, fit_baseline=baseline)
    assert out["checks"]["P2_fit_storm"]["pass"]
    # ถ้าไม่ส่งฐาน ยอดรวมไม่เท่ากับ 20 ต้องล้ม (พฤติกรรมเดิม)
    assert not G.evaluate(**kw)["checks"]["P2_fit_storm"]["pass"]


def test_p2_with_baseline_still_catches_a_refit():
    kw = _passing(workers=2)
    baseline = {pid: 170 for pid in kw["rounds"][-1]["stats"]}
    for st in (kw["warm_stats"], *(r["stats"] for r in kw["rounds"])):
        for s in st.values():
            s["fits_total"] = 170 + G.N_USERS
    pid = next(iter(kw["rounds"][-1]["stats"]))
    kw["rounds"][-1]["stats"][pid]["fits_total"] += 1  # fit เพิ่มช่วง steady
    assert not G.evaluate(**kw, fit_baseline=baseline)["checks"]["P2_fit_storm"]["pass"]


def test_wait_outcomes_sum_every_worker():
    """§17: งบรอได้คะแนนคืนกี่ครั้ง — รวมทุก worker จากตัวนับของ ml-service."""
    stats = {
        1: {"fit_wait_scored": 3, "warming_responses": 97},
        2: {"fit_wait_scored": 1, "warming_responses": 99},
    }
    out = G.wait_outcomes(stats)
    assert out == {"scored_after_wait": 4, "warming": 196, "scored_share": 0.02}


def test_wait_outcomes_unknown_when_not_reported():
    assert G.wait_outcomes({1: {}})["scored_share"] is None


# ── แบ่ง worker ตามผู้ใช้ + C3 ความสม่ำเสมอ (§20) ───────────────────────────


def test_consistency_violations_count_warming_after_a_completed_score():
    """C3: เมื่อผู้ใช้ได้คะแนนจริงแล้ว request ที่มาหลังคะแนนนั้นเสร็จต้องไม่ได้ warming อีก.
    record = (user, arrival_s, done_s, warming)."""
    records = [
        ("a", 0.0, 0.05, True),  # ครั้งแรก warming — ปกติ
        ("a", 1.0, 1.02, False),  # ได้คะแนน เสร็จที่ 1.02
        ("a", 2.0, 2.05, True),  # มาทีหลัง 1.02 แต่ warming → ละเมิด
        ("b", 0.5, 0.55, False),
        ("b", 0.51, 0.60, True),  # มาก่อนคะแนนแรกเสร็จ (0.55) → ไม่นับ
        ("b", 3.0, 3.01, False),
    ]
    assert G.consistency_violations(records) == 1


def test_no_violation_when_every_later_request_is_scored():
    records = [("a", 0.0, 0.05, True), ("a", 1.0, 1.1, False), ("a", 2.0, 2.1, False)]
    assert G.consistency_violations(records) == 0


def test_shard_urls_follow_the_hub_hash():
    from app.services.l3_sequence_client import shard_index

    g = _gate(0.0)
    g.shard_base_port, g.shard_count = 9100, 4
    for u in ("cap-user-00", "cold-user-0007", "x"):
        assert g.url_for(u) == f"http://ml:{9100 + shard_index(u, 4)}"


def test_without_shards_every_user_uses_the_shared_url():
    g = _gate(0.0)
    assert g.url_for("cap-user-00") == "http://ml"


def test_p2_in_shard_mode_expects_one_fit_per_user_in_total():
    kw = _passing(workers=4)
    per = [6, 5, 5, 4]  # รวม 20 = N_USERS — แต่ละคน fit ครั้งเดียวทั้งระบบ
    for st in (kw["warm_stats"], *(r["stats"] for r in kw["rounds"])):
        for (pid, s), n in zip(st.items(), per):
            s["fits_total"] = n
    assert G.evaluate(**kw, shard_mode=True)["checks"]["P2_fit_storm"]["pass"]
    # ถ้ามีคนถูก fit สองที่ ยอดรวมจะเกิน N_USERS → ต้องล้ม
    for st in (kw["warm_stats"], *(r["stats"] for r in kw["rounds"])):
        next(iter(st.values()))["fits_total"] += 1
    assert not G.evaluate(**kw, shard_mode=True)["checks"]["P2_fit_storm"]["pass"]


def test_passing_input_is_not_mutated():
    kw = _passing()
    snap = copy.deepcopy(kw)
    _eval(kw)
    assert kw == snap
