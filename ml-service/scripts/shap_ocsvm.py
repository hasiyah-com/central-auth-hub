"""SHAP บน OneClassSVM (KernelExplainer) เทียบกับ IsolationForest (TreeExplainer).

จุดประสงค์: ให้เหตุผลเชิงประจักษ์ว่าทำไมเลือก IsolationForest ไป production
  1) feature importance ของ OCSVM (Kernel) ตรงกับ IForest (Tree) ไหม?
  2) ต้นทุนการอธิบาย: วัดเวลา TreeExplainer (exact, ทั้งชุด) vs KernelExplainer (approx, subset)

Run:
    py ml-service/scripts/shap_ocsvm.py
"""

import csv
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import shap
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
from sklearn.svm import OneClassSVM

DATA = Path(__file__).resolve().parents[1] / "data" / "benchmark_rba.csv"
FIG = (
    Path(__file__).resolve().parents[2]
    / "hub"
    / "backend"
    / "tests"
    / "reports"
    / "figures"
)
FIG.mkdir(parents=True, exist_ok=True)

FEATURES_C = [
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
N_BG = 30  # background สำหรับ KernelExplainer
N_EXPLAIN = 300  # จำนวนแถวที่อธิบาย (รวม attack ทั้งหมด + สุ่ม normal)


def _num(v):
    s = str(v).strip().lower()
    return 1.0 if s == "true" else 0.0 if s == "false" else float(s)


def load():
    with open(DATA, "r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    y = np.array([int(r["label"]) for r in rows])
    X = np.array([[_num(r[c]) for c in FEATURES_C] for r in rows])
    return X, y


def main():
    if not DATA.exists():
        print(f"❌ ไม่พบ {DATA}")
        return
    X, y = load()
    Xs = StandardScaler().fit_transform(X)
    print(
        f"dataset {len(y):,} | attack {int(y.sum())} | {len(FEATURES_C)} feat (Exp C)\n"
    )

    # ---- IsolationForest + TreeExplainer (exact, ทั้งชุด) ----
    ifo = IsolationForest(
        n_estimators=200, contamination=float(y.mean()), random_state=42
    ).fit(Xs)
    t0 = time.perf_counter()
    sv_if = shap.TreeExplainer(ifo).shap_values(Xs, check_additivity=False)
    t_tree = time.perf_counter() - t0
    imp_if = np.abs(sv_if).mean(axis=0)
    print(f"TreeExplainer (IForest): อธิบาย {len(Xs):,} แถว ใน {t_tree:.2f}s")

    # ---- OneClassSVM + KernelExplainer (approx, subset) ----
    ocsvm = OneClassSVM(nu=max(float(y.mean()), 0.01), kernel="rbf", gamma="scale").fit(
        Xs
    )

    def f(d):  # สูง = anomaly
        return -ocsvm.decision_function(d)

    bg = shap.kmeans(Xs, N_BG)
    # อธิบาย: attack ทั้งหมด + สุ่ม normal ให้ครบ N_EXPLAIN
    rng = np.random.default_rng(0)
    atk_idx = np.where(y == 1)[0]
    nrm_idx = rng.choice(
        np.where(y == 0)[0], size=max(0, N_EXPLAIN - len(atk_idx)), replace=False
    )
    expl_idx = np.concatenate([atk_idx, nrm_idx])
    t0 = time.perf_counter()
    ke = shap.KernelExplainer(f, bg)
    sv_oc = ke.shap_values(Xs[expl_idx], nsamples=200, silent=True)
    t_kernel = time.perf_counter() - t0
    sv_oc = np.array(sv_oc)
    imp_oc = np.abs(sv_oc).mean(axis=0)
    print(
        f"KernelExplainer (OCSVM): อธิบายแค่ {len(expl_idx)} แถว (bg={N_BG}) ใน {t_kernel:.2f}s"
    )
    print(
        f"\n⚠️ ต้นทุนต่อแถว: Tree={t_tree/len(Xs)*1000:.3f} ms/row | "
        f"Kernel={t_kernel/len(expl_idx)*1000:.1f} ms/row "
        f"(~{(t_kernel/len(expl_idx))/(t_tree/len(Xs)):.0f}× ช้ากว่า)"
    )

    # ---- ranking เทียบกัน ----
    order_if = np.argsort(imp_if)[::-1]
    order_oc = np.argsort(imp_oc)[::-1]
    print(f"\n{'#':>2} {'IsolationForest (Tree)':<32}{'OneClassSVM (Kernel)':<32}")
    for r in range(10):
        a = FEATURES_C[order_if[r]]
        b = FEATURES_C[order_oc[r]]
        print(f"{r+1:>2} {a:<32}{b:<32}")

    # Spearman-ish: overlap ของ top-10
    top_if = {FEATURES_C[i] for i in order_if[:10]}
    top_oc = {FEATURES_C[i] for i in order_oc[:10]}
    print(f"\nTop-10 overlap (IForest ∩ OCSVM): {len(top_if & top_oc)}/10")

    # ---- รูปเทียบ side-by-side ----
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 8))
    nm1 = [FEATURES_C[i] for i in order_if][::-1]
    v1 = [imp_if[i] for i in order_if][::-1]
    ax1.barh(nm1, v1, color="#2980b9")
    ax1.set_title("IsolationForest — TreeExplainer (exact)", fontweight="bold")
    ax1.set_xlabel("mean(|SHAP|)")
    nm2 = [FEATURES_C[i] for i in order_oc][::-1]
    v2 = [imp_oc[i] for i in order_oc][::-1]
    ax2.barh(nm2, v2, color="#c0392b")
    ax2.set_title(
        f"OneClassSVM — KernelExplainer (approx, {len(expl_idx)} rows)",
        fontweight="bold",
    )
    ax2.set_xlabel("mean(|SHAP|)")
    fig.suptitle(
        "SHAP Feature Importance: IsolationForest vs OneClassSVM (Exp C)",
        fontweight="bold",
    )
    fig.tight_layout()
    fig.savefig(FIG / "shap_ocsvm_vs_iforest.png", dpi=130)
    plt.close(fig)
    print(f"\n✅ figure -> {FIG / 'shap_ocsvm_vs_iforest.png'}")


if __name__ == "__main__":
    main()
