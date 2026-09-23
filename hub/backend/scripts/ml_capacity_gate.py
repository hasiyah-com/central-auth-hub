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
import itertools
import json
import math
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

# ── เกณฑ์ช่วงเย็นแบบ open-loop (§15 — กำหนดก่อนวัด) ──
# ml-service เพิ่ง start · 400 คนที่มีประวัติ 2,000 แถวและยังไม่มีใครมีโมเดล · ยิงแบบ Poisson
# 60 login/วินาที 60 วินาที · 400 arrival แรกเป็นคนละคนทั้งหมด (กรณีแย่สุดหลัง restart)
COLD_RATE = 60.0
COLD_SECONDS = 60.0
COLD_USERS = 400
COLD_OVER_DEADLINE_MAX = 0.01  # เกิน 500 ms ได้ไม่เกิน 1%
COLD_BUCKET_S = 5.0
WARMING_REASON = "model_warming"
# ml-service จำกัดคำขอ L3 ค้างพร้อมกันต่อผู้ใช้ (§25) — ไม่มีคะแนน ไม่ใช่ warming
OVERLOAD_REASON = "per_user_overload"
# §25 hot-user protection — เขียนก่อนวัด
HOT_OTHERS_OVERLOAD_MAX = 0.01  # ผู้ใช้อื่นในกรณีผสมถูกจำกัดได้ไม่เกิน 1% ของ request
HOT_MIN_RUNS = 10

