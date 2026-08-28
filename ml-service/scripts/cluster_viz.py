"""กราฟความหนาแน่น + การแบ่งกลุ่ม (PCA 2D + score distribution) สำหรับ Forest & SVM.

ทำ 2 ชุด:
  A) RBA จริง (real_only_rba.csv, 12 feat) — normal จริง + ATO จริง
  B) จริง + สร้างความผิดปกติ (benchmark_rba.csv, 23 feat) — real + synthetic attack

แต่ละชุด: PCA 2D scatter (normal vs anomaly) + score histogram ของ IForest และ OCSVM
+ พิมพ์ metrics (in-sample) เทียบ Forest vs SVM

Output: figures/CLUSTER/  ·  Run: py ml-service/scripts/cluster_viz.py
"""

import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from sklearn.decomposition import PCA
from sklearn.ensemble import IsolationForest
from sklearn.metrics import average_precision_score, f1_score, roc_auc_score
from sklearn.preprocessing import StandardScaler
from sklearn.svm import OneClassSVM

DATA = Path(__file__).resolve().parents[1] / "data"
FIG = (
    Path(__file__).resolve().parents[2]
    / "hub"
    / "backend"
    / "tests"
    / "reports"
    / "figures"
    / "CLUSTER"
)
FIG.mkdir(parents=True, exist_ok=True)

F12 = [
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
]
F23 = F12 + [
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


def _num(v):
    s = str(v).strip().lower()
    return 1.0 if s == "true" else 0.0 if s == "false" else float(s)


def load(fn, feats):
    rows = list(csv.DictReader(open(DATA / fn, encoding="utf-8")))
    X = np.array([[_num(r[c]) for c in feats] for r in rows])
    y = np.array([int(r["label"]) for r in rows])
    return X, y


def analyze(fn, feats, tag, title):
    X, y = load(fn, feats)
    Xs = StandardScaler().fit_transform(X)
    cont = float(y.mean())
    # models
    ifo = IsolationForest(n_estimators=200, contamination=cont, random_state=42).fit(Xs)
    s_if = -ifo.score_samples(Xs)
    ocs = OneClassSVM(nu=max(cont, 0.01), kernel="rbf", gamma="scale").fit(Xs)
    s_oc = -ocs.score_samples(Xs)
    # PCA 2D
    pca = PCA(n_components=2, random_state=0).fit(Xs)
    P = pca.transform(Xs)
    ev = pca.explained_variance_ratio_

    fig, axes = plt.subplots(1, 3, figsize=(16, 5))
    # (1) PCA scatter normal vs anomaly
    ax = axes[0]
    ax.scatter(P[y == 0, 0], P[y == 0, 1], s=6, c="#2980b9", alpha=0.25, label="normal")
    ax.scatter(
        P[y == 1, 0],
        P[y == 1, 1],
        s=28,
        c="#c0392b",
        alpha=0.9,
        marker="x",
        label="anomaly",
    )
    ax.set_title(
        f"PCA 2D projection — clustering / density\n(explained variance {ev[0]*100:.0f}% + {ev[1]*100:.0f}%)",
        fontweight="bold",
    )
    ax.set_xlabel("PC1")
    ax.set_ylabel("PC2")
    ax.legend()
    # (2) IForest score dist
    for nm, s, ax2 in [
        ("IsolationForest", s_if, axes[1]),
        ("OneClassSVM", s_oc, axes[2]),
    ]:
        ax2.hist(
            s[y == 0], bins=50, color="#2980b9", alpha=0.6, density=True, label="normal"
        )
        ax2.hist(
            s[y == 1],
            bins=30,
            color="#c0392b",
            alpha=0.7,
            density=True,
            label="anomaly",
        )
        roc = roc_auc_score(y, s)
        pr = average_precision_score(y, s)
        ax2.set_title(
            f"{nm} — anomaly score\nROC={roc:.3f} PR-AUC={pr:.3f}", fontweight="bold"
        )
        ax2.set_xlabel("anomaly score (high = anomaly)")
        ax2.legend()
    fig.suptitle(title, fontweight="bold", fontsize=13)
    fig.tight_layout()
    fig.savefig(FIG / f"{tag}_cluster.png", dpi=130)
    plt.close(fig)

    # metrics print
    print(
        f"\n=== {tag} : {fn} ({len(feats)} feat) | rows {len(y)} attack {int(y.sum())} ({cont*100:.2f}%) ==="
    )
    print(
        f"PCA explained variance: PC1 {ev[0]*100:.1f}% + PC2 {ev[1]*100:.1f}% = {sum(ev)*100:.1f}%"
    )
    for nm, s in [("IsolationForest", s_if), ("OneClassSVM", s_oc)]:
        pred = (s >= np.quantile(s, 1 - cont)).astype(int)
        print(
            f"  {nm:<18} ROC {roc_auc_score(y,s):.3f} | PR-AUC {average_precision_score(y,s):.3f} | F1 {f1_score(y,pred,zero_division=0):.3f}"
        )
    print(f"  figure -> {FIG / f'{tag}_cluster.png'}")


def main():
    analyze(
        "real_only_rba.csv",
        F12,
        "real12",
        "Dataset A: Real RBA (12 features) — real normal + real ATO",
    )
    analyze(
        "benchmark_rba.csv",
        F23,
        "synth23",
        "Dataset B: Real + Synthetic anomaly (23 features)",
    )


if __name__ == "__main__":
    main()
