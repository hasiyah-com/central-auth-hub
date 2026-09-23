"""วิเคราะห์การทดลอง A/B ของตัวจำกัดคำขอ L3 ต่อผู้ใช้ (ML Capacity Gate §27).

A = เพดาน 2 (ค่าที่ deploy) · B = เพดาน 50 (แทบไม่จำกัด) · รันเป็นคู่ติดกัน สลับลำดับ A-B / B-A
เพื่อลดผลของเครื่องที่เร็ว/ช้าต่างช่วงเวลา · seed, จำนวนผู้ใช้ และ concurrency เหมือนกันทุกรัน

**ไม่ใช่การรัน Capacity Gate เพิ่ม** และห้ามใช้ผลนี้ทำให้ §24 หรือ §26 ผ่านย้อนหลัง
กฎทุกข้อในไฟล์นี้เขียนและ commit ก่อนวัด (รายงาน §27)

    python -m scripts.ml_capacity_ab <root>     # root/pairNN/{A,B}/workers_4.json + order.txt
"""

from __future__ import annotations

import itertools
import json
import random
import statistics
import sys
from pathlib import Path

from scripts import ml_capacity_gate as G

PAIRS = 10
ALPHA = 0.05
MATERIAL_MS = 5.0  # ต่างน้อยกว่านี้ถือว่าไม่มีนัยทางปฏิบัติ แม้สม่ำเสมอ
STEADY_OVERLOAD_MAX = 0.001  # ผู้ใช้ 400 คนปกติถูกจำกัดได้ไม่เกิน 0.1% ของ request ใน steady
CORR_RHO = 0.5
LEVELS = ("1", "5", "10", "20")
BOOTSTRAP = 10_000
PERMUTATIONS = 10_000
SEED = 20260922


# ── สถิติ ─────────────────────────────────────────────────────────────────


def sign_flip_p(diffs: list[float]) -> float:
    """exact paired permutation (สลับเครื่องหมายครบ 2^n แบบ) · สองทาง · สถิติ = |mean|."""
    n = len(diffs)
    obs = abs(sum(diffs) / n)
    hits = 0
    for signs in itertools.product((1, -1), repeat=n):
        m = abs(sum(s * d for s, d in zip(signs, diffs)) / n)
        if m >= obs - 1e-12:
            hits += 1
    return hits / 2**n


def bootstrap_median_ci(diffs: list[float], level: float = 0.95) -> tuple[float, float]:
    rng = random.Random(SEED)
    n = len(diffs)
    meds = sorted(
        statistics.median(rng.choice(diffs) for _ in range(n)) for _ in range(BOOTSTRAP)
    )
    lo = meds[int((1 - level) / 2 * BOOTSTRAP)]
    hi = meds[int((1 + level) / 2 * BOOTSTRAP) - 1]
    return (round(lo, 2), round(hi, 2))


def _ranks(v: list[float]) -> list[float]:
    order = sorted(range(len(v)), key=lambda i: v[i])
    ranks = [0.0] * len(v)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(x: list[float], y: list[float]):
    rx, ry = _ranks(list(x)), _ranks(list(y))
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    sx = sum((a - mx) ** 2 for a in rx)
    sy = sum((b - my) ** 2 for b in ry)
    if sx == 0 or sy == 0:
        return None
    return sum((a - mx) * (b - my) for a, b in zip(rx, ry)) / (sx * sy) ** 0.5


def spearman_p(x: list[float], y: list[float]):
    obs = spearman(x, y)
    if obs is None:
        return None
    rng = random.Random(SEED)
    y2 = list(y)
    hits = 0
    for _ in range(PERMUTATIONS):
        rng.shuffle(y2)
        r = spearman(x, y2)
        if r is not None and abs(r) >= abs(obs) - 1e-12:
            hits += 1
    return (hits + 1) / (PERMUTATIONS + 1)


# ── ข้อมูล ────────────────────────────────────────────────────────────────


def load_pairs(root) -> list[dict]:
    pairs = []
    for d in sorted(Path(root).glob("pair*")):
        arms = {}
        for arm in ("A", "B"):
            f = d / arm / "workers_4.json"
            if not f.exists():
                raise ValueError(f"{d.name}: ไม่มีผลของ {arm}")
            arms[arm] = json.loads(f.read_text(encoding="utf-8"))
        order = (d / "order.txt").read_text(encoding="utf-8").strip()
        if order not in ("AB", "BA"):
            raise ValueError(f"{d.name}: order ต้องเป็น AB หรือ BA")
        pairs.append({"pair": int(d.name[4:]), "order": order, **arms})
    return pairs


def _p95(run: dict, level: str) -> float:
    return run["p1_v3"]["pooled"][level]["p95_ms"]


def _steady(run: dict) -> dict:
    return (run.get("p1_v3") or {}).get("phases", {}).get("steady") or {}


def _host(run: dict, key: str):
    return (_steady(run).get("host") or {}).get(key)


