"""ประเมิน + SHAP บน simulated_features_23.csv (anchor ผู้ใช้จริง, 23 feat).

  1) in-sample metrics (3 โมเดล) + การจับตามระดับ anomaly (1/2/3)
  2) proper split: one-class, group-by-user(email), 10 splits -> mean±std
  3) SHAP (IForest) importance + beeswarm
  4) รูป: confusion, roc, pr, shap -> figures/SIM/

Run: py ml-service/scripts/simulated_eval.py
"""

import csv
import statistics
from collections import defaultdict
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

DATA = Path(__file__).resolve().parents[1] / "data" / "simulated_features_23.csv"
FIG = (
    Path(__file__).resolve().parents[2]
    / "hub"
    / "backend"
    / "tests"
    / "reports"
    / "figures"
    / "SIM"
)
FIG.mkdir(parents=True, exist_ok=True)

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
MODELS = ("IsolationForest", "OneClassSVM", "LocalOutlierFactor")
COL = {
    "IsolationForest": "#2980b9",
    "OneClassSVM": "#c0392b",
    "LocalOutlierFactor": "#27ae60",
}


def load():
    rows = list(csv.DictReader(open(DATA, encoding="utf-8")))
    X = np.array([[float(r[c]) for c in F] for r in rows])
    y = np.array([int(r["label"]) for r in rows])
    email = np.array([r["email"] for r in rows])
    level = np.array([int(r["anomaly_level"]) for r in rows])
    return X, y, email, level


def fit(name, Xtr, Xte, cont):
    if name == "IsolationForest":
        m = IsolationForest(n_estimators=200, contamination=cont, random_state=0).fit(
            Xtr
        )
        return -m.score_samples(Xtr), -m.score_samples(Xte)
    if name == "OneClassSVM":
        m = OneClassSVM(nu=0.05, kernel="rbf", gamma="scale").fit(Xtr)
        return -m.score_samples(Xtr), -m.score_samples(Xte)
    m = LocalOutlierFactor(n_neighbors=20, novelty=True).fit(Xtr)
    return -m.score_samples(Xtr), -m.score_samples(Xte)


