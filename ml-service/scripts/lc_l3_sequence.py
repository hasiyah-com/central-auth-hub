"""Config E — Sequence/window L3: aggregate residual ข้าม window แทน point anomaly.

ที่มา: l3_campaign_2026-08-26.md พบว่า campaign (low-and-slow) เป็น **sequence anomaly** —
แต่ละ event ปกติ แต่ "ลำดับ" drift ร่วมกันหลายมิติ · IForest ต่อ event (config D) จับได้น้อยมาก
(0.1-0.4%) เพราะมองทีละจุด → config E ให้ L3 มองเป็น window

  E vector = residual 6 มิติ (เหมือน D) × [mean, slope(last-first), ptp] ข้าม window W=5 = 18 มิติ
  fit per-user IForest บน rolling window ของ train · calibrate 99th pct · bounded bonus <=0.15 เท่าเดิม

เทียบ: A (L1+L2) · D (point residual) · E (sequence residual)
วัด: L3-unique (attack ที่ L3 ทำให้ surfaced แต่ L1+L2 พลาด) — เน้นเฉพาะ campaign

Run: cd hub/backend && SHARED_NAT=true PYTHONPATH=. python ../../ml-service/scripts/lc_l3_sequence.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from sklearn.ensemble import IsolationForest

ML = Path(__file__).resolve().parent
sys.path.insert(0, str(ML))
import build_profiles_v2 as BP  # noqa: E402
import lc_l3_ownership as O  # noqa: E402  (reuse l3_input/_baseline/_decide/ci95)
import lc_run_4layer as LC  # noqa: E402

from app.security.behavior_profiling import evaluate_behavior  # noqa: E402
from app.security.risk_aggregator import aggregate  # noqa: E402
from app.security.rule_engine import evaluate_rules  # noqa: E402

REPORTS = LC.REPORTS
RANK = LC.RANK
SIZES = LC.SIZES
W = 5  # window size (เท่าจำนวน phase ของ campaign)
MIN_TRUSTED = O.MIN_TRUSTED
BONUS_CAP = O.L3_BONUS_CAP
VAL_FPR = O.VAL_FPR
CONFIGS = ["A_no_l3", "D_point", "E_sequence", "F_channel"]
CLABEL = {
    "A_no_l3": "A: L1+L2",
    "D_point": "D: L3 point-residual",
    "E_sequence": "E: L3 sequence-residual (W=5)",
    "F_channel": "F: L3 sequence เป็น surfacing channel (warn ตรง)",
}


def _resid(vec, raw, prof, base):
    return O.l3_input("D_residual", vec, raw, prof, base)


def _winfeat(res_window):
    """residual (W,6) -> 18 มิติ: mean / slope(last-first) / ptp ต่อ dim."""
    a = np.array(res_window, dtype=float)
    return np.concatenate([a.mean(axis=0), a[-1] - a[0], a.max(axis=0) - a.min(axis=0)])


def _fit(X):
    if len(X) < 12:
        return None
    X = np.asarray(X, dtype=float)
    keep = X.std(axis=0) > 1e-9
    if not keep.any():
        return None
    m = IsolationForest(n_estimators=100, contamination=0.02, random_state=42).fit(
        X[:, keep]
    )
    a = -m.score_samples(X[:, keep])
    thr = float(np.quantile(a, 1 - VAL_FPR))
    scale = float(max(np.quantile(a, 0.999) - thr, 1e-6))
    return (m, keep, thr, scale)


def _bonus(model, X):
    if model is None or len(X) == 0:
        return [0.0] * len(X)
    m, keep, thr, scale = model
    a = -m.score_samples(np.asarray(X, dtype=float)[:, keep])
    return [
        float(np.clip((x - thr) / scale, 0.0, 1.0)) * BONUS_CAP if x >= thr else 0.0
        for x in a
    ]


def evaluate(users, size, config):
    rows = []  # (label, scenario, base_dec, final_dec, l3_flag_raw)
    for alias, u in users.items():
        prof = LC.build_profile(u["train_raw"][:size])
        tv, tr_ = u["train_ft"][:size], u["train_raw"][:size]
        base = O._baseline(tv) if len(tv) >= 8 else None
        model, tail = None, []
        if config != "A_no_l3" and size >= MIN_TRUSTED and base is not None:
            tres = [_resid(v, r, prof, base) for v, r in zip(tv, tr_)]
            if config == "D_point":
                model = _fit(tres)
            else:  # E/F: rolling windows ของ train
                model = _fit(
                    [_winfeat(tres[i - W + 1 : i + 1]) for i in range(W - 1, len(tres))]
                )
            tail = tres[-(W - 1) :] if len(tres) >= W - 1 else tres

        def x_of(pairs, hist_res):
            """input ของ L3 ต่อแถว — point: residual เดี่ยว · sequence: window ที่มี history นำหน้า."""
            out, run = [], list(hist_res)
            for raw, vec in pairs:
                r = _resid(vec, raw, prof, base)
                if config == "D_point":
                    out.append(r)
                else:
                    win = (run + [r])[-W:]
                    while len(win) < W:  # pad ด้วยตัวแรก ถ้า history สั้น
                        win = [win[0]] + win
                    out.append(_winfeat(win))
                run.append(r)
            return out

        def emit(pairs, label, scen, hist):
            if not pairs:
                return
            bon = (
                _bonus(model, x_of(pairs, hist))
                if model is not None
                else [0.0] * len(pairs)
            )
            for (raw, vec), b in zip(pairs, bon):
                rule = evaluate_rules(
                    vec, db=None, user_id=alias, ip=None, geo_country=None
                )
                beh = evaluate_behavior(
                    vec,
                    prof,
                    subsystem_id=raw.get("subsystem"),
                    user_agent=raw.get("user_agent"),
                )
                d = aggregate(rule, beh, O.NEUTRAL)
                final = d.decision
                if b > 0 and RANK[d.decision] < RANK["challenge"]:
                    if config == "F_channel":
                        # surfacing channel: L3 ยิง = warn ทันที (monitoring) ไม่ผ่านการบวกคะแนน
                        final = (
                            d.decision if RANK[d.decision] >= RANK["warn"] else "warn"
                        )
                    else:
                        final = O._decide(min(d.total_score + b, 1.0))
                rows.append((label, scen(raw), d.decision, final, b > 0))

        hist = tail if model is not None else []
        emit(u["test"], 0, lambda r: "normal", hist)
        # attack: แยกตาม scenario แล้วเรียงเวลา — campaign จะได้สะสม phase ของตัวเองใน window
        byscn = {}
        for raw, vec in u["attacks"]:
            byscn.setdefault(raw["scenario"], []).append((raw, vec))
        for scn, pairs in byscn.items():
            pairs.sort(key=lambda p: p[0]["created_at"])
            emit(pairs, 1, lambda r: r["scenario"], hist)
    return rows


def metrics(rows):
    """แยก raw / effective / overlap ตามแผน §7 — วัดศักยภาพดิบของ L3 แยกจากผลหลัง fusion."""
    a = [r for r in rows if r[0] == 1]
    n = [r for r in rows if r[0] == 0]
    ch = lambda d: RANK[d] >= RANK["challenge"]  # noqa: E731
    wn = lambda d: RANK[d] >= RANK["warn"]  # noqa: E731
    tp, fp = sum(ch(r[3]) for r in a), sum(ch(r[3]) for r in n)
    camp = [r for r in a if r[1] == "campaign"]

    def _raw_uniq(g):
        """L3 flag ได้ ทั้งที่ L1/L2 ปล่อยผ่าน (ยังไม่สนว่า decision เปลี่ยนไหม)."""
        return (sum(1 for r in g if r[4] and not wn(r[2])) / len(g)) if g else 0.0

    def _eff_uniq(g):
        """L3 flag ได้ + ทำให้ final decision เปลี่ยนจริง."""
        return (
            (sum(1 for r in g if r[4] and not wn(r[2]) and wn(r[3])) / len(g))
            if g
            else 0.0
        )

    def _overlap(g):
        """L3 flag ได้ แต่ L1/L2 จับอยู่แล้ว (สัญญาณซ้ำ)."""
        return (sum(1 for r in g if r[4] and wn(r[2])) / len(g)) if g else 0.0

    return dict(
        recall=tp / len(a),
        precision=tp / (tp + fp) if tp + fp else 0.0,
        cfpr=fp / len(n),
        wfpr=sum(wn(r[3]) for r in n) / len(n),
        l3_raw_unique=_raw_uniq(a),
        l3_unique=_eff_uniq(a),
        l3_overlap=_overlap(a),
        l3_raw_unique_campaign=_raw_uniq(camp),
        l3_unique_campaign=_eff_uniq(camp),
        campaign_surfaced=(sum(1 for r in camp if wn(r[3])) / len(camp))
        if camp
        else 0.0,
        n_atk=len(a),
        n_camp=len(camp),
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=Path, default=BP.DEFAULT_USERS_XLSX)
    ap.add_argument("--seeds", type=int, nargs="+", default=[42, 43, 44, 45, 46])
    args = ap.parse_args()
    import time

    acc = {c: {s: [] for s in SIZES} for c in CONFIGS}
    for seed in args.seeds:
        BP.SEED = seed
        t0 = time.time()
        users = LC.gen_all(args.users)
        for c in CONFIGS:
            for s in SIZES:
                acc[c][s].append(metrics(evaluate(users, s, c)))
        print(f"seed {seed} done ({time.time() - t0:.0f}s)", flush=True)

    keys = [
        ("l3_raw_unique_campaign", "raw-camp"),
        ("l3_unique_campaign", "eff-camp"),
        ("l3_overlap", "overlap"),
        ("campaign_surfaced", "camp surfaced"),
        ("l3_unique", "L3uniq-all"),
        ("recall", "recall"),
        ("cfpr", "cFPR"),
        ("wfpr", "wFPR"),
    ]
    print("=" * 82)
    for c in CONFIGS:
        print(f"\n[{CLABEL[c]}]  mean±CI95 ({len(args.seeds)} seeds)")
        print(f"  {'size':>6}" + "".join(f"{lab:>17}" for _, lab in keys))
        for s in SIZES:
            cells = ""
            for k, _ in keys:
                m, e = O.ci95([x[k] for x in acc[c][s]])
                cells += f"{m * 100:>11.1f}±{e * 100:<5.1f}"
            print(f"  {s:>6}{cells}")
    _report(acc, args.seeds)


def _report(acc, seeds):
    L = [
        "# Config E — Sequence/window L3 (residual ข้าม window) vs point IForest\n",
        "**วันที่:** 26 ส.ค. 2026  ",
        f"**seeds:** {seeds} (mean ± 95% CI) · sizes {SIZES} · W={W} · bounded bonus <={BONUS_CAP}\n",
        "**สมมติฐาน:** campaign เป็น *sequence anomaly* -> ให้ L3 มองเป็น window "
        "(residual 6 มิติ × [mean, slope, ptp] = 18) แทน point anomaly\n",
        "**configs:** A=L1+L2 · D=L3 point-residual · E=L3 sequence-residual\n",
        "\n## L3 unique detection เฉพาะ campaign (metric ชี้ขาด)\n",
    ]

    def table(key):
        out = [
            "| config | " + " | ".join(str(s) for s in SIZES) + " |",
            "|---|" + "---|" * len(SIZES),
        ]
        for c in CONFIGS:
            cells = []
            for s in SIZES:
                m, e = O.ci95([x[key] for x in acc[c][s]])
                cells.append(f"{m * 100:.1f}±{e * 100:.1f}")
            out.append(f"| {CLABEL[c]} | " + " | ".join(cells) + " |")
        return out

    L += table("l3_unique_campaign")
    for key, lab in [
        ("campaign_surfaced", "campaign surfaced (warn+)"),
        ("l3_unique", "L3-unique (attack ทั้งหมด)"),
        ("recall", "recall รวม (challenge+)"),
        ("cfpr", "challenge FPR"),
        ("wfpr", "warn FPR (ต้นทุนของ F)"),
    ]:
        L.append(f"\n## {lab}\n")
        L += table(key)
    e5 = [x["l3_unique_campaign"] for x in acc["E_sequence"][5000]]
    d5 = [x["l3_unique_campaign"] for x in acc["D_point"][5000]]
    dm, de = O.ci95([a - b for a, b in zip(e5, d5)])
    L.append(
        f"\n## E − D (campaign L3-unique, size 5000): **{dm * 100:+.1f} ± {de * 100:.1f} pp**\n"
    )
    (REPORTS / "l3_sequence_2026-08-26.md").write_text("\n".join(L), encoding="utf-8")
    print("\nreport ->", REPORTS / "l3_sequence_2026-08-26.md")


if __name__ == "__main__":
    main()
