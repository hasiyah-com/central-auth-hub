"""การทดลองรวม 4 ชั้น — L1 Rule + L2 Behavior + L3 IsolationForest(+SHAP) + L4 Fusion.

รายงานผลของ **ทุกชั้น** ในการทดลองเดียว บนชุดข้อมูล/ชุดทดสอบเดียวกัน:

  - standalone   : แต่ละชั้นจับได้เท่าไรถ้าทำงานลำพัง
  - unique       : attack ที่ "เฉพาะชั้นนั้น" จับได้ (ชั้นอื่นพลาด)
  - overlap      : สัญญาณที่ซ้ำกับชั้นอื่น
  - combined(L4) : ผลรวมจริงหลัง fusion

L3 มี 2 แบบให้เทียบ (ใช้ IsolationForest ทั้งคู่):
  L3-all23 : IForest บน 23 ฟีเจอร์ (แบบเดิม) -> ใช้ SHAP วัด DuplicateRatio ว่าซ้ำ L1/L2 แค่ไหน
  L3-seq   : IForest บน residual รายคน 6 มิติ × window 5 = 18 มิติ (แบบ production)

SHAP (ตามแผน l3_isolation_forest_redesign §6):
  - TreeExplainer: parity กับ -score_samples **ไม่ผ่าน** (อธิบาย path length ดิบ) แต่ rank-corr = 1.0
    -> ใช้จัดอันดับ attribution ได้ (เร็วพอสำหรับทุก event)
  - PermutationExplainer: parity เป๊ะ -> ใช้ตรวจสอบบน sample
  - DuplicateRatio = Σ|φ| ของฟีเจอร์ที่ L1/L2 เป็นเจ้าของ ÷ Σ|φ| ทั้งหมด

Run:
    cd hub/backend && SHARED_NAT=true PYTHONPATH=. python ../../ml-service/scripts/exp_4layer_full.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from sklearn.ensemble import IsolationForest

ML = Path(__file__).resolve().parent
sys.path.insert(0, str(ML))
import build_profiles_v2 as BP  # noqa: E402
import lc_l3_ownership as O  # noqa: E402
import lc_l3_sequence as SEQ  # noqa: E402
import lc_run_4layer as LC  # noqa: E402

from app.security.behavior_profiling import evaluate_behavior  # noqa: E402
from app.security.iforest_scorer import IForestResult  # noqa: E402
from app.security.risk_aggregator import THRESHOLDS, aggregate  # noqa: E402
from app.security.rule_engine import evaluate_rules  # noqa: E402

REPORTS = LC.REPORTS
RANK = LC.RANK
FEATURES = LC.FEATURES
SIZE = 5000  # ใช้ขนาดที่โมเดลรายคนนิ่งแล้ว
W = SEQ.W
VAL_FPR = 0.01
NEUTRAL = IForestResult(0.0, 0.0, "neutral")

# ── feature ownership (สำหรับ DuplicateRatio ของ SHAP) ──
L1_OWNED = [
    "is_new_device",
    "is_new_user_agent_family",
    "failed_logins_24h",
    "login_count_24h",
    "concurrent_session_count",
    "active_subsystem_count",
    "new_passkey_recently_added",
    "permission_change_age",
    "ever_changed_permission",
    "confirmed_incident_count",
]
L2_OWNED = [
    "hour_of_day",
    "day_of_week",
    "hours_from_typical_login_time",
    "log_minutes_since_last_login",
    "weekday_usage_score",
]
GEO_DEAD = [
    "is_thailand",
    "is_new_country",
    "country_change_count_30d",
    "impossible_travel_score",
]
L3_ONLY = [
    "passkey_count",
    "passkey_age_days",
    "passkey_last_used_days",
    "scope_sensitivity_score",
]


def _decide(total: float) -> str:
    if total >= THRESHOLDS["block"]:
        return "block"
    if total >= THRESHOLDS["challenge"]:
        return "challenge"
    if total >= THRESHOLDS["warn"]:
        return "warn"
    return "allow"


def _fit_if(X, fpr=VAL_FPR):
    """IForest + calibrate threshold จาก train-normal (anomaly = -score_samples)."""
    X = np.asarray(X, dtype=float)
    if len(X) < 20:
        return None
    keep = X.std(axis=0) > 1e-9
    if not keep.any():
        return None
    m = IsolationForest(n_estimators=100, contamination=0.02, random_state=42).fit(
        X[:, keep]
    )
    a = -m.score_samples(X[:, keep])
    return m, keep, float(np.quantile(a, 1 - fpr))


def _anom(model, X):
    if model is None or len(X) == 0:
        return np.zeros(len(X))
    m, keep, _ = model
    return -m.score_samples(np.asarray(X, dtype=float)[:, keep])


def run_seed(users):
    """ประเมินทุก event ผ่านทั้ง 4 ชั้น เก็บผลแยกชั้น."""
    rows = []
    shap_pool = []  # (X_all23 ของ event ที่ L3-all23 ยิง, label)
    for alias, u in users.items():
        prof = LC.build_profile(u["train_raw"][:SIZE])
        tv, tr_ = u["train_ft"][:SIZE], u["train_raw"][:SIZE]
        base = O._baseline(tv)

        # L3-all23: IForest บนฟีเจอร์ดิบทั้ง 23
        m_all = _fit_if(tv)
        # L3-seq: IForest บน residual window (แบบ production)
        tres = [SEQ._resid(v, r, prof, base) for v, r in zip(tv, tr_)]
        m_seq = _fit_if(
            [SEQ._winfeat(tres[i - W + 1 : i + 1]) for i in range(W - 1, len(tres))]
        )
        tail = tres[-(W - 1) :]

        def evaluate(pairs, label, scen):
            if not pairs:
                return
            vecs = [v for _, v in pairs]
            a_all = _anom(m_all, vecs)
            # window features สำหรับ L3-seq
            wins, run = [], list(tail)
            for raw, vec in pairs:
                r = SEQ._resid(vec, raw, prof, base)
                w = (run + [r])[-W:]
                while len(w) < W:
                    w = [w[0]] + w
                wins.append(SEQ._winfeat(w))
                run.append(r)
            a_seq = _anom(m_seq, wins)
            thr_all = m_all[2] if m_all else 1e9
            thr_seq = m_seq[2] if m_seq else 1e9

            for (raw, vec), aa, asq in zip(pairs, a_all, a_seq):
                rule = evaluate_rules(
                    vec, db=None, user_id=alias, ip=None, geo_country=None
                )
                beh = evaluate_behavior(
                    vec,
                    prof,
                    subsystem_id=raw.get("subsystem"),
                    user_agent=raw.get("user_agent"),
                )
                # decision ถ้าแต่ละชั้นทำงานลำพัง
                l1_alone = "block" if rule.blocked else _decide(rule.score)
                if getattr(rule, "min_action", None):
                    l1_alone = max(l1_alone, rule.min_action, key=lambda d: RANK[d])
                l2_alone = _decide(beh.score)
                if getattr(beh, "min_action", None):
                    l2_alone = max(l2_alone, beh.min_action, key=lambda d: RANK[d])
                l3_all_fired = bool(aa >= thr_all)
                l3_seq_fired = bool(asq >= thr_seq)
                # L4: fusion จริง (L1+L2 ผ่าน aggregate) + L3-seq เป็น surfacing channel
                fused = aggregate(rule, beh, NEUTRAL)
                final = fused.decision
                if l3_seq_fired and RANK[final] < RANK["warn"]:
                    final = "warn"
                rows.append(
                    dict(
                        label=label,
                        scenario=scen(raw),
                        alias=alias,
                        l1=l1_alone,
                        l2=l2_alone,
                        l3_all=l3_all_fired,
                        l3_seq=l3_seq_fired,
                        base=fused.decision,
                        final=final,
                        rule_score=rule.score,
                        beh_score=beh.score,
                        a_all=float(aa),
                        a_seq=float(asq),
                    )
                )
                if l3_all_fired:
                    shap_pool.append((vec, label))

        evaluate(u["test"], 0, lambda r: "normal")
        byscn = {}
        for raw, vec in u["attacks"]:
            byscn.setdefault(raw["scenario"], []).append((raw, vec))
        for scn, pairs in byscn.items():
            pairs.sort(key=lambda p: p[0]["created_at"])
            evaluate(pairs, 1, lambda r: r["scenario"])
    return rows, shap_pool


def layer_metrics(rows):
    """ผลแยกชั้น: standalone / unique / overlap + combined."""
    atk = [r for r in rows if r["label"] == 1]
    nor = [r for r in rows if r["label"] == 0]
    wn = lambda d: RANK[d] >= RANK["warn"]  # noqa: E731
    ch = lambda d: RANK[d] >= RANK["challenge"]  # noqa: E731

    def flag(r, layer):
        if layer == "l1":
            return wn(r["l1"])
        if layer == "l2":
            return wn(r["l2"])
        return r[layer]  # l3_all / l3_seq = bool

    out = {}
    for layer in ("l1", "l2", "l3_all", "l3_seq"):
        others = [x for x in ("l1", "l2", "l3_seq") if x != layer]
        out[layer] = dict(
            standalone=sum(flag(r, layer) for r in atk) / len(atk),
            fpr=sum(flag(r, layer) for r in nor) / len(nor),
            unique=sum(
                1 for r in atk if flag(r, layer) and not any(flag(r, o) for o in others)
            )
            / len(atk),
            overlap=sum(
                1 for r in atk if flag(r, layer) and any(flag(r, o) for o in others)
            )
            / len(atk),
        )
    out["combined"] = dict(
        recall=sum(ch(r["final"]) for r in atk) / len(atk),
        surfaced=sum(wn(r["final"]) for r in atk) / len(atk),
        cfpr=sum(ch(r["final"]) for r in nor) / len(nor),
        wfpr=sum(wn(r["final"]) for r in nor) / len(nor),
        precision=(
            sum(ch(r["final"]) for r in atk)
            / max(
                1, sum(ch(r["final"]) for r in atk) + sum(ch(r["final"]) for r in nor)
            )
        ),
        n_atk=len(atk),
        n_nor=len(nor),
    )
    return out


def shap_analysis(users, shap_pool, sample=300):
    """SHAP บน L3-all23 — วัด DuplicateRatio + top features (แผน §6)."""
    import shap

    alias0 = next(iter(users))
    tv = users[alias0]["train_ft"][:SIZE]
    fit = _fit_if(tv)
    if fit is None or not shap_pool:
        return None
    m, keep, _ = fit
    names = [f for f, k in zip(FEATURES, keep) if k]

    X = np.array([v for v, _ in shap_pool], dtype=float)[:, keep]
    labels = np.array([lb for _, lb in shap_pool])
    if len(X) > sample:
        idx = np.random.RandomState(0).choice(len(X), sample, replace=False)
        X, labels = X[idx], labels[idx]

    phi = np.abs(shap.TreeExplainer(m).shap_values(X, check_additivity=False))

    # parity check ด้วย PermutationExplainer บน sample เล็ก (ตามแผน §6)
    f = lambda z: -m.score_samples(z)  # noqa: E731
    bg = np.asarray(tv, dtype=float)[:60, keep]
    pex = shap.PermutationExplainer(f, bg)
    n_par = min(8, len(X))
    sv = pex(X[:n_par]).values
    parity = float(np.max(np.abs(f(X[:n_par]) - (sv.sum(1) + f(bg).mean()))))

    def ratio(mask):
        p = phi[mask]
        if len(p) == 0:
            return 0.0, 0.0, 0.0
        tot = p.sum(axis=1)
        tot[tot == 0] = 1e-9
        own12 = p[:, [i for i, n in enumerate(names) if n in L1_OWNED + L2_OWNED]].sum(
            axis=1
        )
        own3 = p[:, [i for i, n in enumerate(names) if n in L3_ONLY]].sum(axis=1)
        geo = p[:, [i for i, n in enumerate(names) if n in GEO_DEAD]].sum(axis=1)
        return (
            float((own12 / tot).mean()),
            float((own3 / tot).mean()),
            float((geo / tot).mean()),
        )

    top = sorted(zip(names, phi.mean(axis=0)), key=lambda x: -x[1])[:8]
    return dict(
        n=len(X),
        n_attack=int(labels.sum()),
        parity=parity,
        dup_all=ratio(np.ones(len(X), bool)),
        dup_attack=ratio(labels == 1),
        dup_normal=ratio(labels == 0),
        top=top,
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=Path, default=BP.DEFAULT_USERS_XLSX)
    ap.add_argument("--seeds", type=int, nargs="+", default=[42, 43, 44])
    args = ap.parse_args()
    import time

    acc, pool0, users0 = [], None, None
    for seed in args.seeds:
        BP.SEED = seed
        t0 = time.time()
        users = LC.gen_all(args.users)
        rows, pool = run_seed(users)
        acc.append(layer_metrics(rows))
        if pool0 is None:
            pool0, users0 = pool, users
        print(f"seed {seed} done ({time.time() - t0:.0f}s)", flush=True)

    print("\ncomputing SHAP (TreeExplainer bulk + Permutation parity)...", flush=True)
    sh = shap_analysis(users0, pool0)
    _report(acc, sh, args.seeds)
    _print(acc, sh)


def _agg(acc, layer, key):
    return O.ci95([a[layer][key] for a in acc])


def _print(acc, sh):
    print("=" * 74)
    print(f"ผลแยกชั้น (mean±CI95, {len(acc)} seeds, size {SIZE})")
    print(f"  {'ชั้น':16}{'standalone':>14}{'unique':>13}{'overlap':>13}{'FPR':>12}")
    for layer, lab in [
        ("l1", "L1 Rule"),
        ("l2", "L2 Behavior"),
        ("l3_all", "L3 IForest-23"),
        ("l3_seq", "L3 IForest-seq"),
    ]:
        s, u, o, f = (
            _agg(acc, layer, k) for k in ("standalone", "unique", "overlap", "fpr")
        )
        print(
            f"  {lab:16}{s[0]*100:>9.1f}±{s[1]*100:<4.1f}{u[0]*100:>8.1f}±{u[1]*100:<4.1f}"
            f"{o[0]*100:>8.1f}±{o[1]*100:<4.1f}{f[0]*100:>7.1f}±{f[1]*100:<4.1f}"
        )
    c = acc[0]["combined"]
    print(
        f"\n  L4 รวม: recall {_agg(acc,'combined','recall')[0]:.1%} · "
        f"surfaced {_agg(acc,'combined','surfaced')[0]:.1%} · "
        f"cFPR {_agg(acc,'combined','cfpr')[0]:.1%} · "
        f"wFPR {_agg(acc,'combined','wfpr')[0]:.1%} · "
        f"precision {_agg(acc,'combined','precision')[0]:.1%}"
    )
    print(f"  (attack {c['n_atk']} · normal {c['n_nor']})")
    if sh:
        print(
            f"\nSHAP บน L3-all23 (n={sh['n']}, attack {sh['n_attack']}) "
            f"· parity(Permutation) diff={sh['parity']:.2e}"
        )
        for lab, key in [
            ("ทั้งหมด", "dup_all"),
            ("attack", "dup_attack"),
            ("normal", "dup_normal"),
        ]:
            d12, d3, dg = sh[key]
            print(
                f"  {lab:8} DuplicateRatio(L1/L2)={d12:.1%} · L3-only={d3:.1%} · geo(ตาย)={dg:.1%}"
            )
        print("  top features: " + ", ".join(f"{n}({v:.3f})" for n, v in sh["top"][:6]))


def _report(acc, sh, seeds):
    L = [
        "# การทดลองรวม 4 ชั้น — L1 Rule + L2 Behavior + L3 IsolationForest(+SHAP) + L4 Fusion\n",
        "**วันที่:** 26 ส.ค. 2026  ",
        f"**seeds:** {seeds} (mean ± 95% CI) · size {SIZE} events/user · ชุดทดสอบเดียวกันทุก seed",
        "**ชุด attack:** obvious (11) + subtle (5) + campaign (low-and-slow multi-phase)\n",
        "\n## 1. ผลแยกชั้น\n",
        "- **standalone** = ชั้นนั้นจับได้เท่าไรถ้าทำงานลำพัง (warn+)",
        "- **unique** = attack ที่เฉพาะชั้นนั้นจับได้ (ชั้นอื่นพลาดหมด)",
        "- **overlap** = จับได้แต่ชั้นอื่นก็จับได้ด้วย\n",
        "| ชั้น | standalone | unique | overlap | FPR |",
        "|---|---|---|---|---|",
    ]
    for layer, lab in [
        ("l1", "L1 Rule"),
        ("l2", "L2 Behavior"),
        ("l3_all", "L3 IForest-23 ฟีเจอร์"),
        ("l3_seq", "L3 IForest-sequence"),
    ]:
        s, u, o, f = (
            _agg(acc, layer, k) for k in ("standalone", "unique", "overlap", "fpr")
        )
        L.append(
            f"| {lab} | {s[0]*100:.1f}±{s[1]*100:.1f} | {u[0]*100:.1f}±{u[1]*100:.1f} "
            f"| {o[0]*100:.1f}±{o[1]*100:.1f} | {f[0]*100:.1f}±{f[1]*100:.1f} |"
        )
    c = acc[0]["combined"]
    L += [
        "\n## 2. ผลรวมหลัง L4 fusion\n",
        "| ตัวชี้วัด | ค่า |",
        "|---|---|",
        f"| Recall (challenge+) | {_agg(acc,'combined','recall')[0]:.1%} ± {_agg(acc,'combined','recall')[1]*100:.1f} |",
        f"| Surfaced (warn+) | {_agg(acc,'combined','surfaced')[0]:.1%} |",
        f"| Precision | {_agg(acc,'combined','precision')[0]:.1%} |",
        f"| Challenge FPR | {_agg(acc,'combined','cfpr')[0]:.1%} |",
        f"| Warn FPR | {_agg(acc,'combined','wfpr')[0]:.1%} |",
        f"| ขนาดชุดทดสอบ | attack {c['n_atk']} · normal {c['n_nor']} |",
    ]
    if sh:
        L += [
            "\n## 3. SHAP บน L3 (IsolationForest 23 ฟีเจอร์)\n",
            f"**ตัวอย่าง:** {sh['n']} เหตุการณ์ที่ L3 ยิง (attack {sh['n_attack']})  ",
            f"**Parity check:** PermutationExplainer diff = `{sh['parity']:.2e}` "
            "(TreeExplainer ใช้จัดอันดับได้ rank-corr=1.00 แต่ไม่ additive กับ `-score_samples`)\n",
            "### DuplicateRatio — SHAP มาจากฟีเจอร์ของชั้นไหน\n",
            "| กลุ่ม | L1/L2-owned | L3-only | geo (ตายเพราะ NAT) |",
            "|---|---|---|---|",
        ]
        for lab, key in [
            ("ทั้งหมด", "dup_all"),
            ("attack", "dup_attack"),
            ("normal", "dup_normal"),
        ]:
            d12, d3, dg = sh[key]
            L.append(f"| {lab} | **{d12:.1%}** | {d3:.1%} | {dg:.1%} |")
        L += [
            "\n> เกณฑ์ตามแผน: DuplicateRatio > 70% = L3 ส่วนใหญ่ตรวจซ้ำกับ L1/L2\n",
            "\n### Top features ที่ขับเคลื่อน anomaly score\n",
            "| # | feature | mean \\|SHAP\\| |",
            "|---|---|---|",
        ]
        for i, (n, v) in enumerate(sh["top"], 1):
            L.append(f"| {i} | `{n}` | {v:.4f} |")
    (REPORTS / "exp_4layer_full_2026-08-26.md").write_text(
        "\n".join(L), encoding="utf-8"
    )
    print("\nreport ->", REPORTS / "exp_4layer_full_2026-08-26.md")


if __name__ == "__main__":
    main()
