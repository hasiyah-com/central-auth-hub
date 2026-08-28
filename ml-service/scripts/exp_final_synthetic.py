"""ผลปิดท้าย Synthetic Experiment — วัดครั้งสุดท้ายก่อนไป Production Shadow Replay.

ปรับการวัดตามที่กำหนด (ไม่แตะโมเดล/ฟีเจอร์/threshold — หยุดปรับจาก final holdout แล้ว):

  1. **L1/L2 campaign detection วัดจริง** ไม่ใช้สูตรประมาณ (1−(1−p)^5)
  2. **First-detector + lead-time** — ใครเจอก่อน และเร็วกว่ากี่เหตุการณ์
  3. **CI เป็น Wilson (สัดส่วน) / bootstrap (ค่าเฉลี่ย)** — normal-approx พังเมื่อ p ใกล้ 0
  4. **ระบุจำนวน campaign ต่อ seed ชัดเจน**
  5. **ภาระ alert สเกลตามจำนวนผู้ใช้จริง** (100 / 1,000 / 5,000 คน)

ใช้ event rows จาก `exp_campaign_level.run_seed` (window ไม่ข้าม episode/family แล้ว)

Run: cd hub/backend && SHARED_NAT=true PYTHONPATH=. python ../../ml-service/scripts/exp_final_synthetic.py
"""

from __future__ import annotations

import argparse
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ML = Path(__file__).resolve().parent
sys.path.insert(0, str(ML))
import build_profiles_v2 as BP  # noqa: E402
import exp_campaign_level as CL  # noqa: E402
import gen_v3 as G3  # noqa: E402

REPORTS = CL.REPORTS
RANK = CL.RANK
CONFIGS = CL.CONFIGS


def wilson(k: int, n: int, z: float = 1.96):
    """Wilson score interval — เหมาะกับสัดส่วนที่ p ใกล้ 0 (normal-approx จะให้ช่วงติดลบ)."""
    if n == 0:
        return 0.0, 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return p, max(0.0, c - h), min(1.0, c + h)


def boot(vals, n_boot: int = 5000):
    """bootstrap CI95 ของค่าเฉลี่ย (ไม่สมมติการแจกแจงปกติ)."""
    a = np.asarray(vals, dtype=float)
    if a.size == 0:
        return 0.0, 0.0, 0.0
    rng = np.random.default_rng(0)
    bs = rng.choice(a, (n_boot, a.size), replace=True).mean(axis=1)
    return (
        float(a.mean()),
        float(np.percentile(bs, 2.5)),
        float(np.percentile(bs, 97.5)),
    )


def cluster_boot(rows, keyf, numf, denf, n_boot: int = 2000):
    """cluster bootstrap — resample "กลุ่ม" ไม่ใช่รายเหตุการณ์.

    เหตุการณ์ใน campaign เดียวกัน / ผู้ใช้เดียวกัน / seed เดียวกัน **ไม่เป็นอิสระ**
    การใช้ Wilson กับ event ทั้งหมดจะให้ CI แคบเกินจริง -> resample ที่ระดับ cluster แทน
    """
    g = defaultdict(lambda: [0.0, 0.0])
    for r in rows:
        k = keyf(r)
        g[k][0] += numf(r)
        g[k][1] += denf(r)
    if not g:
        return 0.0, 0.0, 0.0
    nums = np.array([v[0] for v in g.values()])
    dens = np.array([v[1] for v in g.values()])
    point = float(nums.sum() / max(dens.sum(), 1))
    rng = np.random.default_rng(0)
    pick = rng.integers(0, len(nums), (n_boot, len(nums)))
    bs = nums[pick].sum(1) / np.maximum(dens[pick].sum(1), 1)
    return point, float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def campaign_table(rows, cfg):
    """รวม event เป็น campaign instance + หา first-detector ของแต่ละชั้น."""
    wn = lambda d: RANK[d] >= RANK["warn"]  # noqa: E731
    inst = defaultdict(list)
    for x in rows:
        if x["cfg"] == cfg and x["kind"] == "campaign":
            # ต้องมี seed ในคีย์ — inst id ซ้ำข้าม seed (alias/scenario เดียวกัน)
            # ถ้าไม่แยกจะรวม 5 seeds เป็น instance เดียว 25 event -> alerts/campaign เกิน 5 ได้
            inst[(x.get("seed"), x["inst"])].append(x)
    out = []
    for key, evs in inst.items():
        evs.sort(key=lambda x: x["pos"])
        base_pos = next((e["pos"] for e in evs if wn(e["access"])), None)
        l3_pos = next((e["pos"] for e in evs if e["fire"]), None)
        out.append(
            dict(
                inst=key,
                seed=evs[0].get("seed"),
                alias=evs[0]["alias"],
                n_events=len(evs),
                scenario=evs[0]["scenario"],
                base_det=base_pos is not None,
                l3_det=l3_pos is not None,
                base_pos=base_pos,
                l3_pos=l3_pos,
                l3_alerts=sum(e["fire"] for e in evs),
            )
        )
    return out


