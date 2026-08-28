"""Train + Evaluate บนชุด persona-grounded (train_grounded / test_grounded).

เทรน Isolation Forest ด้วย **train_grounded.csv** (normal เท่านั้น — unsupervised)
แล้ววัดประสิทธิภาพบน **test_grounded.csv** (normal ขนาดเท่า train + anomaly แทรก)

วัด:
  - Precision / Recall / F1 / ROC-AUC (รวม)
  - **Recall แยกตาม attacker model** (very_naive / naive / vpn / targeted)
  - **FPR** (normal โดน flag ผิด)

**ไม่ทับ** production model — บันทึกเป็น `iforest_grounded.pkl` แยกต่างหาก

Run:
    # 1. สร้างข้อมูล (hub-backend) แล้ว copy มา ml-service:
    docker compose exec hub-backend python -m scripts.generate_grounded_data
    docker compose cp hub-backend:/app/tests/reports/train_grounded.csv - | \\
        docker compose cp - ml-service:/app/data/train_grounded.csv
    # (หรือใช้ scripts.sync ที่จัดไว้)
    # 2. train + eval:
    docker compose exec ml-service python -m scripts.train_eval_grounded
"""

import csv
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.metrics import (
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

DATA_DIR = Path("/app/data")
TRAIN = DATA_DIR / "train_grounded.csv"
TEST = DATA_DIR / "test_grounded.csv"
MODEL_OUT = Path("/app/models/iforest_grounded.pkl")

N_ESTIMATORS = 100
CONTAMINATION = 0.02
RANDOM_STATE = 42

# decision_function threshold: -0.0 = ค่า default ของ sklearn (score < 0 → anomaly)
# ปรับได้ถ้าต้องการ trade-off recall/FPR ต่างออกไป
ANOMALY_THRESHOLD = 0.0


def _read(path: Path, has_model_col: bool):
    """คืน (X, y, models)."""
    X, y, models = [], [], []
    with open(path, encoding="utf-8") as f:
        r = csv.reader(f)
        header = next(r)
        n_extra = 2 if has_model_col else 1
        n_feat = len(header) - n_extra
        for row in r:
            if not row:
                continue
            X.append([float(v) for v in row[:n_feat]])
            y.append(int(row[n_feat]))
            models.append(row[n_feat + 1] if has_model_col else "normal")
    return np.array(X), np.array(y), models


def _bar(v: float, width: int = 24) -> str:
    n = int(round(max(0.0, min(1.0, v)) * width))
    return "█" * n + "·" * (width - n)


def main() -> None:
    if not TRAIN.exists() or not TEST.exists():
        print(f"❌ ไม่พบ {TRAIN} หรือ {TEST}")
        print("   รัน scripts.generate_grounded_data (hub-backend) + copy มาก่อน")
        return

    X_train, y_train, _ = _read(TRAIN, has_model_col=False)
    X_test, y_test, models = _read(TEST, has_model_col=True)

    n_norm_tr = int((y_train == 0).sum())
    print(f"📥 train: {len(X_train):,} (normal={n_norm_tr:,})")
    print(
        f"📥 test : {len(X_test):,} (normal={(y_test == 0).sum():,}, "
        f"anomaly={(y_test == 1).sum():,})"
    )

    # ── เทรนด้วย normal เท่านั้น (unsupervised) ──
    X_fit = X_train[y_train == 0]
    model = IsolationForest(
        n_estimators=N_ESTIMATORS,
        contamination=CONTAMINATION,
        random_state=RANDOM_STATE,
        n_jobs=-1,
    )
    model.fit(X_fit)

    # ── ประเมินบน test ──
    raw = -model.decision_function(X_test)  # ยิ่งสูง = ยิ่งผิดปกติ
    pred = (raw > ANOMALY_THRESHOLD).astype(int)

    prec = precision_score(y_test, pred, zero_division=0)
    rec = recall_score(y_test, pred, zero_division=0)
    f1 = f1_score(y_test, pred, zero_division=0)
    auc = roc_auc_score(y_test, raw)

    tp = int(((pred == 1) & (y_test == 1)).sum())
    fp = int(((pred == 1) & (y_test == 0)).sum())
    tn = int(((pred == 0) & (y_test == 0)).sum())
    fn = int(((pred == 0) & (y_test == 1)).sum())
    n_norm = int((y_test == 0).sum())
    fpr = fp / n_norm if n_norm else 0.0

    print("\n" + "=" * 70)
    print("Persona-Grounded Evaluation — Isolation Forest")
    print("=" * 70)
    print("\n--- Overall (test) ---")
    print(f"  Precision : {prec:.4f}")
    print(f"  Recall    : {rec:.4f}")
    print(f"  F1        : {f1:.4f}")
    print(f"  ROC-AUC   : {auc:.4f}")
    print(f"  FPR       : {fp}/{n_norm} = {fpr * 100:.1f}%")

    print("\n  Confusion Matrix:")
    print("                pred_normal  pred_anomaly")
    print(f"  true_normal   {tn:>11}  {fp:>12}")
    print(f"  true_anomaly  {fn:>11}  {tp:>12}")

    # ── recall แยกตาม attacker model ──
    print("\n--- Recall แยกตาม attacker model (ยิ่งล่างยิ่งจับยาก) ---")
    order = ["very_naive", "naive", "vpn", "targeted"]
    per = {m: {"n": 0, "det": 0} for m in order}
    for i, m in enumerate(models):
        if m in per:
            per[m]["n"] += 1
            per[m]["det"] += int(pred[i] == 1)
    recalls = []
    print(f"  {'model':<14}{'n':>5}{'detected':>10}{'recall':>9}")
    for m in order:
        st = per[m]
        if not st["n"]:
            continue
        r = st["det"] / st["n"] * 100
        recalls.append(r)
        print(f"  {m:<14}{st['n']:>5}{st['det']:>10}{r:>8.1f}%   {_bar(r / 100)}")

    if len(recalls) >= 2:
        mono = all(recalls[i] >= recalls[i + 1] for i in range(len(recalls) - 1))
        print(
            f"\n  {'✅' if mono else '⚠️'} recall "
            f"{'ลดลงตามระดับผู้โจมตี (ตามที่คาด)' if mono else 'ไม่ลดตามลำดับ — ทบทวน'}"
        )

    joblib.dump(model, MODEL_OUT)
    print(f"\n💾 model → {MODEL_OUT} (แยกจาก production iforest_v1.pkl)")
    print("\n📌 หมายเหตุ: train/test เป็น persona-grounded synthetic")
    print("   (normal อิงชั่วโมง/วันของผู้ใช้จริง 7 คน + ช่วงค่าอิงงานวิจัย;")
    print("    anomaly = attacker model 4 ระดับ) — ระบุใน methodology")
    print("=" * 70)


if __name__ == "__main__":
    main()