# ── P1 v3 (§23 — กำหนดก่อนวัด) ──
# steady บนผู้ใช้ชุด cold 400 คน (อุ่นแล้ว) แทนชุด cap 20 คนที่ hash เอียง 3/9/4/4 ใน §21
# เกณฑ์ตัดสินใช้ของ P1 v2 เดิมทุกตัว (P95_BUDGET_MS, P1_V2_*) — ห้ามแก้ย้อนหลัง
V3_USERS = COLD_USERS
V3_ROUNDS = 3
V3_HOT_CONCURRENCY = 20  # ผู้ใช้คนเดียวยิงพร้อมกัน 20 — กรณี hot user
V3_MIN_RUNS = 10


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
    def __init__(
        self,
        url: str,
        redis_url: str,
        workers: int,
        seed: int,
        high_score_share: float = 0.0,
    ):
        if not 0.0 <= high_score_share <= 1.0:
            raise ValueError(f"high_score_share ต้องอยู่ใน 0–1 (ได้ {high_score_share})")
        self.high_score_share = high_score_share
        self.normal_features: list[float] = []
        self.probe_features: list[list[float]] = []
        self._features_by_user: dict[str, list[float]] = {}
        self.cold_users: list[str] = []
        # L3 แยกตามผู้ใช้ (§20) — None = ส่งทุกคนไป self.url แบบเดิม
        self.shard_base_port: int | None = None
        self.shard_count = 0
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

    def seed_cold_users(self, n: int = COLD_USERS) -> None:
        """ผู้ใช้ชุดแยกสำหรับวัดช่วงเย็น — ประวัติเต็ม 2,000 แถว (ต้นทุน fit สูงสุด)."""
        self.cold_users = [f"cold-user-{i:04d}" for i in range(n)]
        for i, u in enumerate(self.cold_users):
            rng = random.Random(50_000 + i)
            pipe = self.r.pipeline()
            for _ in range(HISTORY_ROWS):
                row = [rng.gauss(0, 1) for _ in range(DIMS)]
                pipe.rpush(f"l3resid:{u}", json.dumps(row))
            pipe.execute()

    async def load_features(self, client: httpx.AsyncClient) -> None:
        info = (await client.get(f"{self.url}/v1/features-info")).json()["data"]
        self.set_feature_names(
            [f["name"] if isinstance(f, dict) else f for f in info["features"]]
        )

    def set_feature_names(self, names: list[str]) -> None:
        """feature สองชุด: ปกติ (point score ~0.41) และผิดปกติ (~0.52 · >= เกณฑ์ SHAP 0.50).

        SHAP ของ point view คำนวณเฉพาะคะแนน >= 0.50 (§12) — ใช้ชุดปกติอย่างเดียวจะข้าม
        SHAP ทุก request = วัดผิดสิ่ง · probe แรก `round(share × N_USERS)` ตัวใช้ชุดผิดปกติ
        feature ของแต่ละ probe คงที่ตลอดการวัด (P3 เทียบคะแนนต่อ probe)
        """
        normal = [0.0] * len(names)
        if "permission_change_age" in names:
            normal[names.index("permission_change_age")] = 365.0  # ค่ากลางตามสัญญา
        high = list(normal)
        for name, value in (
            ("is_new_country", 1.0),
            ("is_new_device", 1.0),
            ("failed_logins_24h", 5.0),
            ("is_thailand", 0.0),
        ):
            if name in names:
                high[names.index(name)] = value
        n_high = round(self.high_score_share * N_USERS)
        self.normal_features = normal
        self.features = normal
        self.probe_features = [high if i < n_high else normal for i in range(N_USERS)]
        self._features_by_user = {
            u: f for (u, _), f in zip(self.probes, self.probe_features)
        }

    # ── เรียก ─────────────────────────────────────────────────────────────
    def url_for(self, user: str) -> str:
        """URL ของ L3 สำหรับผู้ใช้คนนี้ — ใช้ shard_index ตัวเดียวกับ hub (B66: วัดสิ่งที่ deploy)."""
        if not self.shard_base_port or self.shard_count < 1:
            return self.url
        from urllib.parse import urlsplit

        from app.services.l3_sequence_client import shard_index

        parts = urlsplit(self.url)
        port = self.shard_base_port + shard_index(user, self.shard_count)
        return f"{parts.scheme}://{parts.hostname}:{port}"

    async def call(self, client, user, resid, *, spread: bool = False):
        """spread=True เปิด connection ใหม่ — ให้ request กระจายไปทุก worker.

        uvicorn หลาย worker แบ่งงานกันตอน accept connection · ถ้าใช้ keep-alive
        request ทั้งหมดบน connection เดียวจะไปลง worker เดิม
        """
        body = {
            "user_id": user,
            "features": self._features_by_user.get(user, self.features),
            "residual": resid,
            "access_decision": "allow",
        }
        headers = {"Connection": "close"} if spread else None
        t0 = time.perf_counter()
        try:
            r = await client.post(
                f"{self.url_for(user)}/v1/l3-evaluate", json=body, headers=headers
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

    async def wait_fits_idle(self, client, timeout_s: float = 600.0) -> bool:
        """รอจนทุก worker ไม่มี fit ค้าง (fits_pending = 0 สองครั้งติด)."""
        deadline = time.monotonic() + timeout_s
        quiet = 0
        while time.monotonic() < deadline:
            st = await self.stats(client)
            busy = sum(int(s.get("fits_pending") or 0) for s in st.values())
            quiet = quiet + 1 if busy == 0 and len(st) >= self.workers else 0
            if quiet >= 2:
                return True
            await asyncio.sleep(1.0)
        return False

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
        warming = overload = 0
        for (u, r), (_, data, _) in zip(jobs, res):
            if data and _is_overload(data):
                overload += 1  # ถูกจำกัดต่อผู้ใช้ (§25) — ไม่มีคะแนน
            elif data and _is_warming(data):
                warming += 1  # ไม่มีคะแนน — ไม่เข้าการเทียบ P3 (§15)
            elif data:
                scores.setdefault(_probe_key(u, r), set()).add(_score_of(data))
        return {
            "latency": summarize(lat, len(errors)),
            "error_kinds": sorted(set(errors)),
            "scores": {k: sorted(v) for k, v in scores.items()},
            "warming": warming,
            "overload": overload,
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

    def v3_probes(self) -> list[tuple[str, list[float]]]:
        """probe คงที่ต่อผู้ใช้ชุด cold — residual เดิมทุกครั้ง (P3 เทียบคะแนนต่อ probe ได้)."""
        out = []
        for i, u in enumerate(self.cold_users[:V3_USERS]):
            rng = random.Random(70_000 + i)
            out.append((u, [round(rng.gauss(0, 1), 6) for _ in range(DIMS)]))
        return out

    async def steady(self, client, conc: int, probes=None) -> dict:
        lat: list[float] = []
        served: list[float] = []  # ไม่รวมคำตอบที่ถูกจำกัด — ข้อมูลประกอบ (§25)
        errors: list[str] = []
        scores: dict[str, set] = {}
        queue = list(range(REQUESTS_PER_LEVEL))
        rng = random.Random(conc)
        pool = probes if probes is not None else self.probes

        async def worker():
            while queue:
                queue.pop()
                u, r = pool[rng.randrange(len(pool))]
                ms, data, err = await self.call(client, u, r, spread=True)
                lat.append(ms)
                if err:
                    errors.append(err)
                elif data and _is_overload(data):
                    overload[0] += 1
                    continue
                elif data and _is_warming(data):
                    warming[0] += 1
                elif data:
                    scores.setdefault(_probe_key(u, r), set()).add(_score_of(data))
                served.append(ms)

        warming = [0]
        overload = [0]
        await asyncio.gather(*(worker() for _ in range(conc)))
        return {
            "latency": summarize(lat, len(errors)),
            "error_kinds": sorted(set(errors)),
            "scores": {k: sorted(v) for k, v in scores.items()},
            "raw_ms": lat,  # ใช้รวม p95 ข้ามรอบ (วิธีวัด v2) — ไม่เขียนลงผล
            "warming": warming[0],
            "overload": overload[0],
            "served_latency": summarize(served, 0),
        }

    async def cold_open_loop(
        self, client, rate: float, seconds: float, seed: int
    ) -> dict:
        """ช่วงเย็นแบบ open-loop — ผู้ใช้ชุด `cold_users` ที่ยังไม่มีใครมีโมเดล (§15)."""
        times = arrival_times(rate, seconds, seed)
        order = cold_user_order(len(self.cold_users), len(times))
        n_high = round(self.high_score_share * len(self.cold_users))
        high = self.probe_features[0] if self.probe_features else self.features
        normal = self.normal_features or self.features
        for idx, user in enumerate(self.cold_users):
            self._features_by_user[user] = high if idx < n_high else normal
        rng = random.Random(seed)
        records: list[tuple[float, float, bool, str | None]] = []
        timeline: list[tuple[str, float, float, bool]] = []  # C3
        lag: list[float] = []
        overload = [0]
        start = time.perf_counter()

        async def fire(at, user, resid):
            ms, data, err = await self.call(client, user, resid, spread=True)
            warming = bool(data) and _is_warming(data)
            if data and _is_overload(data):
                overload[0] += 1  # ไม่ใช่ทั้งคะแนนและ warming — ไม่เข้า C3 (§25)
                records.append((at, ms, False, err))
                return
            records.append((at, ms, warming, err))
            if data and not err:
                done = time.perf_counter() - start
                timeline.append((user, at, done, warming))

        tasks = []
        for at, idx in zip(times, order):
            delay = at - (time.perf_counter() - start)
            if delay > 0:
                await asyncio.sleep(delay)
            lag.append(max(0.0, (time.perf_counter() - start) - at) * 1000)
            resid = [round(rng.gauss(0, 1), 6) for _ in range(DIMS)]
            tasks.append(asyncio.create_task(fire(at, self.cold_users[idx], resid)))
        await asyncio.gather(*tasks)

        lat = [r[1] for r in records]
        errors = [r[3] for r in records if r[3]]
        warming = sum(1 for r in records if r[2])
        buckets = []
        for b in range(max(1, math.ceil(seconds / COLD_BUCKET_S))):
            lo, hi = b * COLD_BUCKET_S, (b + 1) * COLD_BUCKET_S
            rows = [r for r in records if lo <= r[0] < hi]
            if not rows:
                continue
            buckets.append(
                {
                    "from_s": lo,
                    "n": len(rows),
                    "warming_share": round(sum(1 for r in rows if r[2]) / len(rows), 4),
                    "p95_ms": round(pct([r[1] for r in rows], 0.95), 1),
                }
            )
        warm_at = next(
            (b["from_s"] for b in buckets if b["warming_share"] < 0.05), None
        )
        return {
            "rate": rate,
            "seconds": seconds,
            "users": len(self.cold_users),
            "offered": len(times),
            "latency": summarize(lat, len(errors)),
            "error_kinds": sorted(set(errors)),
            "warming": warming,
            "overload": overload[0],
            "warming_share": round(warming / len(records), 4) if records else 0.0,
            "time_to_warm_s": warm_at,
            "buckets": buckets,
            "max_schedule_lag_ms": round(max(lag), 1) if lag else 0.0,
            "consistency_violations": consistency_violations(timeline),
        }

    async def open_loop(self, client, rate: float, seconds: float, seed: int) -> dict:
        """ยิงตามเวลาที่กำหนด (Poisson) ไม่รอคำตอบก่อนยิงตัวถัดไป — ใกล้ traffic จริงกว่า
        closed-loop ที่ concurrency คงที่ · ใช้ประกอบการทบทวนเกณฑ์ (รายงาน §13)."""
        times = arrival_times(rate, seconds, seed)
        rng = random.Random(seed)
        lat: list[float] = []
        errors: list[str] = []
        lag: list[float] = []
        start = time.perf_counter()

        async def fire(u, r):
            ms, _, err = await self.call(client, u, r, spread=True)
            lat.append(ms)
            if err:
                errors.append(err)

        tasks = []
        for at in times:
            delay = at - (time.perf_counter() - start)
            if delay > 0:
                await asyncio.sleep(delay)
            lag.append(max(0.0, (time.perf_counter() - start) - at) * 1000)
            u, r = self.probes[rng.randrange(len(self.probes))]
            tasks.append(asyncio.create_task(fire(u, r)))
        await asyncio.gather(*tasks)
        return {
            "rate": rate,
            "seconds": seconds,
            "offered": len(times),
            "latency": summarize(lat, len(errors)),
            "error_kinds": sorted(set(errors)),
            "max_schedule_lag_ms": round(max(lag), 1) if lag else 0.0,
        }


def _is_warming(data: dict) -> bool:
    return (data.get("sequence") or {}).get("abstain_reason") == WARMING_REASON


def _is_overload(data: dict) -> bool:
    return (data.get("sequence") or {}).get("abstain_reason") == OVERLOAD_REASON


def _read(path: str):
    try:
        with open(path, encoding="ascii") as f:
            return f.read()
    except OSError:
        return None


def parse_host(proc_stat, loadavg, meminfo):
    """สถานะของเครื่อง (Docker VM) จาก /proc — None เมื่ออ่านไม่ได้ (เช่นรันบน Windows).

    ตัววัดรันในคอนเทนเนอร์ /proc/stat จึงเป็นของทั้ง VM ที่ ml-service ใช้ร่วม (§27)
    """
    try:
        first = proc_stat.splitlines()[0].split()
        if first[0] != "cpu":
            return None
        user, nice, system, idle, iowait, irq, softirq, steal = (
            int(x) for x in first[1:9]
        )
        load1 = float(loadavg.split()[0])
        avail = next(
            int(line.split()[1])
            for line in meminfo.splitlines()
            if line.startswith("MemAvailable:")
        )
    except (AttributeError, IndexError, ValueError, StopIteration):
        return None
    return {
        "total": user + nice + system + idle + iowait + irq + softirq + steal,
        "idle": idle + iowait,
        "steal": steal,
        "load1": load1,
        "mem_available_kb": avail,
    }


def read_host():
    return parse_host(
        _read("/proc/stat"), _read("/proc/loadavg"), _read("/proc/meminfo")
    )


def host_delta(a, b):
    """สัดส่วน CPU ของ VM ที่ไม่ว่าง (ไม่รวม steal) และ steal ในช่วงระหว่างสอง snapshot."""
    if not a or not b:
        return None
    total = b["total"] - a["total"]
    if total <= 0:
        return None
    idle = b["idle"] - a["idle"]
    steal = b["steal"] - a["steal"]
    return {
        "busy_share": round((total - idle - steal) / total, 4),
        "steal_share": round(steal / total, 4),
        "load1": b["load1"],
        "mem_available_kb": b["mem_available_kb"],
    }


def phase_record(before: dict, after: dict, host_a, host_b, seconds: float) -> dict:
    """ตัวเลขของหนึ่งช่วง (§27) — นับเฉพาะ worker ที่เห็นทั้งก่อนและหลัง (รู้ฐาน)."""
    pids = sorted(set(before) & set(after))
    reqs, utils, cpu_total, overload = [], [], 0.0, 0
    cpu_known = bool(pids)
    over_known = bool(pids)
    for pid in pids:
        a, b = before[pid], after[pid]
        reqs.append(int(b.get("l3_requests") or 0) - int(a.get("l3_requests") or 0))
        if b.get("per_user_overload") is None or a.get("per_user_overload") is None:
            over_known = False
        else:
            overload += int(b["per_user_overload"]) - int(a["per_user_overload"])
        if None in (a.get("cpu_s"), b.get("cpu_s"), a.get("mono_s"), b.get("mono_s")):
            cpu_known = False
            continue
        cpu = float(b["cpu_s"]) - float(a["cpu_s"])
        wall = float(b["mono_s"]) - float(a["mono_s"])
        cpu_total += cpu
        utils.append(round(cpu / wall, 4) if wall > 0 else None)
    total_req = sum(reqs)
    mean = total_req / len(reqs) if reqs else 0
    return {
        "seconds": round(seconds, 2),
        "workers_compared": len(pids),
        "requests": total_req,
        "requests_per_worker": sorted(reqs),
        "max_over_mean": round(max(reqs) / mean, 3) if mean else None,
        "overload": overload if over_known else None,
        "cpu_util_per_worker": sorted(u for u in utils if u is not None)
        if cpu_known
        else None,
        "cpu_ms_per_request": (
            round(cpu_total * 1000 / total_req, 3) if cpu_known and total_req else None
        ),
        "rss_kb_max": max(
            (int(after[p].get("rss_kb") or 0) for p in pids), default=None
        ),
        "host": host_delta(host_a, host_b),
    }


class _Phase:
    """จับ stats + host + เวลา ที่ต้นและปลายช่วง."""

    def __init__(self, gate: "Gate", client):
        self.gate, self.client = gate, client

    async def start(self):
        self.t0 = time.perf_counter()
        self.host0 = read_host()
        self.s0 = await self.gate.stats(self.client)
        return self

    async def stop(self) -> dict:
        s1 = await self.gate.stats(self.client)
        host1 = read_host()
        return phase_record(
            self.s0, s1, self.host0, host1, time.perf_counter() - self.t0
        )


def overload_delta(before: dict, after: dict):
    """จำนวนครั้งที่ตัวจำกัดต่อผู้ใช้ทำงานระหว่างสองจุด รวมทุก worker · None = ไม่มีตัวนับ."""
    total, known = 0, False
    for pid, s in after.items():
        a1 = s.get("per_user_overload")
        if a1 is None:
            continue
        known = True
        total += int(a1) - int((before.get(pid) or {}).get("per_user_overload") or 0)
    return total if known else None


def hot_user_summary(runs: list[dict]) -> dict:
    """ตัดสิน hot-user protection ตาม §25 (เขียนก่อนวัด).

    ผู้ใช้อื่นในกรณีผสม: กฎ P1 v2 เดิม (median p95 <= 225 และ >= 9/10 ครั้ง <= 250) · error = 0 ·
    ถูกจำกัด <= 1% ของ request ทุกครั้ง · ตัวจำกัดต้องทำงานจริง (> 0) ทุกครั้ง (บทเรียน B61)
    """
    p95s, clean, fired = [], True, True
    for r in runs:
        v3 = r.get("p1_v3") or {}
        others = v3.get("mixed_others") or {}
        lat = others.get("latency") or {}
        p95s.append(lat.get("p95_ms"))
        n = lat.get("n") or 0
        if lat.get("errors") != 0 or not n:
            clean = False
        elif (others.get("overload") or 0) > HOT_OTHERS_OVERLOAD_MAX * n:
            clean = False
        if not (v3.get("per_user_overload_fired") or 0) > 0:
            fired = False
    enough = len(runs) >= HOT_MIN_RUNS
    p95_ok = enough and None not in p95s and p1_v2_pass(p95s)
    return {
        "runs": len(runs),
        "enough_runs": enough,
        "others_p95": p95s,
        "others_p95_pass": p95_ok,
        "others_clean": clean,
        "limiter_fired": fired,
        "passed": bool(p95_ok and clean and fired),
    }


def wait_outcomes(stats: dict) -> dict:
    """cache miss ที่รอแล้วได้คะแนน เทียบกับที่ตอบ model_warming — รวมทุก worker (§17)."""
    scored = warming = 0
    known = False
    for s in stats.values():
        if "fit_wait_scored" in s:
            known = True
        scored += int(s.get("fit_wait_scored") or 0)
        warming += int(s.get("warming_responses") or 0)
    total = scored + warming
    return {
        "scored_after_wait": scored,
        "warming": warming,
        "scored_share": round(scored / total, 4) if known and total else None,
    }


def consistency_violations(records) -> int:
    """C3 (§20): นับคำตอบ model_warming ที่มาถึง**หลัง**คะแนนจริงครั้งแรกของผู้ใช้คนนั้นเสร็จ.

    record = (user, arrival_s, done_s, warming) · request ที่มาก่อนคะแนนแรกเสร็จไม่นับ
    (ยังไม่มีทางรู้ว่าโมเดลพร้อม) · แบ่ง worker ตามผู้ใช้แล้วค่านี้ต้องเป็น 0
    """
    first_scored_done: dict[str, float] = {}
    for user, _at, done, warming in records:
        if not warming:
            prev = first_scored_done.get(user)
            first_scored_done[user] = done if prev is None else min(prev, done)
    return sum(
        1
        for user, at, _done, warming in records
        if warming and user in first_scored_done and at > first_scored_done[user]
    )


def cold_user_order(n_users: int, n_arrivals: int) -> list[int]:
    """ลำดับผู้ใช้ของ arrival — n_users ตัวแรกเป็นคนละคนทั้งหมด แล้ววนซ้ำ."""
    return [i % n_users for i in range(n_arrivals)]


def p1_v3_summary(runs: list[dict]) -> dict:
    """ตัดสิน P1 v3 ตาม §23: กฎของ P1 v2 เดิมทุกระดับ + C3 = 0 ทุกครั้ง + ต้องมี ≥ 10 ครั้ง."""
    per_level: dict[str, list[float]] = {}
    c3_ok = True
    shares = []
    for r in runs:
        v3 = r.get("p1_v3") or {}
        for lvl, s in (v3.get("pooled") or {}).items():
            per_level.setdefault(lvl, []).append(s["p95_ms"])
        if (r.get("cold_open_loop") or {}).get("consistency_violations") != 0:
            c3_ok = False
        if v3.get("warming_after_warm") != 0:
            c3_ok = False
        shares.append((v3.get("load_share") or {}).get("max_over_mean"))
    enough = len(runs) >= V3_MIN_RUNS
    p1 = enough and bool(per_level) and all(p1_v2_pass(v) for v in per_level.values())
    return {
        "runs": len(runs),
        "enough_runs": enough,
        "per_run_p95": per_level,
        "median_p95": {k: statistics.median(v) for k, v in per_level.items()},
        "p1_pass": p1,
        "c3_pass": c3_ok and enough,
        "load_share_max_over_mean": shares,
        "passed": p1 and c3_ok and enough,
    }


def cold_pass(result: dict) -> bool:
    """เกณฑ์ช่วงเย็น (§15): p95 <= 250 ms · error = 0 · เกิน 500 ms <= 1%."""
    lat = result["latency"]
    n = lat.get("n") or 0
    over = (lat.get("over_deadline") or 0) / n if n else 1.0
    return (
        lat["p95_ms"] <= P95_BUDGET_MS
        and lat["errors"] == 0
        and over <= COLD_OVER_DEADLINE_MAX
    )


def arrival_times(rate: float, seconds: float, seed: int) -> list[float]:
    """เวลายิง (วินาทีนับจากเริ่ม) แบบ Poisson — seed เดียวกันได้ชุดเดียวกัน."""
    rng = random.Random(seed)
    out, t = [], 0.0
    while True:
        t += rng.expovariate(rate)
        if t >= seconds:
            return out
        out.append(t)


def pool_levels(raw_rounds: list[dict]) -> dict:
    """p95 ของทุก request ในทุกรอบ ต่อระดับ concurrency (วิธีวัด v2)."""
    merged: dict[str, list[float]] = {}
    for rnd in raw_rounds:
        for lvl, values in rnd.items():
            merged.setdefault(lvl, []).extend(values)
    return {lvl: summarize(values, 0) for lvl, values in merged.items()}


def permutation_p_value(a: list[float], b: list[float]) -> float:
    """permutation test แบบ exact สองทาง บนผลต่างของค่าเฉลี่ย.

    ไม่สมมติรูปการแจกแจง · 10 ต่อ 10 = 184,756 แบบ (รันได้ในไม่กี่วินาที)
    """
    pooled = list(a) + list(b)
    n, total = len(a), sum(pooled)
    observed = abs(sum(a) / n - sum(b) / len(b))
    hits = count = 0
    for idx in itertools.combinations(range(len(pooled)), n):
        s = sum(pooled[i] for i in idx)
        diff = abs(s / n - (total - s) / len(b))
        hits += diff >= observed - 1e-12
        count += 1
    return hits / count


P1_V2_MEDIAN_MAX_MS = 225.0  # ส่วนเผื่อ 10% จากเพดาน 250
P1_V2_RUN_SHARE = 0.9  # อย่างน้อย 9 ใน 10 ครั้งต้อง <= เพดาน


def p1_v2_pass(per_run_p95: list[float]) -> bool:
    """P1 v2 (กำหนดก่อนวัด): median ของ p95 รวมต่อครั้ง <= 225 ms และอย่างน้อย 90%
    ของครั้ง <= 250 ms."""
    if not per_run_p95:
        return False
    within = sum(1 for v in per_run_p95 if v <= P95_BUDGET_MS)
    return statistics.median(
        per_run_p95
    ) <= P1_V2_MEDIAN_MAX_MS and within >= math.ceil(P1_V2_RUN_SHARE * len(per_run_p95))


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
    if a.p1_v3 and not a.cold_open_loop:
        raise SystemExit("--p1-v3 ต้องใช้คู่ --cold-open-loop (ใช้ผู้ใช้ชุด cold 400 คน)")
    gate = Gate(a.url, a.redis, a.workers, a.seed, high_score_share=a.high_score_share)
    if a.shard_base_port:
        gate.shard_base_port = a.shard_base_port
        gate.shard_count = a.workers
    if _db_index(a.redis) in FORBIDDEN_DBS:
        raise SystemExit(f"ปฏิเสธ Redis DB {_db_index(a.redis)} — ใช้ DB แยก (เช่น 13)")
    limits = httpx.Limits(max_connections=64, max_keepalive_connections=64)
    async with httpx.AsyncClient(timeout=30.0, limits=limits) as client:
        await gate.load_features(client)
        if not a.skip_seed:
            gate.seed_history()
        cold_open = None
        fit_baseline = None
        p1_v3 = None
        if a.cold_open_loop:
            gate.seed_cold_users()
        ready = await gate.wait_ready(client)
        if ready < gate.workers:
            raise SystemExit(f"worker ตอบแค่ {ready}/{gate.workers} ภายใน 60 วินาที")
        phases: dict = {}
        if a.cold_open_loop:  # ต้องมาก่อนทุกอย่าง — ยังไม่มีใครมีโมเดล
            ph = await _Phase(gate, client).start()
            cold_open = await gate.cold_open_loop(
                client, COLD_RATE, COLD_SECONDS, a.seed
            )
            phases["cold"] = await ph.stop()
            cold_open["passed"] = cold_pass(cold_open)
            # ให้ fit ของช่วงเย็นจบก่อน แล้วเก็บเป็นฐานของ P2
            await gate.wait_fits_idle(client)
            after_cold = await gate.stats(client)
            fit_baseline = {pid: s["fits_total"] for pid, s in after_cold.items()}
            cold_open["wait_outcomes"] = wait_outcomes(after_cold)
            if a.p1_v3:
                p1_v3 = await run_p1_v3(gate, client)
                # ฐานของ P2 ต้องนับหลัง v3 (v3 fit ผู้ใช้ชุด cold ที่ยังไม่ครบ)
                fit_baseline = {
                    pid: s["fits_total"]
                    for pid, s in (await gate.stats(client)).items()
                }
        started = time.perf_counter()
        ph_cap = await _Phase(gate, client).start()
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
        phases["cap"] = await ph_cap.stop()

        open_loop = []
        for rate in a.open_loop_rates:
            open_loop.append(
                await gate.open_loop(client, rate, a.open_loop_seconds, a.seed)
            )

    result = evaluate(
        a.workers,
        cold,
        cold_stats,
        warm,
        warm_stats,
        rounds,
        time.perf_counter() - started,
        fit_baseline=fit_baseline,
        shard_mode=bool(a.shard_base_port),
    )
    result["high_score_share"] = gate.high_score_share
    result["shard_base_port"] = a.shard_base_port
    result["pooled"] = pool_levels(
        [{c: lvl["raw_ms"] for c, lvl in r["levels"].items()} for r in rounds]
    )
    result["open_loop"] = open_loop
    result["cold_open_loop"] = cold_open
    result["p1_v3"] = p1_v3
    result["phases"] = phases
    result["cold_burst_passed"] = cold_pass({"latency": cold["latency"]})
    result["wait_outcomes_total"] = wait_outcomes(rounds[-1]["stats"])
    return result


async def run_p1_v3(gate: "Gate", client) -> dict:
    """steady บนผู้ใช้ชุด cold ทั้ง 400 คน + hot user (§23).

    1) อุ่นทุกคน (ส่งครบทุกคนจนไม่มี warming) 2) steady V3_ROUNDS × CONCURRENCY
    3) สัดส่วนงานของทุก worker 4) hot user: คนเดียว c=20 · ผสม: hot c=10 + คนอื่น c=10
    """
    probes = gate.v3_probes()
    warm_passes = 0
    for _ in range(6):
        warm_passes += 1
        res = await asyncio.gather(
            *(gate.call(client, u, r, spread=True) for u, r in probes)
        )
        if not any(d and _is_warming(d) for _, d, _ in res):
            break
        await gate.wait_fits_idle(client)
    before = await gate.stats(client)
    ph_steady = await _Phase(gate, client).start()

    raw_rounds, rounds_p95, warming = [], [], 0
    for _ in range(V3_ROUNDS):
        raw, p95 = {}, {}
        for c in CONCURRENCY:
            out = await gate.steady(client, c, probes=probes)
            raw[str(c)] = out["raw_ms"]
            p95[str(c)] = out["latency"]["p95_ms"]
            warming += out["warming"]
        raw_rounds.append(raw)
        rounds_p95.append(p95)
    after = await gate.stats(client)
    steady_phase = await ph_steady.stop()

    hot = probes[0]
    hot_before = await gate.stats(client)
    ph_hot = await _Phase(gate, client).start()
    hot_only = await gate.steady(client, V3_HOT_CONCURRENCY, probes=[hot])
    mixed_hot, mixed_rest = await asyncio.gather(
        gate.steady(client, 10, probes=[hot]),
        gate.steady(client, 10, probes=probes[1:]),
    )
    hot_after = await gate.stats(client)
    hot_phase = await ph_hot.stop()
    strip = lambda o: {k: v for k, v in o.items() if k not in ("raw_ms", "scores")}  # noqa: E731
    return {
        "users": len(probes),
        "warm_passes": warm_passes,
        "pooled": pool_levels(raw_rounds),
        "rounds_p95": rounds_p95,
        "warming_after_warm": warming,
        "load_share": load_share(before, after),
        "hot_user": strip(hot_only),
        "mixed_hot": strip(mixed_hot),
        "mixed_others": strip(mixed_rest),
        # ตัวจำกัดต่อผู้ใช้ทำงานกี่ครั้งในช่วง hot user (§25) · None = ml-service ไม่มีตัวนับ
        "per_user_overload_fired": overload_delta(hot_before, hot_after),
        "phases": {"steady": steady_phase, "hot": hot_phase},
    }


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


def evaluate(
    workers,
    cold,
    cold_stats,
    warm,
    warm_stats,
    rounds,
    elapsed,
    fit_baseline: dict | None = None,
    shard_mode: bool = False,
) -> dict:
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
    # ช่วงเย็นแบบ open-loop (§15) fit ผู้ใช้ชุด cold ไปก่อน · นับเฉพาะส่วนที่เพิ่มจากฐาน
    base = fit_baseline or {}
    deltas = {pid: s["fits_total"] - base.get(pid, 0) for pid, s in final.items()}
    if shard_mode:
        # แบ่ง worker ตามผู้ใช้ (§20): แต่ละคน fit ครั้งเดียวทั้งระบบ → ผลรวม = N_USERS
        exact = sum(deltas.values()) == N_USERS
    else:
        exact = all(d == N_USERS for d in deltas.values())
    checks["P2_fit_storm"] = {
        "pass": per_proc_max <= 1
        and exact
        and len(final) == workers
        and fits_after_steady == fits_after_warm
        and warm["stable"],
        "max_fits_per_user_per_process": per_proc_max,
        "processes_seen": len(final),
        "fits_per_process_final": {str(p): s["fits_total"] for p, s in final.items()},
        "fit_baseline": {str(p): v for p, v in base.items()},
        "expected_fits_per_process": None if shard_mode else N_USERS,
        "expected_fits_total": N_USERS if shard_mode else None,
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
    ap.add_argument(
        "--high-score-share",
        type=float,
        default=0.0,
        help="สัดส่วน probe ที่ point score >= 0.50 (ได้ SHAP) — 0 = ชุดปกติทั้งหมด",
    )
    ap.add_argument(
        "--open-loop-rates",
        type=lambda s: [float(x) for x in s.split(",") if x.strip()],
        default=[],
        help="อัตรา login ต่อวินาทีของการยิงแบบ open-loop หลัง steady เช่น 10,30,60,120",
    )
    ap.add_argument("--open-loop-seconds", type=float, default=60.0)
    ap.add_argument(
        "--shard-base-port",
        type=int,
        default=None,
        help="ส่ง L3 ไปพอร์ตเฉพาะของ worker ตาม shard_index ของ hub (§20)",
    )
    ap.add_argument(
        "--p1-v3",
        action="store_true",
        help="P1 v3 (§23): steady บนผู้ใช้ชุด cold 400 คน + hot user · ต้องใช้คู่ --cold-open-loop",
    )
    ap.add_argument(
        "--cold-open-loop",
        action="store_true",
        help="วัดช่วงเย็นแบบ open-loop ก่อนทุกขั้น (§15: 400 คน, 60/วินาที, 60 วินาที)",
    )
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
