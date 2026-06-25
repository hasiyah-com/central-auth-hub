"""สร้างรูปกราฟสำหรับรายงาน/เล่ม (benchmark_rba.csv) — ครบ Experiment A/B/C.

Export -> hub/backend/tests/reports/figures/
  figures/<EXP>/   (EXP ∈ A,B,C) แต่ละชุดมี 6 รูป:
    1) confusion_matrices.png        — 3 โมเดล @ contamination 1.38%
    2) metrics_comparison.png        — Precision/Recall/F1/ROC-AUC/PR-AUC (grouped bar)
    3) roc_curves.png                — ROC + AUC
    4) pr_curves.png                 — Precision-Recall curve + AP (ตัวหลัก, imbalanced §11)
    5) shap_feature_importance.png   — mean|SHAP| (IsolationForest + TreeExplainer)
    6) shap_summary_beeswarm.png     — SHAP beeswarm summary
  figures/ablation_pr_auc.png        — PR-AUC + F1 A→B→C ต่อโมเดล (ablation รวม)

Run:
    py ml-service/scripts/generate_figures.py
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

DATA = Path(__file__).resolve().parents[1] / "data" / "benchmark_rba.csv"
FIG_DIR = (
    Path(__file__).resolve().parents[2]
    / "hub"
    / "backend"
    / "tests"
    / "reports"
    / "figures"
)
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
MODELS = ("IsolationForest", "OneClassSVM", "LocalOutlierFactor")
COLORS = {
    "IsolationForest": "#2980b9",
    "OneClassSVM": "#c0392b",
    "LocalOutlierFactor": "#27ae60",
}
ALL_COLS = FEATURES_C


def load():
    with open(DATA, "r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    y = np.array([int(r["label"]) for r in rows])
    cols = {c: np.array([float(r[c]) for r in rows]) for c in ALL_COLS}
    return cols, y


def fit_predict_score(name, Xs, contamination):
    if name == "IsolationForest":
        m = IsolationForest(
            n_estimators=200, contamination=contamination, random_state=42
        )
        m.fit(Xs)
        return (m.predict(Xs) == -1).astype(int), -m.score_samples(Xs)
    if name == "OneClassSVM":
        m = OneClassSVM(nu=max(contamination, 0.01), kernel="rbf", gamma="scale")
        m.fit(Xs)
        return (m.predict(Xs) == -1).astype(int), -m.score_samples(Xs)
    m = LocalOutlierFactor(n_neighbors=20, contamination=contamination)
    pred = (m.fit_predict(Xs) == -1).astype(int)
    return pred, -m.negative_outlier_factor_


def figs_for_experiment(exp, names, cols, y, cont):
    out = FIG_DIR / exp
    out.mkdir(parents=True, exist_ok=True)
    X = np.column_stack([cols[n] for n in names])
    Xs = StandardScaler().fit_transform(X)
    preds, scores = {}, {}
    for name in MODELS:
        preds[name], scores[name] = fit_predict_score(name, Xs, cont)

    # 1) confusion matrices
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.2))
    for ax, name in zip(axes, MODELS):
        cm = confusion_matrix(y, preds[name])
        ConfusionMatrixDisplay(cm, display_labels=["normal", "attack"]).plot(
            ax=ax, cmap="Blues", colorbar=False, values_format="d"
        )
        ax.set_title(f"{name}\nF1={f1_score(y, preds[name], zero_division=0):.3f}")
    fig.suptitle(
        f"Confusion Matrices — Experiment {exp} ({len(names)} features, flag @ {cont*100:.2f}%)",
        fontweight="bold",
    )
    fig.tight_layout()
    fig.savefig(out / "confusion_matrices.png", dpi=130)
    plt.close(fig)

    # metrics
    metric_names = ["Precision", "Recall", "F1", "ROC-AUC", "PR-AUC"]
    vals = {
        n: [
            precision_score(y, preds[n], zero_division=0),
            recall_score(y, preds[n], zero_division=0),
            f1_score(y, preds[n], zero_division=0),
            roc_auc_score(y, scores[n]),
            average_precision_score(y, scores[n]),
        ]
        for n in MODELS
    }

    # 2) metrics comparison
    x = np.arange(len(metric_names))
    width = 0.26
    fig, ax = plt.subplots(figsize=(10, 5))
    for i, name in enumerate(MODELS):
        bars = ax.bar(
            x + (i - 1) * width, vals[name], width, label=name, color=COLORS[name]
        )
        ax.bar_label(bars, fmt="%.2f", fontsize=7, padding=2)
    ax.set_xticks(x)
    ax.set_xticklabels(metric_names)
    ax.set_ylim(0, 1.08)
    ax.set_ylabel("score")
    ax.set_title(
        f"Model Metrics Comparison — Experiment {exp} ({len(names)} features)",
        fontweight="bold",
    )
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out / "metrics_comparison.png", dpi=130)
    plt.close(fig)

    # 3) ROC
    fig, ax = plt.subplots(figsize=(6.5, 6))
    for name in MODELS:
        fpr, tpr, _ = roc_curve(y, scores[name])
        ax.plot(
            fpr,
            tpr,
            color=COLORS[name],
            lw=2,
            label=f"{name} (AUC={roc_auc_score(y, scores[name]):.3f})",
        )
    ax.plot([0, 1], [0, 1], "k--", lw=1, alpha=0.5)
    ax.set_xlabel("False Positive Rate")
    ax.set_ylabel("True Positive Rate")
    ax.set_title(
        f"ROC Curves — Experiment {exp} ({len(names)} features)", fontweight="bold"
    )
    ax.legend(loc="lower right")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out / "roc_curves.png", dpi=130)
    plt.close(fig)

    # 4) PR curve (ตัวหลัก imbalanced)
    fig, ax = plt.subplots(figsize=(6.5, 6))
    for name in MODELS:
        prec, rec, _ = precision_recall_curve(y, scores[name])
        ax.plot(
            rec,
            prec,
            color=COLORS[name],
            lw=2,
            label=f"{name} (AP={average_precision_score(y, scores[name]):.3f})",
        )
    ax.axhline(
        cont, ls="--", color="gray", lw=1, alpha=0.6, label=f"baseline ({cont:.3f})"
    )
    ax.set_xlabel("Recall")
    ax.set_ylabel("Precision")
    ax.set_ylim(0, 1.05)
    ax.set_title(
        f"Precision-Recall Curves — Experiment {exp} ({len(names)} features)",
        fontweight="bold",
    )
    ax.legend(loc="upper right")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out / "pr_curves.png", dpi=130)
    plt.close(fig)

    # 5 & 6) SHAP (IsolationForest, feature ดิบ)
    ifo = IsolationForest(n_estimators=200, contamination=cont, random_state=42)
    ifo.fit(X)
    sv = shap.TreeExplainer(ifo).shap_values(X, check_additivity=False)

    mean_abs = np.abs(sv).mean(axis=0)
    order = np.argsort(mean_abs)[::-1]
    nm = [names[i] for i in order][::-1]
    vv = [mean_abs[i] for i in order][::-1]
    fig, ax = plt.subplots(figsize=(9, max(4, len(names) * 0.34)))
    ax.barh(nm, vv, color="#8e44ad")
    ax.set_xlabel("mean(|SHAP value|)")
    ax.set_title(
        f"SHAP Feature Importance — IsolationForest (Exp {exp})", fontweight="bold"
    )
    fig.tight_layout()
    fig.savefig(out / "shap_feature_importance.png", dpi=130)
    plt.close(fig)

    plt.figure()
    shap.summary_plot(
        sv, X, feature_names=names, show=False, plot_size=(9, max(4, len(names) * 0.34))
    )
    plt.title(
        f"SHAP Summary (beeswarm) — IsolationForest (Exp {exp})",
        fontweight="bold",
        pad=20,
    )
    plt.savefig(out / "shap_summary_beeswarm.png", dpi=130, bbox_inches="tight")
    plt.close()

    return {n: vals[n] for n in MODELS}  # for ablation


def main():
    if not DATA.exists():
        print(f"❌ ไม่พบ {DATA} — รัน build_benchmark.py ก่อน")
        return
    cols, y = load()
    cont = float(y.mean())
    print(f"dataset {len(y):,} | attack {int(y.sum())} ({cont*100:.2f}%)")

    # PR-AUC index=4, F1 index=2 ใน metric vals
    prauc = {n: [] for n in MODELS}
    f1s = {n: [] for n in MODELS}
    for exp, names in EXPERIMENTS.items():
        vals = figs_for_experiment(exp, names, cols, y, cont)
        for n in MODELS:
            prauc[n].append(vals[n][4])
            f1s[n].append(vals[n][2])
        print(f"   ✅ Experiment {exp} ({len(names)} feat) — 6 รูป")

    # ablation: PR-AUC + F1 across A->B->C
    exps = list(EXPERIMENTS.keys())
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
    for n in MODELS:
        ax1.plot(exps, prauc[n], "o-", color=COLORS[n], lw=2, label=n)
        ax2.plot(exps, f1s[n], "o-", color=COLORS[n], lw=2, label=n)
    ax1.set_title("PR-AUC across Experiments (ablation)", fontweight="bold")
    ax1.set_xlabel("Experiment (A=13 → B=19 → C=23 features)")
    ax1.set_ylabel("PR-AUC")
    ax2.set_title("F1 across Experiments (ablation)", fontweight="bold")
    ax2.set_xlabel("Experiment (A=13 → B=19 → C=23 features)")
    ax2.set_ylabel("F1")
    for ax in (ax1, ax2):
        ax.grid(alpha=0.3)
        ax.legend()
    fig.suptitle(
        "Ablation: effect of added features (Tier-1 in B, Passkey in C)",
        fontweight="bold",
    )
    fig.tight_layout()
    fig.savefig(FIG_DIR / "ablation_pr_auc.png", dpi=130)
    plt.close(fig)

    print(f"\n✅ เสร็จ — figures ที่: {FIG_DIR}")
    print("   figures/{A,B,C}/ (6 รูปต่อชุด) + ablation_pr_auc.png")


if __name__ == "__main__":
    main()
