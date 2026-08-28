"""Learning Curve — หาว่าต้องใช้ข้อมูลเทรนกี่แถวถึง "พอ".

═══════════════════════════════════════════════════════════════════════════
คำถามที่ตอบ
═══════════════════════════════════════════════════════════════════════════
"ชุดข้อมูลสำหรับเทรนต้องมีกี่แถว ถึงจะแยกพฤติกรรมปกติ/ผิดปกติได้แม่นยำ?"

**วิธี:** เทรนโมเดลด้วยจำนวนข้อมูลเพิ่มขึ้นทีละขั้น แล้ววัด Precision / Recall / F1 /
ROC-AUC บน **test set ชุดเดียวกันตลอด** → ถ้าค่าเริ่มนิ่ง (plateau) = ข้อมูลพอแล้ว

ขนาดที่ทดสอบ: 1,000 → 3,000 → 5,000 → 7,000 → 10,000 → 14,000

═══════════════════════════════════════════════════════════════════════════
หลักการออกแบบที่สำคัญ (ทำให้ผลเชื่อถือได้)
═══════════════════════════════════════════════════════════════════════════
1. **Test set คงที่ทุกขนาด** — ถ้าเปลี่ยน test set ไปด้วย จะเทียบกันไม่ได้
2. **Nested subsample** — ชุด 1,000 เป็น subset ของ 3,000, 3,000 ⊂ 5,000 ...
   → ลด noise จากการสุ่มคนละชุด ทำให้เส้นโค้งเรียบ
3. **เฉลี่ยหลาย seed** (`--repeats`) — กันบังเอิญสุ่มได้ชุดที่ดี/แย่เป็นพิเศษ
4. **นับเฉพาะ normal** — Isolation Forest เทรนแบบ unsupervised ด้วย normal เท่านั้น
   (`fit(X_train_normal)`) ตัวเลข 1,000–14,000 จึงหมายถึง **จำนวน normal ที่ใช้เทรน**

═══════════════════════════════════════════════════════════════════════════
⚠️ ข้อจำกัดที่ต้องระบุในเล่ม
═══════════════════════════════════════════════════════════════════════════
ข้อมูลที่ใช้เป็น **synthetic** (สร้างจาก generate_data.py) — learning curve นี้จึงตอบว่า
"ต้องใช้กี่แถวเพื่อเรียนรู้ *การกระจายตัวแบบสังเคราะห์* ได้ครบ" ไม่ใช่ "แม่นยำกับ
traffic จริงแค่ไหน" (อันหลังวัดที่ evaluate_real_logins / evaluate_attack_set)

═══════════════════════════════════════════════════════════════════════════
Run
═══════════════════════════════════════════════════════════════════════════
    docker compose exec ml-service python -m scripts.learning_curve

    # ปรับขนาด/จำนวนรอบ
    docker compose exec ml-service python -m scripts.learning_curve \\
        --sizes 1000,3000,5000,7000,10000,14000 --repeats 3

**ไม่แตะ** `sessions.csv` / `iforest_v1.pkl` ของ production — สร้าง pool แยกต่างหาก
"""

import argparse
import csv
import random
import statistics
from pathlib import Path

