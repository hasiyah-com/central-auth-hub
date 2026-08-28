"""OPTION 1 — Ablation: Rule/Behavior เดี่ยว vs +V8 MLP บนโปรไฟล์ V2 (คนจริง 12 คน).

ตอบ: ML (V8) เพิ่ม recall เหนือ Rule/Behavior จริงไหม (คุ้ม complexity ไหม)

ใช้โค้ด production จริง (evaluate_rules/evaluate_behavior/aggregate) + V8 จริง
(neural_features/fit_profile_baselines/runtime) — ไม่มี mapping error

เงื่อนไข: V8 eligible เมื่อ >= 1000 event -> ใช้ V2 size-5000
combine: layered "OR" — final = max(base_decision, v8_decision)  (สถาปัตยกรรม Rule OR ML)

Run:
    cd hub/backend && SHARED_NAT=true PYTHONPATH=. python ../../ml-service/scripts/eval_ablation_v8.py --v8 <path>
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from datetime import datetime
from pathlib import Path
from statistics import mode

DATA = Path(__file__).resolve().parents[1] / "data"
TS = "%Y-%m-%d %H:%M:%S"
SCOPE = {"HUB": 0.0, "SUB_A": 0.8, "SUB_B": 0.6}
RANK = {"allow": 0, "warn": 1, "challenge": 2, "block": 3}
EXPECTED = {
    "combined_ato": "block",
    "new_os": "warn",
    "off_hours": "warn",
    "new_device": "challenge",
    "new_ua_family": "challenge",
    "failed_spike": "challenge",
    "login_velocity": "challenge",
    "concurrent_sessions": "challenge",
    "new_passkey": "challenge",
    "permission_change": "challenge",
    "subsystem_lateral": "challenge",
}


def parse(s):
    return datetime.strptime(s, TS)


def bver(row):
    m = re.search(r"(\d+)", row.get("browser", "")) or re.search(
        r"FBAV/(\d+)", row.get("user_agent", "")
    )
    return int(m.group(1)) if m else 0


def maxd(a, b):
    return a if RANK[a] >= RANK[b] else b


def is_ch(dec):
    return RANK[dec] >= RANK["challenge"]


def is_wn(dec):
    return RANK[dec] >= RANK["warn"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--v8", required=True, type=Path)
    ap.add_argument(
        "--recalibrate",
        action="store_true",
        help="ตั้ง V8 threshold ใหม่จาก normal-train ของ V2 (แทน threshold ของ generator ตัวเอง)",
    )
    ap.add_argument(
        "--cal-challenge-fpr",
        type=float,
        default=0.005,
        help="เป้า challenge FPR ตอน recalibrate (V8 flag normal ได้ไม่เกินนี้)",
    )
    ap.add_argument("--cal-warn-fpr", type=float, default=0.02)
    args = ap.parse_args()
    sys.path.insert(0, str(args.v8 / "scripts"))
    sys.path.insert(0, str(Path(__file__).resolve().parent))

    from app.security.behavior_profiling import evaluate_behavior
    from app.security.iforest_scorer import IForestResult
    from app.security.risk_aggregator import aggregate
    from app.security.rule_engine import FEAT, evaluate_rules
    import run_temporal_mlp_v8 as V8
    import shadow_temporal_runtime_v8 as RT

    FEATS = [n for n, _ in sorted(FEAT.items(), key=lambda kv: kv[1])]
    runtime = RT.load_runtime(args.v8 / "results" / "temporal_mlp_v8")
    W = V8.WINDOW
    NEUTRAL = IForestResult(raw_score=0.0, risk_score=0.0, label="neutral")

    frows = list(csv.DictReader(open(DATA / "features_v2.csv", encoding="utf-8")))
    norm_feat, atk_feat = {}, {}
    for r in frows:
        if r["label"] == "0" and r["normal_condition"] == "staggered":
            norm_feat.setdefault(r["alias"], []).append(r)
        elif r["label"] == "1":
            atk_feat.setdefault(r["alias"], []).append(r)
    for d in (norm_feat, atk_feat):
        for a in d:
            d[a].sort(key=lambda r: r["created_at"])

    logins = list(csv.DictReader(open(DATA / "logins_v2.csv", encoding="utf-8")))
    attacks = list(csv.DictReader(open(DATA / "attacks_v2.csv", encoding="utf-8")))

    def mkev(r, split="normal"):
        sig = r["device_signature"].split("|")
        return V8.Event(
            profile_id=r["alias"],
            user_type=r.get("user_type", "student"),
            timestamp=parse(r["created_at"]),
            split=split,
            normal_scenario=r.get("normal_condition", "staggered"),
            subsystem=r["subsystem"],
            device_id=r["device_signature"],
            browser_family=sig[2] if len(sig) > 2 else "Other",
            os_name=sig[1] if len(sig) > 1 else "?",
            browser_version=bver(r),
            session_duration=float(r.get("duration_min", 0) or 0),
            scope_sensitivity=SCOPE.get(r["subsystem"], 0.1),
        )

    nby = {}
    for r in logins:
        if r["normal_condition"] == "staggered":
            nby.setdefault(r["alias"], []).append(r)
    for a in nby:
        nby[a].sort(key=lambda r: r["created_at"])

    train_ev, profiles = [], {}
    for a, rows in nby.items():
        k = int(len(rows) * 0.8)
        train_ev += [mkev(r, "train") for r in rows[:k]]
        tr = rows[:k]
        hrs = [parse(r["created_at"]).hour for r in tr]
        wk = [1 if parse(r["created_at"]).weekday() >= 5 else 0 for r in tr]
        try:
            typ = mode(hrs)
        except Exception:
            typ = 12
        profiles[a] = {
            "typical_hour": typ,
            "typical_weekend": round(sum(wk) / len(wk)),
            "session_count": len(tr),
        }
    baselines = V8.fit_profile_baselines(train_ev)
    evraw = {a: [mkev(r) for r in rows] for a, rows in nby.items()}

    aby = {}
    for r in attacks:
        aby.setdefault(r["alias"], []).append(r)
    for a in aby:
        aby[a].sort(key=lambda r: r["created_at"])

    def v8_prob(alias, win):
        return RT.probability(runtime, V8.neural_features(win, baselines[alias]))

    # ── recalibrate: ตั้ง threshold ใหม่จาก normal-train ของ V2 (calibration set แยกจาก test) ──
    import numpy as np

    ch_thr, wn_thr = runtime.challenge_threshold, runtime.warn_threshold
    if args.recalibrate:
        cal = []
        for a, rows in nby.items():
            k = int(len(rows) * 0.8)
            evs = evraw[a]
            for i in range(W - 1, k):  # เฉพาะ train (i < k) -> ไม่ leak test
                cal.append(v8_prob(a, evs[i - W + 1 : i + 1]))
        cal = np.array(cal)
        ch_thr = float(np.quantile(cal, 1 - args.cal_challenge_fpr))
        wn_thr = float(np.quantile(cal, 1 - args.cal_warn_fpr))
        print(
            f"recalibrate จาก normal-train V2 ({len(cal)} windows): "
            f"challenge {runtime.challenge_threshold:.4f}->{ch_thr:.4f} · "
            f"warn {runtime.warn_threshold:.4f}->{wn_thr:.4f}"
        )

    def v8_dec(alias, win):
        p = v8_prob(alias, win)
        if p >= ch_thr:
            return "challenge"
        if p >= wn_thr:
            return "warn"
        return "allow"

    results = []  # (label, scenario, base, combined)
    for a, frs in norm_feat.items():
        k = int(len(frs) * 0.8)
        evs = evraw[a]
        for i in range(k, len(frs)):
            f = [float(frs[i][x]) for x in FEATS]
            rule = evaluate_rules(f, db=None, user_id=a, ip=None, geo_country=None)
            base = aggregate(
                rule, evaluate_behavior(f, profiles.get(a)), NEUTRAL
            ).decision
            v8 = v8_dec(a, evs[i - W + 1 : i + 1]) if i >= W - 1 else "allow"
            results.append((0, "normal", base, maxd(base, v8)))

    for a, frs in atk_feat.items():
        base_rows = nby.get(a, [])
        arows = [r for r in aby.get(a, []) if r["row_kind"] == "attack"]
        for j, fr in enumerate(frs):
            f = [float(fr[x]) for x in FEATS]
            rule = evaluate_rules(f, db=None, user_id=a, ip=None, geo_country=None)
            base = aggregate(
                rule, evaluate_behavior(f, profiles.get(a)), NEUTRAL
            ).decision
            t = fr["created_at"]
            hist = [mkev(x) for x in base_rows if x["created_at"] < t]
            v8 = "allow"
            if len(hist) >= W - 1 and j < len(arows):
                v8 = v8_dec(a, hist[-(W - 1) :] + [mkev(arows[j])])
            results.append((1, fr["scenario"], base, maxd(base, v8)))

    def metrics(idx):
        atk = [r for r in results if r[0] == 1]
        nor = [r for r in results if r[0] == 0]
        tp = sum(is_ch(r[idx]) for r in atk)
        fp = sum(is_ch(r[idx]) for r in nor)
        return {
            "recall": tp / len(atk),
            "prec": tp / (tp + fp) if (tp + fp) else 0.0,
            "cfpr": fp / len(nor),
            "wfpr": sum(is_wn(r[idx]) for r in nor) / len(nor),
            "policy": sum(RANK[r[idx]] >= RANK[EXPECTED[r[1]]] for r in atk) / len(atk),
            "n_atk": len(atk),
            "n_nor": len(nor),
        }

    base_m, comb_m = metrics(2), metrics(3)
    print("=" * 64)
    print("ABLATION บนโปรไฟล์ V2 (12 คน anchor จริง, size 5000)")
    print(f"  normal test {base_m['n_nor']} · attack {base_m['n_atk']}\n")
    print(f"  {'':22}{'Rule+Behavior':>16}{'+ V8 MLP':>13}{'ต่าง':>8}")
    for key, label in [
        ("recall", "Recall"),
        ("policy", "Policy success"),
        ("cfpr", "Challenge FPR"),
        ("wfpr", "Warn FPR"),
        ("prec", "Precision"),
    ]:
        b, c = base_m[key], comb_m[key]
        print(f"  {label:22}{b:>15.1%}{c:>13.1%}{(c - b) * 100:>+7.1f}")

    print("\n  แยกตาม scenario (recall = challenge+):")
    print(f"  {'scenario':22}{'Rule+Beh':>10}{'+V8':>7}{'ช่วย':>7}")
    for scn in sorted(EXPECTED):
        g = [r for r in results if r[0] == 1 and r[1] == scn]
        if not g:
            continue
        rb = sum(is_ch(r[2]) for r in g) / len(g)
        cb = sum(is_ch(r[3]) for r in g) / len(g)
        mark = " <<<" if cb > rb + 0.01 else ""
        print(f"  {scn:22}{rb:>9.0%}{cb:>7.0%}{(cb - rb) * 100:>+6.0f}{mark}")


if __name__ == "__main__":
    main()