def _paired(diffs: list[float]) -> dict:
    return {
        "diffs_ms": [round(d, 2) for d in diffs],
        "median_diff_ms": round(statistics.median(diffs), 2),
        "ci_ms": bootstrap_median_ci(diffs),
        "p": round(sign_flip_p(diffs), 4),
    }


def _q1(pairs) -> dict:
    out = {}
    for lvl in LEVELS:
        s = _paired([_p95(p["A"], lvl) - _p95(p["B"], lvl) for p in pairs])
        slower = s["median_diff_ms"] > 0 and s["ci_ms"][0] > 0 and s["p"] < ALPHA
        if slower and s["median_diff_ms"] >= MATERIAL_MS:
            s["verdict"] = "slower_material"
        elif slower:
            s["verdict"] = "slower_small"
        else:
            s["verdict"] = "no_evidence"
        out[lvl] = s
    cpu = [
        (
            _steady(p["A"]).get("cpu_ms_per_request"),
            _steady(p["B"]).get("cpu_ms_per_request"),
        )
        for p in pairs
    ]
    if all(a is not None and b is not None for a, b in cpu):
        out["cpu_ms_per_request"] = _paired([a - b for a, b in cpu])
    return out


def _q2(pairs) -> dict:
    runs = [(p["pair"], arm, p[arm]) for p in pairs for arm in ("A", "B")]
    y = [_p95(r, "20") for _, _, r in runs]
    factors = {
        "steady_overload": lambda r: _steady(r).get("overload"),
        "host_busy_share": lambda r: _host(r, "busy_share"),
        "host_steal_share": lambda r: _host(r, "steal_share"),
        "host_load1": lambda r: _host(r, "load1"),
        "cpu_ms_per_request": lambda r: _steady(r).get("cpu_ms_per_request"),
    }
    out = {}
    for name, get in factors.items():
        x = [get(r) for _, _, r in runs]
        if any(v is None for v in x):
            out[name] = {
                "rho": None,
                "p": None,
                "associated": False,
                "note": "ไม่มีข้อมูลครบ",
            }
            continue
        rho = spearman(x, y)
        p = spearman_p(x, y)
        out[name] = {
            "rho": None if rho is None else round(rho, 3),
            "p": None if p is None else round(p, 4),
            "associated": rho is not None and abs(rho) >= CORR_RHO and p < ALPHA,
        }
    out["runs_over_budget"] = [
        {
            "pair": pair,
            "arm": arm,
            "p95_c20_ms": _p95(r, "20"),
            "steady_overload": _steady(r).get("overload"),
            "host_busy_share": _host(r, "busy_share"),
            "host_steal_share": _host(r, "steal_share"),
            "cpu_ms_per_request": _steady(r).get("cpu_ms_per_request"),
        }
        for pair, arm, r in runs
        if _p95(r, "20") > G.P95_BUDGET_MS
    ]
    return out


def _q3(pairs, q1) -> dict:
    reasons = []
    shares = []
    for p in pairs:
        st = _steady(p["A"])
        req, over = st.get("requests") or 0, st.get("overload")
        share = None if over is None or not req else over / req
        shares.append(share)
        if share is None or share > STEADY_OVERLOAD_MAX:
            reasons.append(
                f"pair {p['pair']}: steady ถูกจำกัด {over}/{req} (เกิน {STEADY_OVERLOAD_MAX:.1%})"
            )
    if q1["20"]["verdict"] == "slower_material":
        reasons.append("steady c=20 ช้าลงอย่างมีนัยเมื่อเปิดตัวจำกัด (Q1)")
    hot = G.hot_user_summary([p["A"] for p in pairs])
    if not hot["passed"]:
        reasons.append("hot-user protection ของแขน A ไม่ผ่านกฎ H (§25)")
    return {
        "ceiling_ok": not reasons,
        "reasons": reasons,
        "steady_overload_share_a": [None if s is None else round(s, 5) for s in shares],
        "hot_user_a": hot,
    }


def _q4(pairs) -> dict:
    def others(run):
        return run["p1_v3"]["mixed_others"]["latency"]["p95_ms"]

    s = _paired([others(p["B"]) - others(p["A"]) for p in pairs])
    s["b_others_p95_ms"] = [others(p["B"]) for p in pairs]
    s["b_runs_over_budget"] = sum(1 for p in pairs if others(p["B"]) > G.P95_BUDGET_MS)
    return s


def analyze(pairs: list[dict]) -> dict:
    if len(pairs) < PAIRS:
        raise ValueError(f"ต้องมีครบ {PAIRS} คู่ (ได้ {len(pairs)})")
    q1 = _q1(pairs)
    return {
        "pairs": len(pairs),
        "orders": [p["order"] for p in pairs],
        "q1": q1,
        "q2": _q2(pairs),
        "q3": _q3(pairs, q1),
        "q4": _q4(pairs),
    }


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: python -m scripts.ml_capacity_ab <root>", file=sys.stderr)
        return 2
    print(json.dumps(analyze(load_pairs(argv[0])), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
