"""Train Isolation Forest จาก synthetic data — บันทึก model พร้อมใช้.

Run:
    docker compose exec ml-service python -m scripts.train_model

Output:
    /app/models/iforest_v1.pkl

ใช้ stratified train/test split 80/20:
  - train Isolation Forest บน train_normal เท่านั้น (unsupervised)
  - ประเมินบน train set (sanity check) และ test set (น่าเชื่อถือ)
  - รายงาน AUC, classification report, confusion matrix แยก train/test
  - เลือก threshold จาก test set ที่ Youden's J (TPR - FPR สูงสุด)
"""

import csv
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    roc_auc_score,
    roc_curve,
)
from sklearn.model_selection import train_test_split

DATA_PATH = Path("/app/data/sessions.csv")
# Phase 2.2 — feedback loop: real labeled data (export จาก hub: export_labeled_data.py)
# ถ้ามี → merge เข้า training (real normal ลด FPR; real attack ใช้ eval recall)
REAL_DATA_PATH = Path("/app/data/real_labeled.csv")
MODEL_DIR = Path("/app/models")
MODEL_DIR.mkdir(parents=True, exist_ok=True)
MODEL_PATH = MODEL_DIR / "iforest_v1.pkl"

RANDOM_STATE = 42
TEST_SIZE = 0.20


def _read_csv(path: Path) -> tuple[list, list]:
    X, y = [], []
    with open(path, encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader)  # header
        for row in reader:
            if not row:
                continue
            X.append([float(v) for v in row[:-1]])
            y.append(int(row[-1]))
    return X, y


def load_data() -> tuple[np.ndarray, np.ndarray]:
    if not DATA_PATH.exists():
        raise FileNotFoundError(f"ไม่พบ {DATA_PATH} — รัน scripts/generate_data ก่อน")
    X, y = _read_csv(DATA_PATH)

    # Phase 2.2 — merge real labeled data ถ้ามี (feedback loop)
    if REAL_DATA_PATH.exists():
        Xr, yr = _read_csv(REAL_DATA_PATH)
        if Xr and len(Xr[0]) == len(X[0]):  # feature count ต้องตรง (B49)
            X += Xr
            y += yr
            print(
                f"🔁 feedback loop: merge real labeled {len(Xr)} แถว "
                f"(normal={yr.count(0)}, attack={yr.count(1)})"
            )
        else:
            print(
                f"⚠️ real_labeled.csv feature count ไม่ตรง — ข้าม (synthetic={len(X[0])})"
            )

    return np.array(X), np.array(y)


def report_split(
    name: str, y_true: np.ndarray, pred_label: np.ndarray, scores: np.ndarray
) -> None:
    print(f"\n=========== {name} ===========")
    print(
        f"  samples: {len(y_true)}  (normal={int((y_true == 0).sum())}, anomaly={int((y_true == 1).sum())})"
    )

    print("\n--- Classification Report ---")
    print(
        classification_report(
            y_true, pred_label, target_names=["normal", "anomaly"], zero_division=0
        )
    )

    cm = confusion_matrix(y_true, pred_label)
    print("Confusion Matrix:")
    print("               pred_normal  pred_anomaly")
    print(f"true_normal    {cm[0][0]:>10}    {cm[0][1]:>10}")
    print(f"true_anomaly   {cm[1][0]:>10}    {cm[1][1]:>10}")

    try:
        auc = roc_auc_score(y_true, scores)
        print(f"\nAUC-ROC: {auc:.4f}")
    except ValueError:
        pass


def suggest_threshold(y_true: np.ndarray, scores: np.ndarray) -> None:
    """หา threshold ที่ Youden's J (TPR - FPR) สูงสุดบน test set.

    หมายเหตุ: คะแนนนี้คือ -decision_function (สูง = anomalous) ของ sklearn
    ไม่ใช่ score 0-1 ที่ ML service คืน (sigmoid scaled). ใช้เป็น guideline
    สำหรับ tune THRESHOLD_BLOCK/THRESHOLD_MFA ใน main.py
    """
    try:
        fpr, tpr, thr = roc_curve(y_true, scores)
    except ValueError:
        return
    j = tpr - fpr
    idx = int(np.argmax(j))
    print("\n--- Threshold Suggestion (Youden's J on raw -decision_function) ---")
    print(f"  best raw threshold = {thr[idx]:.4f}")
    print(f"  TPR (recall)       = {tpr[idx]:.4f}")
    print(f"  FPR                = {fpr[idx]:.4f}")
    print("  (ใช้ปรับ THRESHOLD_BLOCK/THRESHOLD_MFA ใน app/main.py ได้)")


def main():
    print("📊 โหลด data ...")
    X, y = load_data()
    print(f"   total:   {len(X)} samples")
    print(f"   normal:  {(y == 0).sum()}")
    print(f"   anomaly: {(y == 1).sum()}")

    # Stratified split — รักษาสัดส่วน normal/anomaly ทั้ง train + test
    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=TEST_SIZE,
        stratify=y,
        random_state=RANDOM_STATE,
    )
    print(f"\n🔀 Split (stratified) — test_size={TEST_SIZE}")
    print(
        f"   train: {len(X_train)}  (normal={(y_train == 0).sum()}, anomaly={(y_train == 1).sum()})"
    )
    print(
        f"   test:  {len(X_test)}  (normal={(y_test == 0).sum()}, anomaly={(y_test == 1).sum()})"
    )

    # Train Isolation Forest — unsupervised, ใช้ normal ของ train set เท่านั้น
    print("\n🤖 Train Isolation Forest (บน train_normal เท่านั้น) ...")
    X_train_normal = X_train[y_train == 0]
    model = IsolationForest(
        n_estimators=100,
        contamination=0.05,  # คาดว่าใน production จะมี anomaly ~5%
        max_samples=256,
        random_state=RANDOM_STATE,
        n_jobs=-1,
    )
    model.fit(X_train_normal)

    # ประเมิน TRAIN (sanity check — ดูว่า model fit ได้)
    train_pred = (model.predict(X_train) == -1).astype(int)
    train_scores = -model.decision_function(X_train)
    report_split("TRAIN", y_train, train_pred, train_scores)

    # ประเมิน TEST (เลขที่น่าเชื่อถือ)
    test_pred = (model.predict(X_test) == -1).astype(int)
    test_scores = -model.decision_function(X_test)
    report_split("TEST (held-out)", y_test, test_pred, test_scores)

    # แนะนำ threshold จาก test set
    suggest_threshold(y_test, test_scores)

    # บันทึก model
    joblib.dump(model, MODEL_PATH)
    print(f"\n💾 บันทึก model: {MODEL_PATH}")
    print("✅ Done — เรียก /v1/score ได้แล้ว")


if __name__ == "__main__":
    main()
