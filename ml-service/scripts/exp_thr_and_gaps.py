"""(1) threshold sweep ของ L3 หา FPR<=1%  +  (2) วินิจฉัยว่า L1/L2 พลาด campaign family ไหนเพราะอะไร.

ที่มา: exp_lc_v3 พบว่า
  - L3 FPR = 2.2-2.4% สูงกว่าเป้า <=1% แม้ calibrate p99 บน validation
  - L1/L2 campaign recall ตกจาก 38.8% (dev) -> 20.7% (final unseen) = จุดอ่อนจริง

Run: cd hub/backend && SHARED_NAT=true PYTHONPATH=. python ../../ml-service/scripts/exp_thr_and_gaps.py
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
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
from app.security.rule_engine import FEAT, evaluate_rules  # noqa: E402

REPORTS = LC.REPORTS
SIZE = 5000
W = 5
QS = [0.99, 0.993, 0.995, 0.997, 0.999]


def _wins(pairs, prof, base):
    res = [SEQ._resid(v, r, prof, base) for r, v in pairs]
    out = []
    for i in range(len(res)):
        w = res[max(0, i - W + 1) : i + 1]
        while len(w) < W:
            w = [w[0]] + w
        out.append(SEQ._winfeat(w))
    return out


def run(users):
    fp = dict.fromkeys(QS, 0)
    uq = dict.fromkeys(QS, 0)
    n_nor = n_atk = 0
    miss, tot = Counter(), Counter()
    why = defaultdict(Counter)
    feat_gap = defaultdict(list)

    for alias, u in users.items():
        tr_raw, tr_ft = G3.nested_subset(u, SIZE)
        prof = LC.build_profile(tr_raw)
        base = O._baseline(tr_ft)
        tres = [SEQ._resid(v, r, prof, base) for v, r in zip(tr_ft, tr_raw)]
        model = E3._fit(E3._windows_per_episode(tres, G3.episode_bounds(u, SIZE)))
        if model is None:
            continue
        val_raw = [x for x, _ in u["test"]][: len(u["val_ft"])]
        vres = [SEQ._resid(v, r, prof, base) for v, r in zip(u["val_ft"], val_raw)]
        Xva = [SEQ._winfeat(vres[i - W + 1 : i + 1]) for i in range(W - 1, len(vres))]
        av = E3._anom(model, Xva)
        thr = {q: float(np.quantile(av, q)) for q in QS}

        an = E3._anom(model, _wins(u["test"], prof, base))
        n_nor += len(an)
        for q in QS:
            fp[q] += int((an >= thr[q]).sum())

        aa = E3._anom(model, _wins(u["final_attacks"], prof, base))
        n_atk += len(aa)
        for (raw, vec), a in zip(u["final_attacks"], aa):
            rule = evaluate_rules(
                vec, db=None, user_id=alias, ip=None, geo_country=None
            )
            beh = evaluate_behavior(
                vec,
                prof,
                subsystem_id=raw.get("subsystem"),
                user_agent=raw.get("user_agent"),
            )
            dec = aggregate(rule, beh, E3.NEUTRAL).decision
            scn = raw["scenario"]
            if E3._family(scn) == "campaign":
                tot[scn] += 1
                if dec == "allow":
                    miss[scn] += 1
                    rs = rule.reasons + beh.reasons
                    why[scn]["ไม่มีสัญญาณเลย" if not rs else rs[0][:44]] += 1
                    # เก็บว่าฟีเจอร์ไหนเบี่ยงจาก baseline ของคนนี้ (เผื่อหาสัญญาณใหม่)
                    for nm in (
                        "scope_sensitivity_score",
                        "active_subsystem_count",
                        "concurrent_session_count",
                        "hours_from_typical_login_time",
                    ):
                        feat_gap[nm].append(float(vec[FEAT[nm]]))
            if dec == "allow":
                for q in QS:
                    if a >= thr[q]:
                        uq[q] += 1
    return fp, uq, n_nor, n_atk, miss, tot, why, feat_gap


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=Path, default=BP.DEFAULT_USERS_XLSX)
    ap.add_argument("--seeds", type=int, nargs="+", default=[42, 43, 44])
    args = ap.parse_args()

    F = {q: [] for q in QS}
    U = {q: [] for q in QS}
    MISS, TOT, WHY = Counter(), Counter(), defaultdict(Counter)
    for seed in args.seeds:
        users = G3.build_seed(args.users, seed)
        fp, uq, nn, na, miss, tot, why, _ = run(users)
        for q in QS:
            F[q].append(fp[q] / nn)
            U[q].append(uq[q] / na)
        MISS += miss
        TOT += tot
        for k, c in why.items():
            WHY[k] += c
        print(f"seed {seed} done", flush=True)

    L = [
        "# (1) L3 threshold sweep + (2) วินิจฉัยจุดอ่อน L1/L2 ต่อ campaign\n",
        f"**วันที่:** 26 ส.ค. 2026 · seeds {args.seeds} · size {SIZE} · final attack (holdout)\n",
        "\n## (1) threshold sweep — หาจุดที่ L3 FPR ≤ 1%\n",
        "| quantile | L3 FPR | L3 unique | ผ่านเกณฑ์ FPR≤1% |",
        "|---|---|---|---|",
    ]
    print("\n=== (1) threshold sweep ===")
    print(f"  {'quantile':>10}{'L3 FPR':>12}{'unique':>12}")
    best = None
    for q in QS:
        f, e = O.ci95(F[q])
        u, ue = O.ci95(U[q])
        ok = f <= 0.01
        if ok and best is None:
            best = (q, f, u)
        print(f"  {q:>10}{f * 100:>11.2f}%{u * 100:>11.2f}%")
        L.append(
            f"| {q} | {f * 100:.2f}±{e * 100:.2f}% | {u * 100:.2f}±{ue * 100:.2f}% "
            f"| {'✅' if ok else '❌'} |"
        )
    if best:
        L.append(
            f"\n> **เลือก quantile {best[0]}** — FPR {best[1] * 100:.2f}% "
            f"· unique {best[2] * 100:.2f}%\n"
        )
        print(
            f"  => เลือก {best[0]} (FPR {best[1] * 100:.2f}% · unique {best[2] * 100:.2f}%)"
        )

    L += [
        "\n## (2) campaign family ที่ L1/L2 พลาด (final holdout)\n",
        "| family | พลาด/ทั้งหมด | อัตราพลาด |",
        "|---|---|---|",
    ]
    print("\n=== (2) campaign ที่ L1/L2 พลาด ===")
    for scn in sorted(TOT):
        r = MISS[scn] / TOT[scn]
        print(f"  {scn:24} {MISS[scn]:>4}/{TOT[scn]:<4} ({r * 100:.0f}%)")
        L.append(f"| `{scn}` | {MISS[scn]}/{TOT[scn]} | {r * 100:.0f}% |")
    L += ["\n### เหตุผลที่พลาด\n", "| family | สัญญาณที่ได้ | ครั้ง |", "|---|---|---|"]
    print("\n  เหตุผล:")
    for scn in sorted(WHY):
        for k, v in WHY[scn].most_common(2):
            print(f"    {scn:24} {k[:46]} x{v}")
            L.append(f"| `{scn}` | {k} | {v} |")
    (REPORTS / "exp_thr_and_gaps_2026-08-26.md").write_text(
        "\n".join(L), encoding="utf-8"
    )
    print("\nreport ->", REPORTS / "exp_thr_and_gaps_2026-08-26.md")


if __name__ == "__main__":
    main()