def hier_boot(tbl, flag, n_boot: int = 2000):
    """hierarchical bootstrap: resample ผู้ใช้ -> seed ภายในผู้ใช้ -> instance.

    campaign 300 ชุดมาจากโปรไฟล์ผู้ใช้พื้นฐานเพียง 12 คนที่ใช้ซ้ำใน 5 seed
    -> ไม่อิสระต่อกันจริง · Wilson (ที่ถือว่าอิสระ) จะให้ CI แคบเกินไป
    """
    by_user = defaultdict(lambda: defaultdict(list))
    for t in tbl:
        by_user[t["alias"]][t["seed"]].append(1.0 if flag(t) else 0.0)
    users = list(by_user)
    if not users:
        return 0.0, 0.0, 0.0
    allv = [v for u in users for sd in by_user[u] for v in by_user[u][sd]]
    point = float(np.mean(allv))
    rng = np.random.default_rng(0)
    stats = []
    for _ in range(n_boot):
        vals = []
        for u in rng.choice(users, len(users), replace=True):
            seeds = list(by_user[u])
            for sd in rng.choice(seeds, len(seeds), replace=True):
                arr = by_user[u][sd]
                idx = rng.integers(0, len(arr), len(arr))
                vals += [arr[i] for i in idx]
        stats.append(np.mean(vals) if vals else 0.0)
    return point, float(np.percentile(stats, 2.5)), float(np.percentile(stats, 97.5))


def summarize(all_rows, cfg, n_seeds):
    tbl = campaign_table(all_rows, cfg)
    n = len(tbl)
    both = [t for t in tbl if t["base_det"] and t["l3_det"]]
    nb = max(len(both), 1)
    nor = [x for x in all_rows if x["cfg"] == cfg and x["kind"] == "normal"]
    atk = [x for x in all_rows if x["cfg"] == cfg and x["kind"] != "normal"]
    # ต้องมี seed ในคีย์ — ทุก seed ใช้ปฏิทินเดียวกัน ถ้าไม่แยกจะนับ user-day ซ้อนกัน
    # (เคยทำให้ false incident rate เฟ้อ 4 เท่า: 1.1% -> 4.2%)
    ud = {(x.get("seed"), x["alias"], x["day"]) for x in nor}
    bad = {(x.get("seed"), x["alias"], x["day"]) for x in nor if x["fire"]}
    # false incident/user-day: cluster bootstrap ตาม (seed, user)
    # หลายวันของผู้ใช้คนเดียวกันมีพฤติกรรมสัมพันธ์กัน -> Wilson ที่ถือว่าอิสระให้ CI แคบเกินไป
    day_rows = [
        {"k": (sd, al), "bad": 1.0 if (sd, al, d) in bad else 0.0} for (sd, al, d) in ud
    ]
    return dict(
        n_inst=n,
        per_seed=n // max(n_seeds, 1),
        base_det=wilson(sum(t["base_det"] for t in tbl), n),
        l3_det=wilson(sum(t["l3_det"] for t in tbl), n),
        either=wilson(sum(t["base_det"] or t["l3_det"] for t in tbl), n),
        l3_only=wilson(sum((not t["base_det"]) and t["l3_det"] for t in tbl), n),
        base_only=wilson(sum(t["base_det"] and not t["l3_det"] for t in tbl), n),
        both=wilson(len(both), n),
        l3_first=wilson(sum(1 for t in both if t["l3_pos"] < t["base_pos"]), nb),
        base_first=wilson(sum(1 for t in both if t["base_pos"] < t["l3_pos"]), nb),
        same_first=wilson(sum(1 for t in both if t["base_pos"] == t["l3_pos"]), nb),
        lead=boot([t["base_pos"] - t["l3_pos"] for t in both]),
        ttd=boot([t["l3_pos"] for t in tbl if t["l3_det"]]),
        alerts=boot([t["l3_alerts"] for t in tbl if t["l3_det"]]),
        # event metrics: cluster bootstrap ตาม (seed, user, campaign instance)
        ev_unique=cluster_boot(
            atk,
            lambda r: (r.get("seed"), r["alias"], r.get("inst") or r["scenario"]),
            lambda r: 1.0 if (r["fire"] and RANK[r["access"]] < RANK["warn"]) else 0.0,
            lambda r: 1.0,
        ),
        # normal FPR: cluster bootstrap ตาม (seed, user, day)
        fpr=cluster_boot(
            nor,
            lambda r: (r.get("seed"), r["alias"], r["day"]),
            lambda r: 1.0 if r["fire"] else 0.0,
            lambda r: 1.0,
        ),
        incident_rate=cluster_boot(
            day_rows, lambda r: r["k"], lambda r: r["bad"], lambda r: 1.0
        ),
        # hierarchical bootstrap (user -> seed -> instance) สำหรับสัดส่วนระดับ campaign
        base_det_h=hier_boot(tbl, lambda t: t["base_det"]),
        l3_det_h=hier_boot(tbl, lambda t: t["l3_det"]),
        l3_only_h=hier_boot(tbl, lambda t: (not t["base_det"]) and t["l3_det"]),
        max_events=max((t["n_events"] for t in tbl), default=0),
        dedup_incident=boot([1.0 for t in tbl if t["l3_det"]])
        if any(t["l3_det"] for t in tbl)
        else (0.0, 0.0, 0.0),
        n_both=len(both),
        n_l3_det=sum(t["l3_det"] for t in tbl),
        n_userdays=len(ud),
        n_atk=len(atk),
        n_nor=len(nor),
        by_family={
            scn: wilson(
                sum(t["l3_det"] for t in tbl if t["scenario"] == scn),
                max(sum(1 for t in tbl if t["scenario"] == scn), 1),
            )
            for scn in sorted({t["scenario"] for t in tbl})
        },
    )


