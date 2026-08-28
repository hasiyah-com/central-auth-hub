"""L3 multi-scale window — ⛔ DEPRECATED: harness นี้มีบั๊ก cross-family window.

⚠️ **ห้ามใช้ผลจากสคริปต์นี้** — window ถูกสร้างจาก final attack ทั้ง 53 เหตุการณ์ของผู้ใช้
(obvious + subtle + campaign) ต่อกันเป็นลิสต์เดียว -> window คร่อมข้าม attack family
ทำให้ตรวจจับง่ายเกินจริง (วัดได้ W=10 unique 4.18% ทั้งที่ของจริง 0.9%)

ใช้ `exp_campaign_level.py` แทน (แยก family + window ไม่ข้าม episode + campaign-level metrics)

เก็บไฟล์นี้ไว้เป็นบทเรียนเชิงวิธี — ต้องส่ง --i-know-this-is-buggy ถึงจะรันได้
ดู: tests/reports/exp_l3_window_2026-08-26.md
"""

from __future__ import annotations

import argparse
import sys
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
QS = [0.995, 0.997, 0.999, 0.9995]
CONFIGS = {"W5": (5,), "W10": (10,), "MULTI": (5, 10)}


def _win(res: list, i: int, w: int):
    """window ยาว w ที่จบที่ index i — ถ้าไม่พอให้ pad ด้วยตัวแรก."""
    seg = res[max(0, i - w + 1) : i + 1]
    while len(seg) < w:
        seg = [seg[0]] + seg
    return SEQ._winfeat(seg)


def _feats(res: list, scales, bounds=None):
    """สร้าง feature ต่อ index — ถ้ามี bounds ให้ window อยู่ใน episode เดียวกัน."""
    out = []
    if bounds is None:
        for i in range(len(res)):
            out.append(np.concatenate([_win(res, i, w) for w in scales]))
        return out
    for a, b in zip(bounds, bounds[1:]):
        seg = res[a:b]
        for i in range(len(seg)):
            out.append(np.concatenate([_win(seg, i, w) for w in scales]))
    return out


def run_seed(users):
    """คืน per-config: (anomaly ของ normal test, anomaly ของ final attack, access decision)."""
    res = {c: dict(norm=[], atk=[], thr={}) for c in CONFIGS}
    access = []
    for alias, u in users.items():
        tr_raw, tr_ft = G3.nested_subset(u, SIZE)
        prof = LC.build_profile(tr_raw)
        base = O._baseline(tr_ft)
        tres = [SEQ._resid(v, r, prof, base) for v, r in zip(tr_ft, tr_raw)]
        bounds = G3.episode_bounds(u, SIZE)

        val_raw = [x for x, _ in u["test"]][: len(u["val_ft"])]
        vres = [SEQ._resid(v, r, prof, base) for v, r in zip(u["val_ft"], val_raw)]
        nres = [SEQ._resid(v, r, prof, base) for r, v in u["test"]]
        ares = [SEQ._resid(v, r, prof, base) for r, v in u["final_attacks"]]

        for cname, scales in CONFIGS.items():
            model = E3._fit(_feats(tres, scales, bounds))
            if model is None:
                continue
            av = E3._anom(model, _feats(vres, scales))
            res[cname]["thr"][alias] = {q: float(np.quantile(av, q)) for q in QS}
            res[cname]["norm"].append((alias, E3._anom(model, _feats(nres, scales))))
            res[cname]["atk"].append((alias, E3._anom(model, _feats(ares, scales))))

        for raw, vec in u["final_attacks"]:
            rule = evaluate_rules(
                vec, db=None, user_id=alias, ip=None, geo_country=None
            )
            beh = evaluate_behavior(
                vec,
                prof,
                subsystem_id=raw.get("subsystem"),
                user_agent=raw.get("user_agent"),
            )
            access.append(
                (alias, raw["scenario"], aggregate(rule, beh, E3.NEUTRAL).decision)
            )
    return res, access


