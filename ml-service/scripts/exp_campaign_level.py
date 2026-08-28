"""Campaign-level metrics + W sweep ที่แก้บั๊กแล้ว (ปิดข้อสงสัยรอบสุดท้าย).

ทำ 3 อย่างพร้อมกัน:

  1. **รัน multi-scale ใหม่** ด้วยวิธีที่ถูกต้อง (window ไม่ข้าม episode / ไม่คร่อม attack family)
     -> แทนผลเดิมจาก exp_l3_multiscale ที่มีบั๊ก cross-family
  2. **campaign-level metrics** — L3 ออกแบบมาจับ "ลำดับ" การวัดด้วย event-level unique
     ประเมินค่าต่ำเกินไป เช่น campaign 5 login ยิงแค่ 1 -> event recall 20% แต่จับ campaign ได้ 100%
  3. **CI ครบ** รวม paired-seed delta ระหว่าง config

⚠️ W=5 เป็น config ที่เลือกจาก **development set** ก่อนเปิด final holdout
   ผล W=10 / MULTI บน holdout เป็น **exploratory analysis** เท่านั้น ไม่ใช้เลือกโมเดล

Run: cd hub/backend && SHARED_NAT=true PYTHONPATH=. python ../../ml-service/scripts/exp_campaign_level.py
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ML = Path(__file__).resolve().parent
sys.path.insert(0, str(ML))
import build_profiles_v2 as BP  # noqa: E402
import exp_lc_v3 as E3  # noqa: E402
import gen_v3 as G3  # noqa: E402
import lc_l3_ownership as O  # noqa: E402
import lc_l3_sequence as SEQ  # noqa: E402
import lc_run_4layer as LC  # noqa: E402

from app.security.behavior_profiling import evaluate_behavior  # noqa: E402
from app.security.risk_aggregator import aggregate  # noqa: E402
from app.security.rule_engine import evaluate_rules  # noqa: E402

REPORTS = LC.REPORTS
RANK = LC.RANK
SIZE = 5000
Q = 0.999  # p99.9 — จุดเดียวที่ FPR<=1% (จาก threshold sweep บน development)
CONFIGS = {"W5": (5,), "W10": (10,), "MULTI": (5, 10)}
PHASES_PER_CAMPAIGN = 5  # 1 campaign = 5 phase


def _win(res, i, w):
    seg = res[max(0, i - w + 1) : i + 1]
    while len(seg) < w:
        seg = [seg[0]] + seg
    return SEQ._winfeat(seg)


def _feats(res, scales):
    """window ต่อ index — pad ต้นลิสต์ (ต้องเหมือนกันทุกชุด ไม่งั้น threshold เพี้ยน)."""
    return [np.concatenate([_win(res, i, w) for w in scales]) for i in range(len(res))]


def _feats_ep(res, bounds, scales):
    """window ภายใน episode เดียวกันเท่านั้น."""
    out = []
    for a, b in zip(bounds, bounds[1:]):
        out += _feats(res[a:b], scales)
    return out


def run_seed(users):
    """คืน rows ระดับ event: (config, alias, kind, scenario, inst, pos, access, fire, day)."""
    rows = []
    for alias, u in users.items():
        tr_raw, tr_ft = G3.nested_subset(u, SIZE)
        prof = LC.build_profile(tr_raw)
        base = O._baseline(tr_ft)
        tres = [SEQ._resid(v, r, prof, base) for v, r in zip(tr_ft, tr_raw)]
        bounds = G3.episode_bounds(u, SIZE)
        tail_src = tres

        val_raw = [x for x, _ in u["test"]][: len(u["val_ft"])]
        vres = [SEQ._resid(v, r, prof, base) for v, r in zip(u["val_ft"], val_raw)]
        vb = E3._ep_bounds_of(len(vres))

        # L1/L2 decision (ไม่ขึ้นกับ config)
        def access_of(raw, vec):
            rule = evaluate_rules(
                vec, db=None, user_id=alias, ip=None, geo_country=None
            )
            beh = evaluate_behavior(
                vec,
                prof,
                subsystem_id=raw.get("subsystem"),
                user_agent=raw.get("user_agent"),
            )
            return aggregate(rule, beh, E3.NEUTRAL).decision

        # จัดกลุ่ม attack เป็น "campaign instance" (แยก family + แบ่งทีละ 5 phase)
        groups = []  # (kind, scenario, inst_id, [(raw, vec), ...])
        by = defaultdict(list)
        for raw, vec in u["final_attacks"]:
            by[raw["scenario"]].append((raw, vec))
        for scn, prs in by.items():
            prs.sort(key=lambda x: x[0]["created_at"])
            if E3._family(scn) == "campaign":
                for k in range(0, len(prs), PHASES_PER_CAMPAIGN):
                    groups.append(
                        (
                            "campaign",
                            scn,
                            f"{alias}:{scn}:{k}",
                            prs[k : k + PHASES_PER_CAMPAIGN],
                        )
                    )
            else:
                groups.append((E3._family(scn), scn, f"{alias}:{scn}", prs))

        for cname, scales in CONFIGS.items():
            model = E3._fit(_feats_ep(tres, bounds, scales))
            if model is None:
                continue
            thr = float(np.quantile(E3._anom(model, _feats_ep(vres, vb, scales)), Q))
            tail = tail_src[-(max(scales) - 1) :]

            # normal test — window ต่อ episode
            nres = [SEQ._resid(v, r, prof, base) for r, v in u["test"]]
            nb = E3._ep_bounds_of(len(nres))
            fired_n = E3._anom(model, _feats_ep(nres, nb, scales)) >= thr
            for (raw, vec), f in zip(u["test"], fired_n):
                rows.append(
                    dict(
                        cfg=cname,
                        alias=alias,
                        kind="normal",
                        scenario="normal",
                        inst=None,
                        pos=0,
                        access="allow",
                        fire=bool(f),
                        day=raw["created_at"][:10],
                    )
                )

            # attack — ต่อ instance โดยมี history จริงนำหน้า
            for kind, scn, inst, prs in groups:
                res = list(tail) + [SEQ._resid(v, r, prof, base) for r, v in prs]
                fa = E3._anom(model, _feats(res, scales))[len(tail) :] >= thr
                for pos, ((raw, vec), f) in enumerate(zip(prs, fa), start=1):
                    rows.append(
                        dict(
                            cfg=cname,
                            alias=alias,
                            kind=kind,
                            scenario=scn,
                            inst=inst,
                            pos=pos,
                            access=access_of(raw, vec),
                            fire=bool(f),
                            day=raw["created_at"][:10],
                        )
                    )
    return rows


def metrics(rows, cfg):
    r = [x for x in rows if x["cfg"] == cfg]
    nor = [x for x in r if x["kind"] == "normal"]
    atk = [x for x in r if x["kind"] != "normal"]
    camp = [x for x in atk if x["kind"] == "campaign"]
    wn = lambda d: RANK[d] >= RANK["warn"]  # noqa: E731

    # ── event-level ──
    ev_unique = sum(1 for x in atk if x["fire"] and not wn(x["access"])) / max(
        len(atk), 1
    )
    fpr = sum(x["fire"] for x in nor) / max(len(nor), 1)

    # ── campaign-level ──
    inst = defaultdict(list)
    for x in camp:
        inst[x["inst"]].append(x)
    det = uniq = 0
    ttd, alerts = [], []
    for evs in inst.values():
        evs.sort(key=lambda x: x["pos"])
        fires = [e for e in evs if e["fire"]]
        if fires:
            det += 1
            ttd.append(fires[0]["pos"])
            alerts.append(len(fires))
            if not any(wn(e["access"]) for e in evs):  # L1/L2 พลาดทั้ง campaign
                uniq += 1
    n_inst = max(len(inst), 1)

    # ── false incident ต่อ user-day ──
    ud = {(x["alias"], x["day"]) for x in nor}
    bad = {(x["alias"], x["day"]) for x in nor if x["fire"]}
    return dict(
        ev_unique=ev_unique,
        fpr=fpr,
        camp_detect=det / n_inst,
        camp_unique=uniq / n_inst,
        ttd=float(np.mean(ttd)) if ttd else 0.0,
        alerts=float(np.mean(alerts)) if alerts else 0.0,
        false_incident_rate=len(bad) / max(len(ud), 1),
        n_inst=len(inst),
        n_atk=len(atk),
        n_nor=len(nor),
    )


KEYS = [
    ("camp_unique", "campaign L3-unique"),
    ("camp_detect", "campaign detection"),
    ("ev_unique", "event L3-unique"),
    ("fpr", "L3 FPR (event)"),
    ("false_incident_rate", "false incident/user-day"),
    ("ttd", "time-to-detect (ลำดับที่)"),
    ("alerts", "alerts/campaign"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=Path, default=BP.DEFAULT_USERS_XLSX)
    ap.add_argument("--seeds", type=int, nargs="+", default=[42, 43, 44, 45, 46])
    args = ap.parse_args()
    import time

    acc = {c: [] for c in CONFIGS}
    for seed in args.seeds:
        t0 = time.time()
        rows = run_seed(G3.build_seed(args.users, seed))
        for c in CONFIGS:
            acc[c].append(metrics(rows, c))
        print(f"seed {seed} done ({time.time() - t0:.0f}s)", flush=True)

    print("=" * 86)
    m0 = acc["W5"][0]
    print(
        f"campaign instance {m0['n_inst']} · attack event {m0['n_atk']} · normal {m0['n_nor']}"
    )
    print(f"  {'metric':28}" + "".join(f"{c:>18}" for c in CONFIGS))
    for k, lab in KEYS:
        cells = ""
        for c in CONFIGS:
            m, e = O.ci95([a[k] for a in acc[c]])
            scale = 1 if k in ("ttd", "alerts") else 100
            cells += f"{m * scale:>12.2f}±{e * scale:<5.2f}"
        print(f"  {lab:28}{cells}")
    print("\n  paired-seed delta เทียบ W5 (CI95):")
    for c in ("W10", "MULTI"):
        for k, lab in (
            ("camp_unique", "campaign unique"),
            ("ev_unique", "event unique"),
            ("fpr", "FPR"),
        ):
            d, de = O.ci95([b[k] - a[k] for a, b in zip(acc["W5"], acc[c])])
            sig = "" if abs(d) > de else "  (CI คร่อม 0)"
            print(f"    {c:>6} {lab:18}{d * 100:>+8.2f}±{de * 100:<5.2f}{sig}")
    _report(acc, args.seeds)


def _report(acc, seeds):
    m0 = acc["W5"][0]
    L = [
        "# Campaign-level metrics + W sweep (harness ที่แก้บั๊กแล้ว)\n",
        f"**วันที่:** 26 ส.ค. 2026 · seeds {seeds} (mean ± CI95) · size {SIZE} · p{Q * 100:g}\n",
        f"**ขนาด:** campaign instance {m0['n_inst']} · attack event {m0['n_atk']} · normal {m0['n_nor']}\n",
        "\n> ⚠️ **W=5 เลือกจาก development set ก่อนเปิด final holdout** — ผล W=10/MULTI ที่นี่เป็น",
        "> **exploratory analysis** เพื่อปิดข้อสงสัยเท่านั้น **ไม่ถูกใช้เลือกโมเดล**",
        "> (ถ้าใช้ผล final เลือก config ชุดนี้จะไม่ใช่ holdout อีกต่อไป)\n",
        "\n## ผลทุก metric (mean ± CI95)\n",
        "| metric | " + " | ".join(CONFIGS) + " |",
        "|---|" + "---|" * len(CONFIGS),
    ]
    for k, lab in KEYS:
        cells = []
        for c in CONFIGS:
            m, e = O.ci95([a[k] for a in acc[c]])
            if k in ("ttd", "alerts"):
                cells.append(f"{m:.2f}±{e:.2f}")
            else:
                cells.append(f"{m * 100:.2f}±{e * 100:.2f}%")
        L.append(f"| {lab} | " + " | ".join(cells) + " |")
    L += [
        "\n## Paired-seed delta เทียบ W5\n",
        "| config | metric | Δ (pp) | นัยสำคัญ |",
        "|---|---|---|---|",
    ]
    for c in ("W10", "MULTI"):
        for k, lab in (
            ("camp_unique", "campaign unique"),
            ("ev_unique", "event unique"),
            ("fpr", "FPR"),
        ):
            d, de = O.ci95([b[k] - a[k] for a, b in zip(acc["W5"], acc[c])])
            sig = "CI คร่อม 0 (ไม่ต่างอย่างมีนัย)" if abs(d) <= de else "ต่างอย่างมีนัย"
            L.append(f"| {c} | {lab} | {d * 100:+.2f} ± {de * 100:.2f} | {sig} |")
    (REPORTS / "exp_campaign_level_2026-08-26.md").write_text(
        "\n".join(L), encoding="utf-8"
    )
    print("\nreport ->", REPORTS / "exp_campaign_level_2026-08-26.md")


if __name__ == "__main__":
    main()
