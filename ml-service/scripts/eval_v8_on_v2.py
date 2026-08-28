"""ทดสอบ V8 (Temporal MLP) บนชุด V2 ที่มันไม่เคยเห็น — external held-out test.

FAIR: import โค้ด V8 เอง (Event, fit_profile_baselines, neural_features) มาสร้าง
64-vector จากข้อมูล V2 -> ไม่มี mapping error ของผม (ต่างจาก V7 ที่ผมแมป field เอง)

เงื่อนไข: V8 abstain เมื่อ < 1000 event -> ใช้ข้อมูล V2 size 5000 (ทุกคน >= 1000)
โปรโตคอล: normal 80/20 ต่อคน · fit baseline บน train · attack frozen · window=6

Run:
    py ml-service/scripts/eval_v8_on_v2.py --v8 <path>/experiments/rba_user_learning_curve
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

DATA = Path(__file__).resolve().parents[1] / "data"
TS = "%Y-%m-%d %H:%M:%S"
SCOPE = {"HUB": 0.0, "SUB_A": 0.8, "SUB_B": 0.6}
EXPECTED = {
    "combined_ato": "challenge",
    "concurrent_sessions": "challenge",
    "failed_spike": "challenge",
    "login_velocity": "challenge",
    "new_device": "challenge",
    "new_os": "warn",
    "new_passkey": "challenge",
    "new_ua_family": "challenge",
    "off_hours": "warn",
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--v8",
        required=True,
        type=Path,
        help="โฟลเดอร์ experiments/rba_user_learning_curve",
    )
    args = ap.parse_args()
    sys.path.insert(0, str(args.v8 / "scripts"))
    import run_temporal_mlp_v8 as V8
    import shadow_temporal_runtime_v8 as RT

    runtime = RT.load_runtime(args.v8 / "results" / "temporal_mlp_v8")
    W = V8.WINDOW
    print(
        f"V8 โหลดแล้ว — window {W} · challenge {runtime.challenge_threshold:.4f} · warn {runtime.warn_threshold:.4f}"
    )

    def mkevent(row, split="normal"):
        sig = row["device_signature"].split("|")  # device|os|family
        return V8.Event(
            profile_id=row["alias"],
            user_type=row.get("user_type", "student"),
            timestamp=parse(row["created_at"]),
            split=split,
            normal_scenario=row.get("normal_condition", "staggered"),
            subsystem=row["subsystem"],
            device_id=row["device_signature"],
            browser_family=sig[2] if len(sig) > 2 else "Other",
            os_name=sig[1] if len(sig) > 1 else "?",
            browser_version=bver(row),
            session_duration=float(row.get("duration_min", 0) or 0),
            scope_sensitivity=SCOPE.get(row["subsystem"], 0.1),
        )

    logins = list(csv.DictReader(open(DATA / "logins_v2.csv", encoding="utf-8")))
    attacks = list(csv.DictReader(open(DATA / "attacks_v2.csv", encoding="utf-8")))

    # normal staggered ต่อคน -> Event เรียงเวลา
    by_user = {}
    for r in logins:
        if r["normal_condition"] == "staggered":
            by_user.setdefault(r["alias"], []).append(r)
    for a in by_user:
        by_user[a].sort(key=lambda r: r["created_at"])

    train_ev, test_win = [], []
    for a, rows in by_user.items():
        k = int(len(rows) * 0.8)
        train_ev += [mkevent(r, "train") for r in rows[:k]]
        ev = [mkevent(r) for r in rows]
        for i in range(max(k, W - 1), len(ev)):  # test = 20% ท้าย
            test_win.append((a, "normal", ev[i - W + 1 : i + 1]))

    baselines = V8.fit_profile_baselines(train_ev)

    # attack frozen — 5 normal history ก่อนหน้า + attack
    atk_by = {}
    for r in attacks:
        atk_by.setdefault(r["alias"], []).append(r)
    atk_win = []
    for a, rows in atk_by.items():
        rows.sort(key=lambda r: r["created_at"])
        base = by_user.get(a, [])
        for r in rows:
            if r["row_kind"] != "attack":
                continue
            t = r["created_at"]
            hist = [mkevent(x) for x in base if x["created_at"] < t]
            if len(hist) < W - 1:
                continue
            win = hist[-(W - 1) :] + [mkevent(r)]
            atk_win.append((a, r["scenario"], win))

    def score(win_alias, win):
        vec = V8.neural_features(win, baselines[win_alias])
        return RT.probability(runtime, vec)

    rows = []
    for a, sc, win in test_win:
        rows.append({"alias": a, "scenario": sc, "label": 0, "p": score(a, win)})
    for a, sc, win in atk_win:
        rows.append({"alias": a, "scenario": sc, "label": 1, "p": score(a, win)})

    n = [r for r in rows if r["label"] == 0]
    at = [r for r in rows if r["label"] == 1]
    print(f"windows: normal {len(n)} · attack {len(at)}\n")

    def decide(p):
        return (
            "challenge"
            if p >= runtime.challenge_threshold
            else ("warn" if p >= runtime.warn_threshold else "allow")
        )

    RANK = {"allow": 0, "warn": 1, "challenge": 2}
    ch = lambda r: RANK[decide(r["p"])] >= 2
    tp, fp = sum(ch(r) for r in at), sum(ch(r) for r in n)
    recall = tp / len(at)
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    f1 = 2 * prec * recall / (prec + recall) if (prec + recall) else 0.0
    try:
        from sklearn.metrics import average_precision_score, roc_auc_score

        y = [r["label"] for r in rows]
        s = [r["p"] for r in rows]
        roc, pr = roc_auc_score(y, s), average_precision_score(y, s)
    except Exception:
        roc = pr = float("nan")

    print("=" * 60)
    print("V8 Temporal MLP บนชุด V2 (external, threshold ของ V8 เอง)")
    print(f"  Recall {recall:.1%} | Precision {prec:.1%} | F1 {f1:.3f}")
    print(
        f"  Challenge FPR {fp/len(n):.2%} ({fp}/{len(n)}) | ROC-AUC {roc:.3f} | PR-AUC {pr:.3f}"
    )
    print(
        f"  prob เฉลี่ย: normal {np.mean([r['p'] for r in n]):.3f} vs attack {np.mean([r['p'] for r in at]):.3f}"
    )

    pn = np.array([r["p"] for r in n])
    pa = np.array([r["p"] for r in at])
    print("\n  threshold sweep:")
    for t in [
        0.1,
        0.2,
        0.3,
        runtime.warn_threshold,
        0.5,
        runtime.challenge_threshold,
        0.7,
        0.8,
    ]:
        r_ = (pa >= t).sum() / len(pa)
        f_ = (pn >= t).sum() / len(pn)
        print(f"    thr {t:.3f}  recall {r_:.1%}  FPR {f_:.1%}")

    print("\n  แยกตาม scenario (challenge+):")
    for scn in sorted(EXPECTED):
        g = [r for r in at if r["scenario"] == scn]
        if g:
            print(
                f"    {scn:22} recall {sum(ch(r) for r in g)/len(g):>6.1%}  mean_p {np.mean([r['p'] for r in g]):.3f}"
            )


if __name__ == "__main__":
    main()
