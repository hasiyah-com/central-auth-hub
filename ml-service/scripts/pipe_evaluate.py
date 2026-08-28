"""ขั้น 6 — ประเมินประสิทธิภาพโมเดลรายคน.

ต่อ user: test = normal held-out (20% ท้าย จาก user_features) + anomalies ของคนนั้น
score ด้วย "โมเดลของคนนั้น" → predict (score ≥ threshold) → per-user P/R/F1
รวมทุกคน: P/R/F1/ROC-AUC/PR-AUC + detection แยกตาม anomaly_type
เทียบ per-user vs global (ถ้ามี global ใน joblib)

Output: พิมพ์ตาราง + เซฟรายงาน hub/backend/tests/reports/per_user_eval_<date>.md
Run: py ml-service/scripts/pipe_evaluate.py
"""

import csv
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import numpy as np
from joblib import load
from sklearn.metrics import (
    average_precision_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

DATA = Path(__file__).resolve().parents[1] / "data"
MODELS = Path(__file__).resolve().parents[1] / "models"
REPORT = (
    Path(__file__).resolve().parents[2]
    / "hub"
    / "backend"
    / "tests"
    / "reports"
    / f"per_user_eval_{date.today()}.md"
)


def load_rows(fp):
    d = defaultdict(list)
    for r in csv.DictReader(open(fp, encoding="utf-8")):
        d[r["email"]].append(r)
    return d


def main():
    mp = MODELS / "user_models.joblib"
    if not mp.exists():
        print(f"❌ ไม่พบ {mp} — รัน pipe_train.py ก่อน")
        return
    payload = load(mp)
    F = payload["features"]
    users = payload["users"]
    feats = load_rows(DATA / "user_features.csv")
    anoms = load_rows(DATA / "user_anomalies_features.csv")

    lines = [f"# รายงานประเมินโมเดลรายคน (Per-User RBA) — {date.today()}", ""]
    lines.append(
        f"{'user':<24}{'test_n':>7}{'atk':>5}{'Prec':>7}{'Recall':>8}{'F1':>7}{'ROC':>7}{'PR':>7}"
    )
    print(lines[-1])
    all_y, all_s = [], []
    type_hit, type_tot = Counter(), Counter()
    rows_md = []
    for email, um in users.items():
        rows = sorted(feats.get(email, []), key=lambda r: r["created_at"])
        test_norm = rows[um["test_from_index"] :]  # held-out normal
        test_anom = anoms.get(email, [])
        if not test_anom:
            continue
        X = np.array([[float(r[c]) for c in F] for r in (test_norm + test_anom)])
        y = np.array([0] * len(test_norm) + [1] * len(test_anom))
        s = -um["model"].score_samples(um["scaler"].transform(X))
        pred = (s >= um["threshold"]).astype(int)
        P = precision_score(y, pred, zero_division=0)
        R = recall_score(y, pred, zero_division=0)
        Fm = f1_score(y, pred, zero_division=0)
        roc = roc_auc_score(y, s) if y.sum() and (y == 0).any() else float("nan")
        pr = average_precision_score(y, s) if y.sum() else float("nan")
        line = f"{email.split('@')[0]:<24}{len(y):>7}{int(y.sum()):>5}{P:>7.3f}{R:>8.3f}{Fm:>7.3f}{roc:>7.3f}{pr:>7.3f}"
        print(line)
        rows_md.append(line)
        all_y += list(y)
        all_s += list(s)
        # detection แยก anomaly_type
        for r, p in zip(test_anom, pred[len(test_norm) :]):
            t = r.get("anomaly_type", "unknown")
            type_tot[t] += 1
            type_hit[t] += int(p)

    all_y, all_s = np.array(all_y), np.array(all_s)
    lines += ["```"] + rows_md + ["```", ""]
    lines.append("## รวมทุกคน")
    lines.append(
        f"- ROC-AUC = {roc_auc_score(all_y, all_s):.3f} | PR-AUC = {average_precision_score(all_y, all_s):.3f}"
    )
    lines.append("")
    lines.append("## Detection แยกตามชนิด anomaly")
    print("\nDetection แยกชนิด:")
    for t in sorted(type_tot):
        row = f"- {t:<20} {type_hit[t]}/{type_tot[t]}"
        print("  " + row.replace("- ", ""))
        lines.append(row)

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n✅ รายงาน → {REPORT}")


if __name__ == "__main__":
    main()
