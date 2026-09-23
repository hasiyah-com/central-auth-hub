"""วินิจฉัยเวลาและความพร้อมของ L3 — ยิงจริงผ่าน `evaluate_l3` แล้วนับผล.

ไม่เขียนอะไรลง DB · อ่าน/เขียนเฉพาะ key ของผู้ใช้สมมติใน Redis ของเทส (DB 15)

    docker compose exec -e REDIS_URL=<redis ของเทส /15> \\
        -e ML_SERVICE_URL=http://ml-service-test:9000 -e TEST_ENVIRONMENT=1 \\
        hub-backend python -m scripts.diag_l3_concurrency [--sequential 300]

โหมด
  (ค่าเริ่มต้น)      ยิงพร้อมกัน 1 / 5 / 10 / 20 ตัว — หาจุดที่ timeout เริ่มเกิด
  --sequential N    ยิงเรียงทีละตัว N ครั้ง — p50 / p95 / p99 และอัตรา error
  --tiers           ประวัติแต่ละขนาดได้ eligibility อะไร (abstain หรือไม่)
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import os
import random
import time

from app.config import settings
from app.redis_client import redis_client
from app.security import l3_sequence as L3
from app.security.rule_engine import FEAT
from app.services.l3_sequence_client import evaluate_l3

USER = "diag-l3-concurrency"
KEY = f"l3resid:{USER}"


def _features() -> list[float]:
    v = [0.0] * 23
    v[FEAT["permission_change_age"]] = 365.0
    return v


def _seed_history(n: int) -> None:
    """ประวัติ n แถว seed 42 — ตรงกับ fixture ของเทส (ml-service ต้องคำนวณ sequence จริง)."""
    redis_client.delete(KEY)
    rng = random.Random(42)
    for _ in range(n):
        L3.record_residual(
            redis_client, USER, [rng.gauss(0, 1) for _ in range(L3.DIMS)]
        )


async def _one(resid):
    t0 = time.perf_counter()
    out = await evaluate_l3(USER, _features(), resid, "allow")
    return out, (time.perf_counter() - t0) * 1000


def _pct(sorted_vals, p):
    return sorted_vals[min(int(p * len(sorted_vals)), len(sorted_vals) - 1)]


async def _warm(resid) -> None:
    for _ in range(20):
        out, _ = await _one(resid)
        if out.get("error") is None:
            return


async def concurrency(resid) -> None:
    for n in (1, 5, 10, 20):
        outs = await asyncio.gather(*[_one(resid) for _ in range(n)])
        errs = collections.Counter(o.get("error") for o, _ in outs)
        lat = sorted(ms for _, ms in outs)
        print(
            f"พร้อมกัน {n:>2}: ผล {dict(errs)} · "
            f"latency p50 {_pct(lat, .5):.0f}ms max {lat[-1]:.0f}ms"
        )


async def sequential(resid, n: int) -> None:
    lat, errs = [], collections.Counter()
    for _ in range(n):
        out, ms = await _one(resid)
        lat.append(ms)
        errs[out.get("error")] += 1
    lat.sort()
    ok = errs.get(None, 0)
    print(
        f"เรียงทีละตัว n={n}: p50 {_pct(lat, .5):.1f}ms · p95 {_pct(lat, .95):.1f}ms · "
        f"p99 {_pct(lat, .99):.1f}ms · max {lat[-1]:.1f}ms"
    )
    print(
        f"  ML ตอบสำเร็จ {ok}/{n} ({ok / n:.1%}) · error {dict((k, v) for k, v in errs.items() if k)}"
    )


async def tiers() -> None:
    """ขนาดประวัติตามช่วงของแผนขั้นที่ 6 -> eligibility ที่ได้จริงจาก ml-service."""
    resid = [0.1] * L3.DIMS
    for size in (0, 49, 99, 499, 999, 1000, 4999, 5000):
        _seed_history(size)
        out = None
        for _ in range(5):
            out, _ = await _one(resid)
            if out.get("error") is None:
                break
        seq = (out or {}).get("sequence") or {}
        print(
            f"  ประวัติ {size:>5}: eligibility {seq.get('eligibility')!s:<11} "
            f"n_history {seq.get('n_history')} · error {out.get('error')}"
        )


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sequential", type=int, default=0)
    ap.add_argument("--tiers", action="store_true")
    a = ap.parse_args()

    assert settings.redis_url.rstrip("/").endswith("/15"), "ต้องชี้ Redis DB ของเทสเท่านั้น"
    print(
        f"timeout {settings.l3_timeout_seconds}s · ml {os.environ.get('ML_SERVICE_URL')}"
    )
    try:
        if a.tiers:
            await tiers()
            return
        _seed_history(1500)
        resid = [8.0] * L3.DIMS
        resid[3] = 30.0
        await _warm(resid)
        if a.sequential:
            await sequential(resid, a.sequential)
        else:
            await concurrency(resid)
    finally:
        redis_client.delete(KEY)


if __name__ == "__main__":
    asyncio.run(main())