import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.metrics import (
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

from app.features import FEATURE_NAMES
from scripts.generate_data import anomaly_session, normal_session

DATA_DIR = Path("/app/data")
POOL_PATH = DATA_DIR / "learning_curve_pool.csv"
REPORT_PATH = Path("/app/data/learning_curve_result.csv")

# ต้องมี normal มากกว่าขนาดสูงสุด + test set
POOL_NORMAL = 20_000
POOL_ANOMALY = 1_000
TEST_NORMAL = 4_000
TEST_ANOMALY = 400

# พารามิเตอร์โมเดล — ตรงกับ train_model.py (เทียบผลกันได้)
N_ESTIMATORS = 100
CONTAMINATION = 0.02
BASE_SEED = 42

DEFAULT_SIZES = [1_000, 3_000, 5_000, 7_000, 10_000, 14_000]
# เกณฑ์ตัดสินว่า "นิ่งแล้ว" — เปลี่ยนแปลงน้อยกว่านี้ถือว่า plateau
PLATEAU_EPS = 0.01


def _build_pool(force: bool = False) -> None:
    """สร้าง pool ขนาดใหญ่ (ครั้งเดียว) — ไม่แตะ sessions.csv ของ production."""
    if POOL_PATH.exists() and not force:
        print(f"♻️  ใช้ pool เดิม: {POOL_PATH}")
        return
    print(f"🔨 สร้าง pool ใหม่: normal={POOL_NORMAL:,} anomaly={POOL_ANOMALY:,}")
    random.seed(BASE_SEED)
    rows = [normal_session() + [0] for _ in range(POOL_NORMAL)]
    rows += [anomaly_session() + [1] for _ in range(POOL_ANOMALY)]
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(POOL_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(FEATURE_NAMES + ["label"])
        w.writerows(rows)
    print(f"   ✅ {POOL_PATH}  ({len(rows):,} rows)")


def _load_pool() -> tuple[np.ndarray, np.ndarray]:
    X, y = [], []
    with open(POOL_PATH, encoding="utf-8") as f:
        r = csv.reader(f)
        next(r)
        for row in r:
            if row:
                X.append([float(v) for v in row[:-1]])
                y.append(int(row[-1]))
    return np.array(X), np.array(y)


def _evaluate(model, X_test, y_test) -> dict:
    """คืน precision / recall / f1 / roc_auc บน test set."""
    pred = (model.predict(X_test) == -1).astype(int)  # -1 = anomaly → 1
    scores = -model.decision_function(X_test)  # ยิ่งสูง = ยิ่งผิดปกติ
    return {
        "precision": precision_score(y_test, pred, zero_division=0),
        "recall": recall_score(y_test, pred, zero_division=0),
        "f1": f1_score(y_test, pred, zero_division=0),
        "roc_auc": roc_auc_score(y_test, scores),
    }


def _bar(v: float, width: int = 20) -> str:
    n = int(round(max(0.0, min(1.0, v)) * width))
    return "█" * n + "·" * (width - n)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--sizes",
        type=str,
        default=",".join(str(s) for s in DEFAULT_SIZES),
        help="ขนาด training set (normal) คั่นด้วย comma",
    )
    ap.add_argument(
        "--repeats",
        type=int,
        default=3,
        help="จำนวนรอบต่อขนาด (เฉลี่ยเพื่อลด noise, default 3)",
    )
    ap.add_argument(
        "--regen-pool", action="store_true", help="สร้าง pool ใหม่ (ปกติใช้ของเดิม)"
    )
    args = ap.parse_args()

    sizes = sorted(int(s.strip()) for s in args.sizes.split(",") if s.strip())
    _build_pool(force=args.regen_pool)
    X, y = _load_pool()

    # ── แยก test set คงที่ (ใช้ชุดเดียวกันทุกขนาด — สำคัญมาก) ──
    rng = np.random.RandomState(BASE_SEED)
    idx_norm = np.where(y == 0)[0]
    idx_anom = np.where(y == 1)[0]
    rng.shuffle(idx_norm)
    rng.shuffle(idx_anom)

    test_idx = np.concatenate([idx_norm[:TEST_NORMAL], idx_anom[:TEST_ANOMALY]])
    pool_train_norm = idx_norm[TEST_NORMAL:]  # normal ที่เหลือไว้เทรน
    X_test, y_test = X[test_idx], y[test_idx]

    max_size = max(sizes)
    if len(pool_train_norm) < max_size:
        print(f"❌ pool normal ไม่พอ (มี {len(pool_train_norm):,} ต้องการ {max_size:,})")
        print("   → เพิ่ม POOL_NORMAL แล้วรันด้วย --regen-pool")
        return

    print(f"\n📊 Test set (คงที่ทุกขนาด): normal={TEST_NORMAL:,} anomaly={TEST_ANOMALY:,}")
    print(f"   Train pool (normal): {len(pool_train_norm):,}")
    print(f"   ขนาดที่ทดสอบ: {', '.join(f'{s:,}' for s in sizes)}")
    print(f"   รอบต่อขนาด: {args.repeats} (เฉลี่ย)\n")

    results: list[dict] = []
    for size in sizes:
        runs = []
        for rep in range(args.repeats):
            # nested subsample: shuffle ด้วย seed ต่อรอบ แล้วตัดหัว `size` ตัว
            # → ชุดเล็กเป็น subset ของชุดใหญ่ในรอบเดียวกัน (เส้นโค้งเรียบ)
            r = np.random.RandomState(BASE_SEED + rep)
            order = pool_train_norm.copy()
            r.shuffle(order)
            X_train = X[order[:size]]

            model = IsolationForest(
                n_estimators=N_ESTIMATORS,
                contamination=CONTAMINATION,
                random_state=BASE_SEED + rep,
                n_jobs=-1,
            )
            model.fit(X_train)
            runs.append(_evaluate(model, X_test, y_test))

        avg = {k: statistics.mean(r[k] for r in runs) for k in runs[0]}
        sd = {
            k: (statistics.stdev([r[k] for r in runs]) if len(runs) > 1 else 0.0)
            for k in runs[0]
        }
        results.append(
            {"size": size, **avg, "sd_f1": sd["f1"], "sd_auc": sd["roc_auc"]}
        )
        print(
            f"  n={size:>6,}  P={avg['precision']:.4f}  R={avg['recall']:.4f}  "
            f"F1={avg['f1']:.4f}  AUC={avg['roc_auc']:.4f}"
        )

    # ── ตารางสรุป + delta ──
    print("\n" + "=" * 78)
    print("Learning Curve — Isolation Forest (synthetic data)")
    print("=" * 78)
    print(
        f"{'train n':>8} {'Precision':>10} {'Recall':>9} {'F1':>9} {'ROC-AUC':>9}"
        f" {'ΔF1':>8} {'ΔAUC':>8}"
    )
    print("-" * 78)
    for i, r in enumerate(results):
        if i == 0:
            d_f1 = d_auc = None
        else:
            d_f1 = r["f1"] - results[i - 1]["f1"]
            d_auc = r["roc_auc"] - results[i - 1]["roc_auc"]
        d_f1_s = "  —" if d_f1 is None else f"{d_f1:+.4f}"
        d_auc_s = "  —" if d_auc is None else f"{d_auc:+.4f}"
        print(
            f"{r['size']:>8,} {r['precision']:>10.4f} {r['recall']:>9.4f} "
            f"{r['f1']:>9.4f} {r['roc_auc']:>9.4f} {d_f1_s:>8} {d_auc_s:>8}"
        )

    # ── กราฟ ASCII (F1 + AUC) ──
    print("\n--- F1 ---")
    for r in results:
        print(f"  {r['size']:>6,}  {_bar(r['f1'])} {r['f1']:.4f}")
    print("\n--- ROC-AUC ---")
    for r in results:
        print(f"  {r['size']:>6,}  {_bar(r['roc_auc'])} {r['roc_auc']:.4f}")

    # ── หาจุดที่ค่าเริ่มนิ่ง ──
    print("\n--- จุดที่ค่าเริ่มนิ่ง (plateau) ---")
    print(f"  เกณฑ์: |ΔF1| < {PLATEAU_EPS} และ |ΔAUC| < {PLATEAU_EPS}")
    plateau_at = None
    for i in range(1, len(results)):
        d_f1 = abs(results[i]["f1"] - results[i - 1]["f1"])
        d_auc = abs(results[i]["roc_auc"] - results[i - 1]["roc_auc"])
        if d_f1 < PLATEAU_EPS and d_auc < PLATEAU_EPS:
            plateau_at = results[i - 1]["size"]
            break
    if plateau_at:
        print(f"  ✅ ค่านิ่งตั้งแต่ n ≈ {plateau_at:,}")
        print("     → เพิ่มข้อมูลเกินนี้ไม่ช่วยให้ดีขึ้นอย่างมีนัยสำคัญ")
    else:
        print("  ⚠️ ยังไม่นิ่งในช่วงที่ทดสอบ — ควรลองขนาดใหญ่กว่านี้")

    # ── บันทึก CSV ──
    with open(REPORT_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            ["train_n", "precision", "recall", "f1", "roc_auc", "sd_f1", "sd_roc_auc"]
        )
        for r in results:
            w.writerow(
                [
                    r["size"],
                    f"{r['precision']:.6f}",
                    f"{r['recall']:.6f}",
                    f"{r['f1']:.6f}",
                    f"{r['roc_auc']:.6f}",
                    f"{r['sd_f1']:.6f}",
                    f"{r['sd_auc']:.6f}",
                ]
            )
    print(f"\n💾 บันทึกผล → {REPORT_PATH}")
    print("\n📌 หมายเหตุ: ข้อมูล synthetic — ตอบว่า 'กี่แถวพอสำหรับเรียนรู้การกระจายตัว'")
    print("   ไม่ใช่ความแม่นยำบน traffic จริง (ดู evaluate_real_logins / attack_set)")
    print("=" * 78)


if __name__ == "__main__":
    main()