def main():
    X, y, email, level = load()
    cont = float(y.mean())
    Xs = StandardScaler().fit_transform(X)
    print(
        f"simulated_features_23: {len(y)} rows | attack {int(y.sum())} ({cont*100:.1f}%) | 23 feat\n"
    )

    # ---------- 1) in-sample ----------
    preds, scores = {}, {}
    print("=== in-sample (flag @ prevalence) ===")
    print(f"{'Model':<20}{'Prec':>7}{'Recall':>8}{'F1':>7}{'ROC':>8}{'PR':>7}")
    for name in MODELS:
        if name == "LocalOutlierFactor":
            m = LocalOutlierFactor(n_neighbors=20, contamination=cont)
            p = (m.fit_predict(Xs) == -1).astype(int)
            s = -m.negative_outlier_factor_
        elif name == "IsolationForest":
            m = IsolationForest(
                n_estimators=200, contamination=cont, random_state=42
            ).fit(Xs)
            p = (m.predict(Xs) == -1).astype(int)
            s = -m.score_samples(Xs)
        else:
            m = OneClassSVM(nu=max(cont, 0.01), kernel="rbf", gamma="scale").fit(Xs)
            p = (m.predict(Xs) == -1).astype(int)
            s = -m.score_samples(Xs)
        preds[name], scores[name] = p, s
        print(
            f"{name:<20}{precision_score(y,p,zero_division=0):>7.3f}{recall_score(y,p,zero_division=0):>8.3f}"
            f"{f1_score(y,p,zero_division=0):>7.3f}{roc_auc_score(y,s):>8.3f}{average_precision_score(y,s):>7.3f}"
        )

    print("\n=== IForest จับได้ตามระดับ anomaly ===")
    pif = preds["IsolationForest"]
    for lv in [1, 2, 3]:
        idx = np.where(level == lv)[0]
        if len(idx):
            print(f"  level {lv}: จับ {int(pif[idx].sum())}/{len(idx)}")

    # ---------- 2) proper split (group-by-email) ----------
    user_atk = defaultdict(int)
    for e, l in zip(email, y):
        user_atk[e] |= l
    atk_u = set(u for u, a in user_atk.items() if a)
    norm_u = [u for u, a in user_atk.items() if not a]
    res = {m: {"roc": [], "pr": [], "rec": []} for m in MODELS}
    rng = np.random.default_rng(42)
    for _ in range(10):
        nu = norm_u.copy()
        rng.shuffle(nu)
        k = int(len(nu) * 0.7)
        tr_u, te_u = set(nu[:k]), set(nu[k:]) | atk_u
        tr = np.array([e in tr_u for e in email]) & (y == 0)
        te = np.array([e in te_u for e in email])
        sc = StandardScaler().fit(Xs[tr])
        Xtr, Xte, yte = sc.transform(Xs[tr]), sc.transform(Xs[te]), y[te]
        if yte.sum() == 0:
            continue
        for name in MODELS:
            _, s_te = fit(name, Xtr, Xte, 0.01)
            thr = np.quantile(_, 0.99)
            res[name]["roc"].append(roc_auc_score(yte, s_te))
            res[name]["pr"].append(average_precision_score(yte, s_te))
            res[name]["rec"].append(
                recall_score(yte, (s_te >= thr).astype(int), zero_division=0)
            )
    print("\n=== proper split (one-class, group-by-user, 10 splits) ===")
    print(f"{'Model':<20}{'ROC-AUC':>16}{'PR-AUC':>16}{'Recall@1%':>14}")
    ms = lambda v: f"{statistics.mean(v):.3f}±{statistics.pstdev(v):.3f}" if v else "-"
    for name in MODELS:
        r = res[name]
        print(f"{name:<20}{ms(r['roc']):>16}{ms(r['pr']):>16}{ms(r['rec']):>14}")

    # ---------- 3) figures ----------
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.2))
    for ax, name in zip(axes, MODELS):
        ConfusionMatrixDisplay(
            confusion_matrix(y, preds[name]), display_labels=["normal", "attack"]
        ).plot(ax=ax, cmap="Purples", colorbar=False, values_format="d")
        ax.set_title(f"{name}\nF1={f1_score(y,preds[name],zero_division=0):.3f}")
    fig.suptitle(
        f"Confusion — SIMULATED (anchor real users, 23 feat, flag @ {cont*100:.1f}%)",
        fontweight="bold",
    )
    fig.tight_layout()
    fig.savefig(FIG / "confusion_matrices.png", dpi=130)
    plt.close(fig)

    for kind in ("roc", "pr"):
        fig, ax = plt.subplots(figsize=(6.5, 6))
        for name in MODELS:
            if kind == "roc":
                fpr, tpr, _ = roc_curve(y, scores[name])
                ax.plot(
                    fpr,
                    tpr,
                    color=COL[name],
                    lw=2,
                    label=f"{name} (AUC={roc_auc_score(y,scores[name]):.3f})",
                )
            else:
                pr, rc, _ = precision_recall_curve(y, scores[name])
                ax.plot(
                    rc,
                    pr,
                    color=COL[name],
                    lw=2,
                    label=f"{name} (AP={average_precision_score(y,scores[name]):.3f})",
                )
        if kind == "roc":
            ax.plot([0, 1], [0, 1], "k--", lw=1, alpha=0.5)
            ax.set_xlabel("FPR")
            ax.set_ylabel("TPR")
            ax.set_title("ROC — SIMULATED (23 feat)", fontweight="bold")
        else:
            ax.axhline(cont, ls="--", color="gray", lw=1, alpha=0.6)
            ax.set_xlabel("Recall")
            ax.set_ylabel("Precision")
            ax.set_ylim(0, 1.05)
            ax.set_title("Precision-Recall — SIMULATED (23 feat)", fontweight="bold")
        ax.legend(loc="lower right" if kind == "roc" else "upper right")
        ax.grid(alpha=0.3)
        fig.tight_layout()
        fig.savefig(FIG / f"{kind}_curves.png", dpi=130)
        plt.close(fig)

    # ---------- 4) SHAP ----------
    ifo = IsolationForest(n_estimators=200, contamination=cont, random_state=42).fit(X)
    sv = shap.TreeExplainer(ifo).shap_values(X, check_additivity=False)
    ma = np.abs(sv).mean(0)
    order = np.argsort(ma)[::-1]
    nm = [F[i] for i in order][::-1]
    vv = [ma[i] for i in order][::-1]
    fig, ax = plt.subplots(figsize=(9, 8))
    ax.barh(nm, vv, color="#8e44ad")
    ax.set_xlabel("mean(|SHAP|)")
    ax.set_title("SHAP Importance — SIMULATED (IForest, 23 feat)", fontweight="bold")
    fig.tight_layout()
    fig.savefig(FIG / "shap_feature_importance.png", dpi=130)
    plt.close(fig)
    plt.figure()
    shap.summary_plot(sv, X, feature_names=F, show=False, plot_size=(9, 8))
    plt.title("SHAP Summary — SIMULATED (IForest)", fontweight="bold", pad=20)
    plt.savefig(FIG / "shap_summary_beeswarm.png", dpi=130, bbox_inches="tight")
    plt.close()

    print(f"\n✅ figures -> {FIG}")
    print(f"   SHAP top-5: {[F[i] for i in order[:5]]}")


if __name__ == "__main__":
    main()