def _pc(t):
    return f"{t[0] * 100:.1f}% [{t[1] * 100:.1f}, {t[2] * 100:.1f}]"


def _nm(t):
    return f"{t[0]:+.2f} [{t[1]:+.2f}, {t[2]:+.2f}]"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=Path, default=BP.DEFAULT_USERS_XLSX)
    ap.add_argument("--seeds", type=int, nargs="+", default=[42, 43, 44, 45, 46])
    args = ap.parse_args()
    import time

    all_rows = []
    for seed in args.seeds:
        t0 = time.time()
        rows = CL.run_seed(G3.build_seed(args.users, seed))
        for r in rows:
            r["seed"] = seed
        all_rows += rows
        print(f"seed {seed} done ({time.time() - t0:.0f}s)", flush=True)

    S = {c: summarize(all_rows, c, len(args.seeds)) for c in CONFIGS}
    w = S["W5"]
    print("=" * 80)
    print(
        f"campaign instance {w['n_inst']} ({w['per_seed']}/seed × {len(args.seeds)}) · "
        f"attack {w['n_atk']} · normal {w['n_nor']} · user-day {w['n_userdays']}"
    )
    print("\n[Config F / W=5]  Wilson CI95 (สัดส่วน) · bootstrap CI95 (ค่าเฉลี่ย)")
    for lab, k in (
        ("L1/L2 campaign detection (วัดจริง)", "base_det"),
        ("L3 campaign detection", "l3_det"),
        ("รวมสองชั้น", "either"),
        ("L3 only (L1/L2 พลาดทั้ง campaign)", "l3_only"),
        ("L1/L2 only", "base_only"),
        ("จับได้ทั้งคู่", "both"),
    ):
        print(f"  {lab:38}{_pc(w[k])}")
    print("\n  first detector (เฉพาะที่จับได้ทั้งคู่):")
    for lab, k in (
        ("L3 ก่อน", "l3_first"),
        ("L1/L2 ก่อน", "base_first"),
        ("พร้อมกัน", "same_first"),
    ):
        print(f"    {lab:36}{_pc(w[k])}")
    print(f"  lead-time (base − L3 · + = L3 เร็วกว่า): {_nm(w['lead'])}")
    print(
        f"  time-to-detect L3 {_nm(w['ttd'])} · alerts/campaign {_nm(w['alerts'])} "
        f"(ฐาน = {w['n_l3_det']} campaign ที่ L3 surface · สูงสุดเป็นไปได้ {w['max_events']})"
    )
    print(f"\n  event L3-unique {_pc(w['ev_unique'])} · L3 FPR {_pc(w['fpr'])}")
    print(f"  false incident/user-day {_pc(w['incident_rate'])}")
    print("\n  ภาระ alert ตามขนาดผู้ใช้จริง:")
    for nu in (100, 1000, 5000):
        r = w["incident_rate"]
        print(
            f"    {nu:>5} คน: {r[0] * nu:6.1f} ครั้ง/วัน  [{r[1] * nu:.1f}, {r[2] * nu:.1f}]"
        )
    print("\n  L3 detection แยก family:")
    for scn, t in w["by_family"].items():
        print(f"    {scn:26}{_pc(t)}")
    _report(S, args.seeds)


