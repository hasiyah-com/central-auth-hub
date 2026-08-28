"""ขั้น 4 — เทรนโมเดล "รายคน" ให้เรียนรู้พฤติกรรมของผู้ใช้แต่ละคน.

Per-user model: ต่อ user 1 คน → StandardScaler + IsolationForest fit บนฟีเจอร์ normal
ของ "คนนั้นเท่านั้น" (80% แรกตามเวลา = train, 20% ท้าย = held-out ไว้ให้ pipe_evaluate)
threshold = quantile 0.98 ของ train anomaly score

เก็บ models/user_models.joblib = {email: {scaler, model, threshold, n_train}} + features
(option: เทรน global IForest ไว้เทียบ — เปิดใช้ได้ด้วย TRAIN_GLOBAL=True)

Run: py ml-service/scripts/pipe_train.py
"""

import csv
from collections import defaultdict
from pathlib import Path

import numpy as np
from joblib import dump
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from pipe_featurelib import FEATURES

DATA = Path(__file__).resolve().parents[1] / "data"
MODELS = Path(__file__).resolve().parents[1] / "models"
MODELS.mkdir(parents=True, exist_ok=True)
SRC = DATA / "user_features.csv"
TRAIN_FRAC = 0.80
CONTAMINATION = 0.02
TRAIN_GLOBAL = True  # เทรน global model ไว้เทียบด้วย


def main():
    if not SRC.exists():
        print(f"❌ ไม่พบ {SRC} — รัน pipe_features.py ก่อน")
        return
    by_user = defaultdict(list)
    for r in csv.DictReader(open(SRC, encoding="utf-8")):
        by_user[r["email"]].append(r)

    user_models = {}
    print(f"{'user':<26}{'n_train':>8}{'n_test':>8}{'threshold':>11}")
    for email, rows in by_user.items():
        rows.sort(key=lambda r: r["created_at"])
        k = int(len(rows) * TRAIN_FRAC)
        Xtr = np.array([[float(r[c]) for c in FEATURES] for r in rows[:k]])
        scaler = StandardScaler().fit(Xtr)
        Xtr_s = scaler.transform(Xtr)
        model = IsolationForest(
            n_estimators=200, contamination=CONTAMINATION, random_state=42
        ).fit(Xtr_s)
        s_tr = -model.score_samples(Xtr_s)
        thr = float(np.quantile(s_tr, 0.98))
        user_models[email] = {
            "scaler": scaler,
            "model": model,
            "threshold": thr,
            "n_train": k,
            "test_from_index": k,
        }
        print(f"{email.split('@')[0]:<26}{k:>8}{len(rows) - k:>8}{thr:>11.4f}")

    payload = {
        "features": FEATURES,
        "train_frac": TRAIN_FRAC,
        "contamination": CONTAMINATION,
        "users": user_models,
    }

    if TRAIN_GLOBAL:
        allX = np.array(
            [[float(r[c]) for c in FEATURES] for rows in by_user.values() for r in rows]
        )
        gsc = StandardScaler().fit(allX)
        gm = IsolationForest(
            n_estimators=200, contamination=CONTAMINATION, random_state=42
        ).fit(gsc.transform(allX))
        gs = -gm.score_samples(gsc.transform(allX))
        payload["global"] = {
            "scaler": gsc,
            "model": gm,
            "threshold": float(np.quantile(gs, 0.98)),
        }

    dump(payload, MODELS / "user_models.joblib")
    print(
        f"\n✅ เทรนโมเดลรายคน {len(user_models)} ตัว"
        + (" + global 1 ตัว" if TRAIN_GLOBAL else "")
    )
    print(f"   → {MODELS / 'user_models.joblib'}")


if __name__ == "__main__":
    main()
