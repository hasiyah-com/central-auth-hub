"""SHAP analysis บน benchmark_rba.csv (การทดสอบ.md §12).

ใช้ SHAP TreeExplainer บน IsolationForest (ตรงกับ infra ระบบ — Lundberg & Lee 2017)
  - global importance = mean(|SHAP|) ต่อ feature  -> Top 10 / Top 20
  - signed mean SHAP เฉพาะ attack rows -> ทิศทาง (feature ไหนดัน "เข้าหา anomaly")
  - เปรียบเทียบ Experiment A (13) vs B (19) vs C (23)
  - บันทึก bar chart PNG ต่อ experiment

SHAP คำนวณบน feature ดิบ (ไม่ scale) เพื่อให้ contribution ตีความเป็นหน่วยจริงได้
(tree-based ไม่ไวต่อ scaling — ranking คงเดิม)

Run:
    py ml-service/scripts/shap_analysis.py
ต้องมี: numpy, scikit-learn, shap, matplotlib
"""

import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import shap
from sklearn.ensemble import IsolationForest

DATA = Path(__file__).resolve().parents[1] / "data" / "benchmark_rba.csv"
FIG_DIR = Path(__file__).resolve().parents[1] / "data" / "shap"
FIG_DIR.mkdir(parents=True, exist_ok=True)

FEATURES_A = [
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
]
FEATURES_B = FEATURES_A + [
    "concurrent_session_count",
    "active_subsystem_count",
    "weekday_usage_score",
    "scope_sensitivity_score",
    "permission_change_age",
    "confirmed_incident_count",
]
FEATURES_C = FEATURES_B + [
    "passkey_count",
    "passkey_age_days",
    "new_passkey_recently_added",
    "passkey_last_used_days",
]
EXPERIMENTS = {"A": FEATURES_A, "B": FEATURES_B, "C": FEATURES_C}
TIER1 = set(FEATURES_B) - set(FEATURES_A)
PASSKEY = set(FEATURES_C) - set(FEATURES_B)


def load():
    with open(DATA, "r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    y = np.array([int(r["label"]) for r in rows])
    cols = {c: np.array([float(r[c]) for r in rows]) for c in FEATURES_C}
    return cols, y


def tag(name: str) -> str:
    if name in PASSKEY:
        return " [Passkey]"
    if name in TIER1:
        return " [Tier-1]"
    return ""


def analyze(exp: str, names: list[str], cols, y):
    X = np.column_stack([cols[n] for n in names])
    contamination = float(y.mean())
    model = IsolationForest(
        n_estimators=200, contamination=contamination, random_state=42
    )
    model.fit(X)

    explainer = shap.TreeExplainer(model)
    sv = explainer.shap_values(X, check_additivity=False)  # (n, n_features)

    mean_abs = np.abs(sv).mean(axis=0)
    # ทิศทางบน attack rows: SHAP เฉลี่ย (signed) เฉพาะ label==1
    attack_signed = sv[y == 1].mean(axis=0)

    order = np.argsort(mean_abs)[::-1]
    ranking = [(names[i], mean_abs[i], attack_signed[i]) for i in order]

    # bar chart top features
    top = ranking[: min(20, len(ranking))]
    labels = [t[0] + tag(t[0]) for t in top][::-1]
    vals = [t[1] for t in top][::-1]
    colors = [
        "#c0392b" if PASSKEY & {t[0]} else "#e67e22" if TIER1 & {t[0]} else "#2980b9"
        for t in top
    ][::-1]
    plt.figure(figsize=(9, max(4, len(top) * 0.32)))
    plt.barh(labels, vals, color=colors)
    plt.xlabel("mean(|SHAP value|)  — global importance")
    plt.title(
        f"SHAP feature importance — Experiment {exp} ({len(names)} features)\nIsolationForest + TreeExplainer"
    )
    plt.tight_layout()
    out = FIG_DIR / f"shap_importance_{exp}.png"
    plt.savefig(out, dpi=120)
    plt.close()
    return ranking, out


def print_ranking(exp, ranking, k):
    # IsolationForest: score ต่ำ = anomaly -> signed SHAP บน attack rows ติดลบ = ดันเข้าหา anomaly
    print(f"\n=== Experiment {exp} — Top {k} (mean|SHAP|) ===")
    print(f"{'#':>2}  {'feature':<34}{'mean|SHAP|':>11}{'attack-row SHAP':>16}")
    for i, (name, ma, sgn) in enumerate(ranking[:k], 1):
        arrow = "=> ANOMALY" if sgn < -1e-6 else ("=> normal" if sgn > 1e-6 else "·")
        print(f"{i:>2}  {name + tag(name):<34}{ma:>11.5f}{sgn:>+11.5f} {arrow}")


def main():
    if not DATA.exists():
        print(f"❌ ไม่พบ {DATA} — รัน build_benchmark.py ก่อน")
        return
    cols, y = load()
    print(f"dataset: {len(y):,} rows | attack={int(y.sum())} ({y.mean()*100:.2f}%)")
    print("SHAP TreeExplainer บน IsolationForest (feature ดิบ ไม่ scale)")

    results = {}
    for exp, names in EXPERIMENTS.items():
        ranking, fig = analyze(exp, names, cols, y)
        results[exp] = ranking
        k = 20 if exp == "C" else 10
        print_ranking(exp, ranking, k)
        print(f"   📊 chart: {fig}")

    # สรุปการเลื่อนอันดับ A->B->C ของ feature ใหม่
    print("\n=== อันดับของ feature ที่เพิ่มเข้ามา (rank ใน Experiment ที่มันโผล่) ===")
    rankC = {n: i + 1 for i, (n, _, _) in enumerate(results["C"])}
    rankB = {n: i + 1 for i, (n, _, _) in enumerate(results["B"])}
    print("Tier-1 (เพิ่มใน B):")
    for n in sorted(TIER1, key=lambda x: rankC.get(x, 999)):
        print(f"   {n:<28} rank_B={rankB.get(n,'-'):>3}  rank_C={rankC.get(n):>3}")
    print("Passkey (เพิ่มใน C):")
    for n in sorted(PASSKEY, key=lambda x: rankC.get(x, 999)):
        print(f"   {n:<28} rank_C={rankC.get(n):>3}")


if __name__ == "__main__":
    main()