def _report(S, seeds):
    w = S["W5"]
    L = [
        "# ผลปิดท้าย Synthetic Experiment — campaign-level (Wilson / bootstrap CI)\n",
        f"**วันที่:** 26 ส.ค. 2026 · seeds {seeds} · Config F (W=5, p99.9) · final holdout\n",
        "\n> **หยุดปรับโมเดลจาก final holdout แล้ว** — รายงานนี้ปรับเฉพาะ *วิธีวัด* ไม่แตะ",
        "> ฟีเจอร์/threshold/window · ผลนี้เป็นการปิดผล synthetic ก่อนไป production shadow replay\n",
        "\n## ขนาดข้อมูล\n",
        "| รายการ | จำนวน |",
        "|---|---|",
        f"| campaign instance | **{w['n_inst']}** ({w['per_seed']}/seed × {len(seeds)} seeds) |",
        f"| attack event (holdout) | {w['n_atk']} |",
        f"| normal event | {w['n_nor']} |",
        f"| user-day ที่สังเกต | {w['n_userdays']} |",
        "\n**CI:** สัดส่วน = Wilson score interval · ค่าเฉลี่ย = bootstrap 5,000 resample",
        "(ไม่ใช้ normal approximation ซึ่งให้ช่วงติดลบเมื่อ p ใกล้ 0)\n",
        "\n## 1. Campaign detection — วัดจริงทั้งสองชั้น\n",
        "| ตัวชี้วัด | ค่า [CI95] |",
        "|---|---|",
        f"| **L1/L2 campaign detection** | **{_pc(w['base_det'])}** |",
        f"| L3 campaign detection | {_pc(w['l3_det'])} |",
        f"| รวมสองชั้น | {_pc(w['either'])} |",
        f"| **L3 only** (L1/L2 พลาดทั้ง campaign) | **{_pc(w['l3_only'])}** |",
        f"| L1/L2 only | {_pc(w['base_only'])} |",
        f"| จับได้ทั้งคู่ | {_pc(w['both'])} |",
        "\n## 2. First-detector & Lead-time\n",
        "| ตัวชี้วัด | ค่า [CI95] |",
        "|---|---|",
        f"| L3 ตรวจพบก่อน | {_pc(w['l3_first'])} |",
        f"| L1/L2 ตรวจพบก่อน | {_pc(w['base_first'])} |",
        f"| ตรวจพบพร้อมกัน | {_pc(w['same_first'])} |",
        f"| **lead-time** (base − L3 · + = L3 เร็วกว่า) | **{_nm(w['lead'])}** |",
        f"| time-to-detect ของ L3 (ลำดับที่) | {_nm(w['ttd'])} |",
        f"| alerts ต่อ campaign | {_nm(w['alerts'])} |",
        "\n## 3. Event-level และภาระงาน\n",
        "| ตัวชี้วัด | ค่า [CI95] |",
        "|---|---|",
        f"| event L3-unique | {_pc(w['ev_unique'])} |",
        f"| L3 FPR (event) | {_pc(w['fpr'])} |",
        f"| false incident ต่อ user-day | {_pc(w['incident_rate'])} |",
        "\n### ภาระ alert ตามขนาดผู้ใช้จริง\n",
        "| ผู้ใช้ | false incident/วัน [CI95] |",
        "|---|---|",
    ]
    for nu in (100, 1000, 5000):
        r = w["incident_rate"]
        L.append(f"| {nu:,} | **{r[0] * nu:.1f}** [{r[1] * nu:.1f}, {r[2] * nu:.1f}] |")
    L += [
        "\n## 4. L3 detection แยก campaign family\n",
        "| family | detection [CI95] |",
        "|---|---|",
    ]
    for scn, t in w["by_family"].items():
        L.append(f"| `{scn}` | {_pc(t)} |")
    L += [
        "\n## 5. เทียบ config (exploratory — ไม่ใช้เลือกโมเดล)\n",
        "| config | L3 campaign detection | event unique | FPR |",
        "|---|---|---|---|",
    ]
    for c in CONFIGS:
        L.append(
            f"| {c} | {_pc(S[c]['l3_det'])} | {_pc(S[c]['ev_unique'])} | {_pc(S[c]['fpr'])} |"
        )
    (REPORTS / "exp_final_synthetic_2026-08-26.md").write_text(
        "\n".join(L), encoding="utf-8"
    )
    print("\nreport ->", REPORTS / "exp_final_synthetic_2026-08-26.md")


if __name__ == "__main__":
    main()
