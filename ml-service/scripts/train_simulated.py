"""เทรนโมเดลบน simulated_features_23.csv (anchor ผู้ใช้จริง, 2 บัญชีโดน ATO).

โปรโตคอลถูกต้อง (one-class):
  - 2 บัญชีที่โดนโจมตี → test ทั้งหมด
  - ผู้ใช้ปกติ → 80% train / 20% test
  - TRAIN = normal logins ของ train users เท่านั้น (เทรน "ปกติ")
  - เทรน IsolationForest (production Layer 3) + เทียบ OCSVM/LOF
  - เซฟ model + scaler + feature list -> ml-service/models/

Run: py ml-service/scripts/train_simulated.py
"""

import csv
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from joblib import dump
from sklearn.ensemble import IsolationForest
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.neighbors import LocalOutlierFactor
from sklearn.preprocessing import StandardScaler
from sklearn.svm import OneClassSVM

DATA = Path(__file__).resolve().parents[1] / "data" / "simulated_features_23.csv"
MODELS = Path(__file__).resolve().parents[1] / "models"
MODELS.mkdir(parents=True, exist_ok=True)

F = [
    "hour_of_day",
    "day_of_week",
    "hours_from_typical_login_time",
    "is_thailand",
    "is_new_country",
    "country_change_count_30d",
    "is_new_device",
    "is_new_user_agent_family",
    "log_minutes_since_last_login",
    "login_count_24h",
    "failed_logins_24h",
    "is_attack_ip",
    "active_session_count",
    "concurrent_session_count",
    "active_subsystem_count",
    "weekday_usage_score",
    "scope_sensitivity_score",
    "permission_change_age",
    "confirmed_incident_count",
    "passkey_count",
    "passkey_age_days",
    "new_passkey_recently_added",
    "passkey_last_used_days",
]


def main():
    rows = list(csv.DictReader(open(DATA, encoding="utf-8")))
    X = np.array([[float(r[c]) for c in F] for r in rows])
    y = np.array([int(r["label"]) for r in rows])
    email = np.array([r["email"] for r in rows])
    level = np.array([int(r["anomaly_level"]) for r in rows])
    print(
        f"dataset: {len(y)} rows | attack {int(y.sum())} ({y.mean()*100:.1f}%) | 23 feat"
    )

    # ── split: บัญชีที่โดนโจมตี → test; ปกติ → 80/20 ──
    user_atk = defaultdict(int)
    for e, l in zip(email, y):
        user_atk[e] |= l
    atk_users = set(u for u, a in user_atk.items() if a)
    norm_users = [u for u, a in user_atk.items() if not a]
    rng = np.random.default_rng(42)
    rng.shuffle(norm_users)
    k = int(len(norm_users) * 0.8)
    train_u, test_u = set(norm_users[:k]), set(norm_users[k:]) | atk_users
    tr = np.array([e in train_u for e in email]) & (y == 0)  # train = normal only
    te = np.array([e in test_u for e in email])
    print(
        f"   attacked users (->test): {len(atk_users)} | normal users: {len(norm_users)}"
    )
    print(
        f"   train(normal-only): {int(tr.sum())} | test: {int(te.sum())} (attack {int(y[te].sum())})"
    )

    # ── scale (fit จาก train เท่านั้น) ──
    scaler = StandardScaler().fit(X[tr])
    Xtr, Xte = scaler.transform(X[tr]), scaler.transform(X[te])
    yte = y[te]
    cont = 0.02

    # ── เทรน + เทียบ 3 โมเดล ──
    print(f"\n{'Model':<20}{'Prec':>7}{'Recall':>8}{'F1':>7}{'ROC':>8}{'PR':>7}")
    results = {}
    for name in ("IsolationForest", "OneClassSVM", "LocalOutlierFactor"):
        if name == "IsolationForest":
            m = IsolationForest(
                n_estimators=200, contamination=cont, random_state=42
            ).fit(Xtr)
            s_tr, s_te = -m.score_samples(Xtr), -m.score_samples(Xte)
        elif name == "OneClassSVM":
            m = OneClassSVM(nu=0.05, kernel="rbf", gamma="scale").fit(Xtr)
            s_tr, s_te = -m.score_samples(Xtr), -m.score_samples(Xte)
        else:
            m = LocalOutlierFactor(n_neighbors=20, novelty=True).fit(Xtr)
            s_tr, s_te = -m.score_samples(Xtr), -m.score_samples(Xte)
        thr = np.quantile(s_tr, 0.98)
        pred = (s_te >= thr).astype(int)
        P, R = (
            precision_score(yte, pred, zero_division=0),
            recall_score(yte, pred, zero_division=0),
        )
        Fm = f1_score(yte, pred, zero_division=0)
        roc, pr = roc_auc_score(yte, s_te), average_precision_score(yte, s_te)
        results[name] = (m, thr, P, R, Fm, roc, pr, pred)
        print(f"{name:<20}{P:>7.3f}{R:>8.3f}{Fm:>7.3f}{roc:>8.3f}{pr:>7.3f}")

    # ── การจับตามระดับ (IForest) ──
    m_if, thr_if, *_, pred_if = results["IsolationForest"]
    lvl_te = level[te]
    print("\nIForest จับได้ตามระดับ (บน test):")
    for lv in [0, 1, 3]:
        ix = np.where(lvl_te == lv)[0]
        if len(ix):
            tag = {0: "normal", 1: "เสี่ยง-ไม่โดน(label0)", 3: "attack"}[lv]
            print(f"  level {lv} ({tag}): flag {int(pred_if[ix].sum())}/{len(ix)}")
    print(f"  confusion (IForest):\n{confusion_matrix(yte, pred_if)}")

    # ── เซฟ production model (IsolationForest) ──
    dump(results["IsolationForest"][0], MODELS / "iforest_simulated.pkl")
    dump(scaler, MODELS / "scaler_simulated.pkl")
    meta = {
        "features": F,
        "n_features": len(F),
        "threshold": float(thr_if),
        "contamination": cont,
        "trained_on": "simulated_features_23.csv (anchor real users)",
        "train_rows": int(tr.sum()),
        "test_rows": int(te.sum()),
    }
    json.dump(
        meta,
        open(MODELS / "iforest_simulated_meta.json", "w"),
        ensure_ascii=False,
        indent=2,
    )
    print(f"\n✅ เซฟโมเดลแล้ว -> {MODELS}")
    print(
        "   iforest_simulated.pkl + scaler_simulated.pkl + iforest_simulated_meta.json"
    )


if __name__ == "__main__":
    main()
