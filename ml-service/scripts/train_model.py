"""Train Isolation Forest จาก synthetic data — บันทึก model พร้อมใช้.

Run:
    docker compose exec ml-service python -m scripts.train_model

Output:
    /app/models/iforest_v1.pkl
"""
import csv
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.metrics import classification_report, roc_auc_score, confusion_matrix

DATA_PATH = Path("/app/data/sessions.csv")
MODEL_DIR = Path("/app/models")
MODEL_DIR.mkdir(parents=True, exist_ok=True)
MODEL_PATH = MODEL_DIR / "iforest_v1.pkl"


def load_data() -> tuple[np.ndarray, np.ndarray]:
    if not DATA_PATH.exists():
        raise FileNotFoundError(
            f"ไม่พบ {DATA_PATH} — รัน scripts/generate_data ก่อน"
        )
    X, y = [], []
    with open(DATA_PATH, encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader)   # header
        for row in reader:
            X.append([float(v) for v in row[:-1]])
            y.append(int(row[-1]))
    return np.array(X), np.array(y)


def main():
    print("📊 โหลด data ...")
    X, y = load_data()
    print(f"   total: {len(X)} samples")
    print(f"   normal:  {(y == 0).sum()}")
    print(f"   anomaly: {(y == 1).sum()}")

    # train เฉพาะข้อมูลปกติ (unsupervised — โมเดลเรียนรู้ว่า 'ปกติ' คืออะไร)
    print("\n🤖 Train Isolation Forest ...")
    X_normal = X[y == 0]
    model = IsolationForest(
        n_estimators=100,
        contamination=0.05,    # คาดว่าใน production จะมี anomaly ~5%
        max_samples=256,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X_normal)

    # ประเมินบน dataset เต็ม (มี label)
    print("\n📈 ประเมินผล ...")
    pred = model.predict(X)             # 1 = normal, -1 = anomaly
    pred_label = (pred == -1).astype(int)
    scores = -model.decision_function(X)  # invert -> high = anomalous

    print("\n--- Classification Report ---")
    print(classification_report(y, pred_label, target_names=["normal", "anomaly"]))

    cm = confusion_matrix(y, pred_label)
    print("Confusion Matrix:")
    print(f"               pred_normal  pred_anomaly")
    print(f"true_normal    {cm[0][0]:>10}    {cm[0][1]:>10}")
    print(f"true_anomaly   {cm[1][0]:>10}    {cm[1][1]:>10}")

    try:
        auc = roc_auc_score(y, scores)
        print(f"\nAUC-ROC: {auc:.4f}")
    except ValueError:
        pass

    # บันทึก
    joblib.dump(model, MODEL_PATH)
    print(f"\n💾 บันทึก model: {MODEL_PATH}")
    print("✅ Done — เรียก /score ได้แล้ว")


if __name__ == "__main__":
    main()
