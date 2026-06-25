"""ประเมินโมเดลบนชุด real-only (feature จริงล้วน 12 ตัว) + บันทึกรูป.

เทียบกับ semi-synthetic benchmark เพื่อให้เล่มมีทั้งสองมุม:
  - real-only  : feature derive จาก RBA จริง 100% (ATO จริงเป็น test)
  - semi-synth : 23 feature (มี passkey/session ที่ simulate)

Run:
    py ml-service/scripts/real_only_eval.py
"""

import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import shap
from sklearn.ensemble import IsolationForest
from sklearn.metrics import (
    ConfusionMatrixDisplay,
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)
from sklearn.neighbors import LocalOutlierFactor
from sklearn.preprocessing import StandardScaler
from sklearn.svm import OneClassSVM

DATA = Path(__file__).resolve().parents[1] / "data" / "real_only_rba.csv"
FIG = (
    Path(__file__).resolve().parents[2]
    / "hub"
    / "backend"
    / "tests"
    / "reports"
    / "figures"
    / "REAL"
)
FIG.mkdir(parents=True, exist_ok=True)

FEATURES = [
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
MODELS = ("IsolationForest", "OneClassSVM", "LocalOutlierFactor")
COLORS = {
    "IsolationForest": "#2980b9",
    "OneClassSVM": "#c0392b",
    "LocalOutlierFactor": "#27ae60",
}


def _num(v):
    s = str(v).strip()
    if s.lower() == "true":
        return 1.0
    if s.lower() == "false":
        return 0.0
    return float(s)


def load():
    with open(DATA, "r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    y = np.array([int(r["label"]) for r in rows])
    X = np.column_stack([np.array([_num(r[c]) for r in rows]) for c in FEATURES])
    return X, y


def fit(name, Xs, cont):
    if name == "IsolationForest":
        m = IsolationForest(n_estimators=200, contamination=cont, random_state=42).fit(
            Xs
        )
        return (m.predict(Xs) == -1).astype(int), -m.score_samples(Xs)
    if name == "OneClassSVM":
        m = OneClassSVM(nu=max(cont, 0.01), kernel="rbf", gamma="scale").fit(Xs)
        return (m.predict(Xs) == -1).astype(int), -m.score_samples(Xs)
    m = LocalOutlierFactor(n_neighbors=20, contamination=cont)
    pred = (m.fit_predict(Xs) == -1).astype(int)
    return pred, -m.negative_outlier_factor_


def main():
    if not DATA.exists():
        print(f"❌ ไม่พบ {DATA} — รัน build_real_only.py ก่อน")
        return
    X, y = load()
    cont = float(y.mean())
    Xs = StandardScaler().fit_transform(X)
    print(
        f"real-only: {len(y):,} rows | attack(ATO จริง)={int(y.sum())} ({cont*100:.3f}%) | {len(FEATURES)} feat\n"
    )

    preds, scores = {}, {}
    hdr = f"{'Model':<20}{'Prec':>7}{'Recall':>8}{'F1':>7}{'ROC-AUC':>9}{'PR-AUC':>8}"
    print(hdr)
    print("-" * len(hdr))
    for name in MODELS:
        preds[name], scores[name] = fit(name, Xs, cont)
        P = precision_score(y, preds[name], zero_division=0)
        R = recall_score(y, preds[name], zero_division=0)
        F = f1_score(y, preds[name], zero_division=0)
        RO = roc_auc_score(y, scores[name])
        PR = average_precision_score(y, scores[name])
        print(f"{name:<20}{P:>7.3f}{R:>8.3f}{F:>7.3f}{RO:>9.3f}{PR:>8.3f}")

    # confusion matrices
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.2))
    for ax, name in zip(axes, MODELS):
        ConfusionMatrixDisplay(
            confusion_matrix(y, preds[name]), display_labels=["normal", "attack"]
        ).plot(ax=ax, cmap="Greens", colorbar=False, values_format="d")
        ax.set_title(f"{name}\nF1={f1_score(y, preds[name], zero_division=0):.3f}")
    fig.suptitle(
        f"Confusion Matrices — REAL-ONLY (12 feat, flag @ {cont*100:.3f}%)",
        fontweight="bold",
    )
    fig.tight_layout()
    fig.savefig(FIG / "confusion_matrices.png", dpi=130)
    plt.close(fig)

    # ROC + PR
    for kind in ("roc", "pr"):
        fig, ax = plt.subplots(figsize=(6.5, 6))
        for name in MODELS:
            if kind == "roc":
                fpr, tpr, _ = roc_curve(y, scores[name])
                ax.plot(
                    fpr,
                    tpr,
                    color=COLORS[name],
                    lw=2,
                    label=f"{name} (AUC={roc_auc_score(y, scores[name]):.3f})",
                )
            else:
                pr, rc, _ = precision_recall_curve(y, scores[name])
                ax.plot(
                    rc,
                    pr,
                    color=COLORS[name],
                    lw=2,
                    label=f"{name} (AP={average_precision_score(y, scores[name]):.3f})",
                )
        if kind == "roc":
            ax.plot([0, 1], [0, 1], "k--", lw=1, alpha=0.5)
            ax.set_xlabel("FPR")
            ax.set_ylabel("TPR")
            ax.set_title("ROC — REAL-ONLY (12 feat)", fontweight="bold")
        else:
            ax.axhline(cont, ls="--", color="gray", lw=1, alpha=0.6)
            ax.set_xlabel("Recall")
            ax.set_ylabel("Precision")
            ax.set_ylim(0, 1.05)
            ax.set_title("Precision-Recall — REAL-ONLY (12 feat)", fontweight="bold")
        ax.legend(loc="lower right" if kind == "roc" else "upper right")
        ax.grid(alpha=0.3)
        fig.tight_layout()
        fig.savefig(FIG / f"{kind}_curves.png", dpi=130)
        plt.close(fig)

    # SHAP importance (IForest)
    ifo = IsolationForest(n_estimators=200, contamination=cont, random_state=42).fit(X)
    sv = shap.TreeExplainer(ifo).shap_values(X, check_additivity=False)
    ma = np.abs(sv).mean(axis=0)
    order = np.argsort(ma)[::-1]
    nm = [FEATURES[i] for i in order][::-1]
    vv = [ma[i] for i in order][::-1]
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.barh(nm, vv, color="#16a085")
    ax.set_xlabel("mean(|SHAP value|)")
    ax.set_title(
        "SHAP Importance — REAL-ONLY (IsolationForest, 12 feat)", fontweight="bold"
    )
    fig.tight_layout()
    fig.savefig(FIG / "shap_feature_importance.png", dpi=130)
    plt.close(fig)
    plt.figure()
    shap.summary_plot(sv, X, feature_names=FEATURES, show=False, plot_size=(9, 5))
    plt.title("SHAP Summary — REAL-ONLY (IsolationForest)", fontweight="bold", pad=20)
    plt.savefig(FIG / "shap_summary_beeswarm.png", dpi=130, bbox_inches="tight")
    plt.close()

    print(f"\n✅ figures -> {FIG}")


if __name__ == "__main__":
    main()