def curve(res, access, cname):
    """คืน {q: (fpr, unique)} — unique = attack ที่ L1/L2 ปล่อยผ่านแต่ L3 ยิง."""
    wn = lambda d: RANK[d] >= RANK["warn"]  # noqa: E731
    out = {}
    per_alias = {}
    idx = 0
    for alias, _, dec in access:
        per_alias.setdefault(alias, []).append(dec)
    for q in QS:
        fp = n = uq = na = 0
        for alias, arr in res[cname]["norm"]:
            t = res[cname]["thr"][alias][q]
            fp += int((arr >= t).sum())
            n += len(arr)
        for alias, arr in res[cname]["atk"]:
            t = res[cname]["thr"][alias][q]
            decs = per_alias.get(alias, [])
            for a, d in zip(arr, decs):
                na += 1
                if a >= t and not wn(d):
                    uq += 1
        out[q] = (fp / max(n, 1), uq / max(na, 1))
        idx += 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=Path, default=BP.DEFAULT_USERS_XLSX)
    ap.add_argument("--seeds", type=int, nargs="+", default=[42, 43, 44, 45, 46])
    ap.add_argument(
        "--i-know-this-is-buggy",
        action="store_true",
        help="ยืนยันว่ารู้ว่า harness นี้มีบั๊ก cross-family (ผลใช้อ้างอิงไม่ได้)",
    )
    args = ap.parse_args()
    if not getattr(args, "i_know_this_is_buggy", False):
        raise SystemExit(
            "harness นี้มีบั๊ก cross-family window - ผลที่ได้เฟ้อ "
            "(W=10 วัดได้ 4.18% ทั้งที่ของจริง 0.9%) "
            "ใช้ exp_campaign_level.py แทน หรือส่ง --i-know-this-is-buggy"
        )
    import time

    acc = {c: {q: {"fpr": [], "uq": []} for q in QS} for c in CONFIGS}
    for seed in args.seeds:
        t0 = time.time()
        users = G3.build_seed(args.users, seed)
        res, access = run_seed(users)
        for c in CONFIGS:
            cur = curve(res, access, c)
            for q in QS:
                acc[c][q]["fpr"].append(cur[q][0])
                acc[c][q]["uq"].append(cur[q][1])
        print(f"seed {seed} done ({time.time() - t0:.0f}s)", flush=True)

    print("=" * 70)
    print(f"L3 operating curve บน final holdout ({len(args.seeds)} seeds)")
    print(f"  {'config':>8}{'quantile':>11}{'L3 FPR':>12}{'unique':>14}")
    best = {}
    for c in CONFIGS:
        for q in QS:
            f, fe = O.ci95(acc[c][q]["fpr"])
            u, ue = O.ci95(acc[c][q]["uq"])
            mark = ""
            if f <= 0.01 and (c not in best or u > best[c][2]):
                best[c] = (q, f, u, ue)
                mark = " <= FPR ok"
            print(
                f"  {c:>8}{q:>11}{f * 100:>11.2f}%{u * 100:>9.2f}±{ue * 100:<4.2f}{mark}"
            )
    print("\n  จุดที่ดีที่สุดของแต่ละ config ภายใต้ FPR<=1%:")
    for c, (q, f, u, ue) in best.items():
        verdict = "ผ่านเกณฑ์ 3-5pp" if u >= 0.03 else "ยังไม่ถึง 3pp"
        print(
            f"    {c:>8} q={q} · FPR {f * 100:.2f}% · unique {u * 100:.2f}±{ue * 100:.2f}%  ({verdict})"
        )

    _report(acc, best, args.seeds)


def _report(acc, best, seeds):
    L = [
        "# L3 multi-scale window — ดัน unique ให้ถึง 3–5pp ที่ FPR ≤1%\n",
        f"**วันที่:** 26 ส.ค. 2026 · seeds {seeds} (mean ± CI95) · size {SIZE} · final holdout\n",
        "\n## configs (residual 6 มิติเหมือนกัน ต่างแค่ window)\n",
        "| config | window | inputs |",
        "|---|---|---|",
        "| W5 | 5 | 18 |",
        "| W10 | 10 | 18 |",
        "| MULTI | 5 + 10 | 36 |",
        "\n## Operating curve (sweep quantile บน validation → วัดบน holdout)\n",
        "| config | quantile | L3 FPR | L3 unique |",
        "|---|---|---|---|",
    ]
    for c in CONFIGS:
        for q in QS:
            f, fe = O.ci95(acc[c][q]["fpr"])
            u, ue = O.ci95(acc[c][q]["uq"])
            L.append(
                f"| {c} | {q} | {f * 100:.2f}±{fe * 100:.2f}% | {u * 100:.2f}±{ue * 100:.2f}% |"
            )
    L += [
        "\n## จุดปฏิบัติการที่ดีที่สุดภายใต้ FPR ≤1%\n",
        "| config | quantile | L3 FPR | L3 unique | ผ่านเกณฑ์ 3–5pp |",
        "|---|---|---|---|---|",
    ]
    for c, (q, f, u, ue) in best.items():
        L.append(
            f"| **{c}** | {q} | {f * 100:.2f}% | **{u * 100:.2f}±{ue * 100:.2f}%** "
            f"| {'✅' if u >= 0.03 else '❌'} |"
        )
    (REPORTS / "exp_l3_multiscale_2026-08-26.md").write_text(
        "\n".join(L), encoding="utf-8"
    )
    print("\nreport ->", REPORTS / "exp_l3_multiscale_2026-08-26.md")


if __name__ == "__main__":
    main()
