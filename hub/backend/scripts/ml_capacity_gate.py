"""ML Capacity Gate — วัดความจุของ ml-service (L3) ต่อจำนวน worker และ concurrency.

รันในคอนเทนเนอร์บน `cah-net` (ใช้ image ของ hub-backend เพราะมี httpx + redis)
ผ่าน `scripts/test/ml_capacity_gate.sh` ซึ่งเปิด ml-service ใหม่ทุกรอบ (cache เย็น)

ข้อมูลทั้งหมดเป็นของสังเคราะห์ใน Redis DB ที่แยกไว้ (ค่าเริ่มต้น 13) — สคริปต์ปฏิเสธ
DB 0 (dev) และ DB 15 (ชุดเทส) · ไม่แตะ holdout ใดๆ

**เกณฑ์ผ่าน — กำหนดไว้ก่อนวัด (ห้ามปรับตามผล):**
  P1 steady state: ทุก (worker, concurrency) p95 <= 250 ms และ error = 0
  P2 fit storm   : ทุก process fit แต่ละคน <= 1 ครั้งตลอดการวัด (cold/warm/steady) ·
                   จบแล้วทุก process fit ครบ N_USERS คนพอดี · เห็นครบทุก worker ·
                   ช่วง steady ต้องไม่มี fit เพิ่ม
  โหลดทุกช่วงเปิด connection ใหม่ต่อ request — เหมือน hub ที่สร้าง AsyncClient ใหม่ทุกครั้ง
  P3 ความสอดคล้อง: input เดียวกัน -> score เท่ากันทุกครั้งทุก worker รวม cold กับ warm
  P4 หน่วยความจำ : RSS ต่อ process หลัง steady รอบ 3 โตจากรอบ 1 ไม่เกิน 5%
  (ข้อมูลประกอบ) cold latency และจำนวน request ที่เกิน 500 ms (เพดาน L3 ของ login)

    python -m scripts.ml_capacity_gate --url http://ml-cap:9000 --workers 2 \\
        --redis redis://redis:6379/13 --out /out/w2.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import sys
import time
from datetime import datetime, timezone

import httpx
import redis as redis_lib

P95_BUDGET_MS = 250.0
L3_DEADLINE_MS = 500.0
RSS_GROWTH_MAX = 0.05
CONCURRENCY = (1, 5, 10, 20)
FORBIDDEN_DBS = {0, 15}

DIMS = 6
HISTORY_ROWS = 2000  # MAX_HISTORY — ต้นทุน fit สูงสุด
N_USERS = 20
REQUESTS_PER_LEVEL = 400
STEADY_ROUNDS = 3
COLD_BURST = 20


def _db_index(url: str) -> int:
    tail = url.rstrip("/").rsplit("/", 1)[-1]
    return int(tail) if tail.isdigit() else 0


def pct(values: list[float], p: float) -> float:
    s = sorted(values)
    return s[min(int(p * len(s)), len(s) - 1)] if s else float("nan")


def summarize(lat: list[float], errors: int) -> dict:
    return {
        "n": len(lat),
        "errors": errors,
        "p50_ms": round(pct(lat, 0.50), 1),
        "p95_ms": round(pct(lat, 0.95), 1),
        "p99_ms": round(pct(lat, 0.99), 1),
        "max_ms": round(max(lat), 1) if lat else None,
        "mean_ms": round(statistics.fmean(lat), 1) if lat else None,
        "over_deadline": sum(1 for x in lat if x > L3_DEADLINE_MS),
    }


class Gate:
    def __init__(self, url: str, redis_url: str, workers: int, seed: int):
        self.url = url.rstrip("/")
        self.workers = workers
        self.rng = random.Random(seed)
        self.r = redis_lib.from_url(redis_url, decode_responses=True)
        self.users = [f"cap-user-{i:02d}" for i in range(N_USERS)]
        self.features: list[float] = []
        # probe คงที่สำหรับตรวจความสอดคล้อง: (user, residual)
        self.probes = [
            (u, [round(self.rng.gauss(0, 1), 6) for _ in range(DIMS)])
            for u in self.users
        ]

    # ── เตรียม ──────────────────────────────────────────────────────────────
    def seed_history(self) -> None:
        self.r.flushdb()
        for i, u in enumerate(self.users):
            rng = random.Random(1000 + i)
            key = f"l3resid:{u}"
            pipe = self.r.pipeline()
            for _ in range(HISTORY_ROWS):
                pipe.rpush(key, json.dumps([rng.gauss(0, 1) for _ in range(DIMS)]))
            pipe.execute()

    async def load_features(self, client: httpx.AsyncClient) -> None:
        info = (await client.get(f"{self.url}/v1/features-info")).json()["data"]
        names = [f["name"] if isinstance(f, dict) else f for f in info["features"]]
        vec = [0.0] * len(names)
        if "permission_change_age" in names:
            vec[names.index("permission_change_age")] = 365.0  # ค่ากลางตามสัญญา
        self.features = vec

    # ── เรียก ─────────────────────────────────────────────────────────────
    async def call(self, client, user, resid, *, spread: bool = False):
        """spread=True เปิด connection ใหม่ — ให้ request กระจายไปทุก worker.

        uvicorn หลาย worker แบ่งงานกันตอน accept connection · ถ้าใช้ keep-alive
        request ทั้งหมดบน connection เดียวจะไปลง worker เดิม
        """
        body = {
            "user_id": user,
            "features": self.features,
            "residual": resid,
            "access_decision": "allow",
        }
        headers = {"Connection": "close"} if spread else None
        t0 = time.perf_counter()
        try:
            r = await client.post(
                f"{self.url}/v1/l3-evaluate", json=body, headers=headers
            )
            ms = (time.perf_counter() - t0) * 1000
            if r.status_code != 200:
                return ms, None, f"http_{r.status_code}"
            return ms, r.json()["data"], None
        except Exception as e:  # noqa: BLE001
            return (time.perf_counter() - t0) * 1000, None, type(e).__name__

    async def stats(self, client) -> dict[int, dict]:
        """เรียกซ้ำจนเห็นครบทุก worker — รวมตาม pid."""
        seen: dict[int, dict] = {}
        for _ in range(60 * self.workers):
            # connection ใหม่ทุกครั้ง — keep-alive จะพาไป worker เดิมตลอด (บั๊กรอบแรก)
            r = await client.get(
                f"{self.url}/v1/l3-capacity-stats", headers={"Connection": "close"}
            )
            d = r.json()["data"]
            seen[d["pid"]] = d
            if len(seen) >= self.workers and _ >= 10 * self.workers:
                break
        return seen

    async def wait_ready(self, client, timeout_s: float = 60.0) -> int:
        """รอจนทุก worker ตอบ — health ผ่านจาก worker ตัวเดียวก็ได้ จึงไม่พอ.

        คืนจำนวน pid ที่เห็น (น้อยกว่า workers = หมดเวลา)
        """
        seen: set[int] = set()
        deadline = time.monotonic() + timeout_s
        while len(seen) < self.workers and time.monotonic() < deadline:
            try:
                r = await client.get(
                    f"{self.url}/v1/l3-capacity-stats", headers={"Connection": "close"}
                )
                seen.add(r.json()["data"]["pid"])
            except Exception:  # noqa: BLE001 — worker ยังไม่ขึ้น
                await asyncio.sleep(0.2)
        return len(seen)

    # ── ขั้นตอน ────────────────────────────────────────────────────────────
    async def cold_burst(self, client) -> dict:
        """COLD_BURST พร้อมกัน: ครึ่งหนึ่งคนเดียวกัน (probe 0) อีกครึ่งคนละคน."""
        same_u, same_r = self.probes[0]
        jobs = [(same_u, same_r)] * (COLD_BURST // 2) + self.probes[
            1 : 1 + COLD_BURST // 2
        ]
        res = await asyncio.gather(
            *(self.call(client, u, r, spread=True) for u, r in jobs)
        )
        lat = [ms for ms, _, _ in res]
        errors = [e for _, _, e in res if e]
        scores = {}
        for (u, r), (_, data, _) in zip(jobs, res):
            if data:
                scores.setdefault(_probe_key(u, r), set()).add(_score_of(data))
        return {
            "latency": summarize(lat, len(errors)),
            "error_kinds": sorted(set(errors)),
            "scores": {k: sorted(v) for k, v in scores.items()},
        }

    async def warm_until_stable(self, client) -> dict:
        prev_total, stable, rounds = -1, 0, 0
        while stable < 2 and rounds < 40:
            rounds += 1
            # ส่งซ้ำ workers ครั้งต่อคน บน connection ใหม่ — ให้ทุก worker ได้ fit ทุกคน
            await asyncio.gather(
                *(
                    self.call(client, u, r, spread=True)
                    for u, r in self.probes
                    for _ in range(self.workers)
                )
            )
            st = await self.stats(client)
            total = sum(s["fits_total"] for s in st.values())
            full = len(st) >= self.workers and all(
                s["cache_entries"] >= N_USERS for s in st.values()
            )
            stable = stable + 1 if (total == prev_total and full) else 0
            prev_total = total
        return {"rounds": rounds, "stable": stable >= 2, "fits_total": prev_total}

    async def steady(self, client, conc: int) -> dict:
        lat: list[float] = []
        errors: list[str] = []
        scores: dict[str, set] = {}
        queue = list(range(REQUESTS_PER_LEVEL))
        rng = random.Random(conc)

        async def worker():
            while queue:
                queue.pop()
                u, r = self.probes[rng.randrange(len(self.probes))]
                ms, data, err = await self.call(client, u, r, spread=True)
                lat.append(ms)
                if err:
                    errors.append(err)
                elif data:
                    scores.setdefault(_probe_key(u, r), set()).add(_score_of(data))

        await asyncio.gather(*(worker() for _ in range(conc)))
        return {
            "latency": summarize(lat, len(errors)),
            "error_kinds": sorted(set(errors)),
            "scores": {k: sorted(v) for k, v in scores.items()},
        }


def _probe_key(user: str, resid: list[float]) -> str:
    return f"{user}|{json.dumps(resid)}"


def _score_of(data: dict):
    """ค่าที่ต้องเท่ากันเมื่อ input เท่ากัน — คะแนนของโมเดลเท่านั้น.

    ไม่รวม duplicate_ratio / monitoring_decision เพราะขึ้นกับสถานะ `l3dup:` ใน Redis
    ที่เปลี่ยนตามการส่งซ้ำโดยออกแบบ (ไม่ใช่ race) · ถ้า sequence ไม่มีคะแนน (abstain)
    ถือว่า probe ใช้ไม่ได้ — เกณฑ์ P3 จะล้มถ้าไม่มี probe ที่มีคะแนนเลย
    """
    seq = data.get("sequence") or {}
    point = data.get("point") or {}
    return json.dumps(
        {
            "seq_score": seq.get("score"),
            "seq_raw": seq.get("raw_score"),
            "seq_percentile": seq.get("percentile"),
            "seq_n_history": seq.get("n_history"),
            "seq_eligibility": seq.get("eligibility"),
            "point_score": point.get("anomaly_score"),
        },
        sort_keys=True,
    )


def _merge_scores(*maps: dict) -> dict[str, set]:
    out: dict[str, set] = {}
    for m in maps:
        for k, v in m.items():
            out.setdefault(k, set()).update(v)
    return out


async def run(a) -> dict:
    gate = Gate(a.url, a.redis, a.workers, a.seed)
    if _db_index(a.redis) in FORBIDDEN_DBS:
        raise SystemExit(f"ปฏิเสธ Redis DB {_db_index(a.redis)} — ใช้ DB แยก (เช่น 13)")
    limits = httpx.Limits(max_connections=64, max_keepalive_connections=64)
    async with httpx.AsyncClient(timeout=30.0, limits=limits) as client:
        await gate.load_features(client)
        if not a.skip_seed:
            gate.seed_history()
        ready = await gate.wait_ready(client)
        if ready < gate.workers:
            raise SystemExit(f"worker ตอบแค่ {ready}/{gate.workers} ภายใน 60 วินาที")
        started = time.perf_counter()
        cold = await gate.cold_burst(client)
        cold_stats = await gate.stats(client)
        warm = await gate.warm_until_stable(client)
        warm_stats = await gate.stats(client)

        rounds = []
        for i in range(STEADY_ROUNDS):
            levels = {}
            for c in CONCURRENCY:
                levels[str(c)] = await gate.steady(client, c)
            rounds.append({"levels": levels, "stats": await gate.stats(client)})

    return evaluate(
        a.workers,
        cold,
        cold_stats,
        warm,
        warm_stats,
        rounds,
        time.perf_counter() - started,
    )


def _point_shap_mode(stats: dict):
    """True/False เมื่อทุก worker รายงานตรงกัน · None = ไม่รู้หรือไม่ตรงกัน."""
    modes = {s.get("point_shap") for s in stats.values()}
    return modes.pop() if len(modes) == 1 and None not in modes else None


def load_share(before: dict, after: dict) -> dict:
    """request ของช่วง steady ที่แต่ละ worker ได้ — ข้อมูลประกอบ ไม่ใช่เกณฑ์ผ่าน.

    max_over_mean = งานของ worker ที่ได้มากสุด / ค่าเฉลี่ย · 1.0 = เท่ากันพอดี
    """
    per = {}
    for pid, s in after.items():
        a1 = s.get("l3_requests")
        a0 = (before.get(pid) or {}).get("l3_requests")
        if a1 is None or a0 is None:
            return {"per_process": None, "max_over_mean": None}
        per[str(pid)] = a1 - a0
    mean = sum(per.values()) / len(per) if per else 0
    return {
        "per_process": per,
        "max_over_mean": round(max(per.values()) / mean, 3) if mean else None,
    }


def evaluate(workers, cold, cold_stats, warm, warm_stats, rounds, elapsed) -> dict:
    checks = {}

    # P1
    worst = {}
    for c in CONCURRENCY:
        p95s = [r["levels"][str(c)]["latency"]["p95_ms"] for r in rounds]
        errs = sum(r["levels"][str(c)]["latency"]["errors"] for r in rounds)
        worst[str(c)] = {
            "p95_ms_worst": max(p95s),
            "p95_ms_rounds": p95s,
            "errors": errs,
        }
    checks["P1_steady_p95"] = {
        "pass": all(
            v["p95_ms_worst"] <= P95_BUDGET_MS and v["errors"] == 0
            for v in worst.values()
        ),
        "by_concurrency": worst,
        "budget_ms": P95_BUDGET_MS,
    }

    # P2 — ประวัติไม่โตระหว่างวัด (ตัววัดไม่เขียน residual) และ TTL 1 ชม. จึงต้อง fit
    # คนละครั้งต่อ process พอดี: ทุก process มี max_fits_per_user == 1 และ
    # fits_total == N_USERS ตั้งแต่ warm จนจบ steady
    final = rounds[-1]["stats"]
    per_proc_max = max(
        (
            s["max_fits_per_user"]
            for st in (cold_stats, warm_stats, final)
            for s in st.values()
        ),
        default=0,
    )
    fits_after_warm = sum(s["fits_total"] for s in warm_stats.values())
    fits_after_steady = sum(s["fits_total"] for s in final.values())
    exact = all(s["fits_total"] == N_USERS for s in final.values())
    checks["P2_fit_storm"] = {
        "pass": per_proc_max <= 1
        and exact
        and len(final) == workers
        and fits_after_steady == fits_after_warm
        and warm["stable"],
        "max_fits_per_user_per_process": per_proc_max,
        "processes_seen": len(final),
        "fits_per_process_final": {str(p): s["fits_total"] for p, s in final.items()},
        "expected_fits_per_process": N_USERS,
        "fits_after_warm": fits_after_warm,
        "fits_after_steady": fits_after_steady,
        "warm": warm,
    }

    # P3
    merged = _merge_scores(
        cold["scores"], *(lvl["scores"] for r in rounds for lvl in r["levels"].values())
    )
    disagree = {k: sorted(v) for k, v in merged.items() if len(v) > 1}
    # probe ที่ sequence abstain ไม่ได้พิสูจน์อะไร — ต้องมีคะแนนจริงทุกตัว
    unscored = sorted(
        k
        for k, v in merged.items()
        if any(json.loads(s)["seq_score"] is None for s in v)
    )
    checks["P3_score_agreement"] = {
        "pass": not disagree and not unscored and len(merged) == N_USERS,
        "probes_checked": len(merged),
        "probes_expected": N_USERS,
        "unscored_probes": unscored,
        "disagreements": disagree,
    }

    # P4
    rss = {}
    first, last = rounds[0]["stats"], rounds[-1]["stats"]
    for pid, s in last.items():
        a0 = (first.get(pid) or {}).get("rss_kb")
        a1 = s.get("rss_kb")
        rss[str(pid)] = {
            "round1_kb": a0,
            "round3_kb": a1,
            "growth": None if not a0 or not a1 else round((a1 - a0) / a0, 4),
        }
    growths = [v["growth"] for v in rss.values() if v["growth"] is not None]
    checks["P4_memory"] = {
        "pass": bool(growths)
        and len(growths) == workers
        and all(g <= RSS_GROWTH_MAX for g in growths),
        "per_process": rss,
        "total_rss_mb_round3": round(
            sum((s.get("rss_kb") or 0) for s in last.values()) / 1024, 1
        ),
        "max_growth": RSS_GROWTH_MAX,
    }

    return {
        "workers": workers,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "elapsed_s": round(elapsed, 1),
        "passed": all(c["pass"] for c in checks.values()),
        "checks": checks,
        "load_share": load_share(warm_stats, rounds[-1]["stats"]),
        "point_shap": _point_shap_mode(rounds[-1]["stats"]),
        "cold_burst": {k: v for k, v in cold.items() if k != "scores"},
        "rounds": [
            {c: lvl["latency"] for c, lvl in r["levels"].items()} for r in rounds
        ],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--redis", required=True)
    ap.add_argument("--workers", type=int, required=True)
    ap.add_argument("--seed", type=int, default=20260921)
    ap.add_argument("--skip-seed", action="store_true")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    result = asyncio.run(run(a))
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    print(
        json.dumps(
            {
                "workers": a.workers,
                "passed": result["passed"],
                **{k: v["pass"] for k, v in result["checks"].items()},
            }
        )
    )
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
