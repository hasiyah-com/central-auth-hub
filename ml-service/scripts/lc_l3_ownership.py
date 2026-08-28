"""L3 feature-ownership experiment — L3 ควรจับ "ความผิดปกติร่วม" ที่ L1/L2 พลาด ไม่ใช่ยืนยันซ้ำ.

4 configs (ต่างกันแค่ feature set ของ L3 · integration เหมือนกันหมด = bounded bonus):
  A  L1+L2 (ไม่มี L3)
  B  +IForest all-23 (ปัจจุบัน — ทับ L1/L2)
  C  +IForest continuous-owned (~6 ฟีเจอร์ต่อเนื่องที่ L1 ไม่ถือ)
  D  +IForest residual/interaction (per-user z-score หลังเทียบ baseline รายคน)

หลักการ (ตาม user spec):
  - **per-user IForest** เท่านั้น (ไม่ global) + abstain ถ้า trusted < 50
  - **ไม่ใช้ sigmoid**: anomaly = -score_samples · calibrate thr = quantile(val, 0.99) (1% FPR)
  - **bounded bonus**: L3 เพิ่ม <= 0.15 เฉพาะเมื่อ L1+L2 ยัง < challenge (ไม่ยืนยันซ้ำ)
  - **preprocess ต่อคน**: log1p หางยาว, winsorize 0.5-99.5, z จาก median/IQR, ตัด zero-variance
  - **metric สำคัญสุด: L3 unique detection** = attack ที่ L3 ทำให้ surfaced แต่ L1+L2 พลาด
  - หลาย seed + 95% CI

Run: cd hub/backend && SHARED_NAT=true PYTHONPATH=. python ../../ml-service/scripts/lc_l3_ownership.py
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
from sklearn.ensemble import IsolationForest

ML = Path(__file__).resolve().parent
sys.path.insert(0, str(ML))
import build_profiles_v2 as BP  # noqa: E402
import lc_run_4layer as LC  # noqa: E402  (reuse gen_all, build_profile, metrics helpers)

from app.security.iforest_scorer import IForestResult  # noqa: E402
from app.security.risk_aggregator import THRESHOLDS, aggregate  # noqa: E402
from app.security.rule_engine import FEAT, evaluate_rules  # noqa: E402
from app.security.behavior_profiling import evaluate_behavior  # noqa: E402

REPORTS = LC.REPORTS
FEATURES = LC.FEATURES
RANK = LC.RANK
SIZES = LC.SIZES
SEEDS = [42, 43, 44, 45, 46]
SUBTLE = LC.SUBTLE
EXPECTED = LC.EXPECTED
MIN_TRUSTED = 50  # abstain ถ้า train < 50
L3_BONUS_CAP = 0.15
VAL_FPR = 0.01  # 1% FPR budget บน val

NEUTRAL = IForestResult(0.0, 0.0, "neutral")
CONFIGS = ["A_no_l3", "B_all23", "C_continuous", "D_residual"]
CLABEL = {
    "A_no_l3": "A: L1+L2",
    "B_all23": "B: +IForest all-23",
    "C_continuous": "C: +IForest continuous",
    "D_residual": "D: +IForest residual/interaction",
}

# continuous-owned features (config C) — ต่อเนื่อง ที่ L1 ไม่ถือ (ไม่เอา active_subsystem: L1 ถืออยู่)
C_NAMES = [
    "log_minutes_since_last_login",
    "scope_sensitivity_score",
    "passkey_age_days",
    "passkey_last_used_days",
    "weekday_usage_score",
    "hours_from_typical_login_time",
]
C_IDX = [FEAT[n] for n in C_NAMES]


def _decide(total):
    if total >= THRESHOLDS["block"]:
        return "block"
    if total >= THRESHOLDS["challenge"]:
        return "challenge"
    if total >= THRESHOLDS["warn"]:
        return "warn"
    return "allow"


def _winsor(a):
    lo, hi = np.quantile(a, 0.005), np.quantile(a, 0.995)
    return np.clip(a, lo, hi)


def _baseline(train_vecs):
    """median/IQR ต่อฟีเจอร์ (สำหรับ z ของ config D)."""
    X = np.array(train_vecs)
    b = {}
    for name in ["scope_sensitivity_score", "passkey_age_days"]:
        col = X[:, FEAT[name]]
        if name == "passkey_age_days":
            col = np.log1p(np.clip(col, 0, None))
        med = float(np.median(col))
        iqr = float(max(np.quantile(col, 0.75) - np.quantile(col, 0.25), 1e-6))
        b[name] = (med, iqr)
    return b


def l3_input(config, vec, raw, prof, base):
    if config == "B_all23":
        return list(vec)
    if config == "C_continuous":
        v = [vec[i] for i in C_IDX]
        v[2] = math.log1p(max(v[2], 0.0))  # passkey_age -> log
        v[3] = math.log1p(max(v[3], 0.0))  # passkey_last_used -> log
        return v
    # D: residual / interaction (per-user z + rarity) — แต่ละตัวอ่อน แต่ร่วมกัน = ผิดปกติ
    gap = vec[FEAT["log_minutes_since_last_login"]]
    cad_z = (gap - prof["gap_log_median"]) / prof["gap_log_scale"]
    sc = vec[FEAT["scope_sensitivity_score"]]
    sm, si = base["scope_sensitivity_score"]
    scope_z = (sc - sm) / si
    pa = math.log1p(max(vec[FEAT["passkey_age_days"]], 0.0))
    pm, pi = base["passkey_age_days"]
    pa_z = (pa - pm) / pi
    wd = vec[FEAT["weekday_usage_score"]]  # deviation-like อยู่แล้ว
    hft = vec[FEAT["hours_from_typical_login_time"]]  # circular deviation อยู่แล้ว
    tot = prof.get("total", 1)
    srar = 1.0 - (
        prof.get("subsystem_counts", {}).get(raw.get("subsystem"), 0) + 1.0
    ) / (tot + 3)
    return [cad_z, scope_z, pa_z, wd, hft, srar]


def _fit_l3(config, train_vecs, raws, prof, base):
    """fit per-user IForest บน L3 input ที่ preprocess แล้ว + calibrate thr จาก 'train เอง' (ไม่มี val แยกต่อคน)."""
    Xl = np.array(
        [l3_input(config, v, r, prof, base) for v, r in zip(train_vecs, raws)]
    )
    # ตัด zero-variance column
    keep = Xl.std(axis=0) > 1e-9
    if not keep.any():
        return None
    Xl = Xl[:, keep]
    Xl = np.apply_along_axis(_winsor, 0, Xl) if len(Xl) > 10 else Xl
    m = IsolationForest(n_estimators=100, contamination=0.02, random_state=42).fit(Xl)
    a = -m.score_samples(Xl)
    thr = float(np.quantile(a, 1 - VAL_FPR))
    scale = float(max(np.quantile(a, 0.999) - thr, 1e-6))
    return (m, keep, thr, scale)


def _l3_bonus_batch(l3, config, pairs, prof, base):
    """bounded bonus 0-0.15 ต่อแถว — batch score_samples ครั้งเดียว (เลี่ยง per-row ช้า)."""
    if l3 is None or not pairs:
        return [0.0] * len(pairs)
    m, keep, thr, scale = l3
    X = np.array(
        [np.array(l3_input(config, vec, raw, prof, base))[keep] for raw, vec in pairs]
    )
    a = -m.score_samples(X)
    return [
        float(np.clip((x - thr) / scale, 0.0, 1.0)) * L3_BONUS_CAP if x >= thr else 0.0
        for x in a
    ]


def evaluate(users, size, config):
    rows = []  # (label, scenario, base_dec, final_dec)
    for alias, u in users.items():
        prof = LC.build_profile(u["train_raw"][:size])
        train_vecs = u["train_ft"][:size]
        train_raws = u["train_raw"][:size]
        base = _baseline(train_vecs) if len(train_vecs) >= 8 else None
        l3 = None
        if config != "A_no_l3" and size >= MIN_TRUSTED and base is not None:
            # raws ของ train: ต้อง align กับ train_vecs — ใช้ train_raw (มี subsystem)
            l3 = _fit_l3(config, train_vecs, train_raws, prof, base)

        def run(pairs, label, scen_of):
            bonuses = _l3_bonus_batch(l3, config, pairs, prof, base)
            for (raw, vec), bonus in zip(pairs, bonuses):
                rule = evaluate_rules(
                    vec, db=None, user_id=alias, ip=None, geo_country=None
                )
                beh = evaluate_behavior(
                    vec,
                    prof,
                    subsystem_id=raw.get("subsystem"),
                    user_agent=raw.get("user_agent"),
                )
                base_dec = aggregate(rule, beh, NEUTRAL)
                final = base_dec.decision
                # bounded bonus เฉพาะเมื่อ L1+L2 ยังไม่ถึง challenge (ไม่ยืนยันซ้ำ)
                if bonus > 0 and RANK[base_dec.decision] < RANK["challenge"]:
                    final = _decide(min(base_dec.total_score + bonus, 1.0))
                rows.append((label, scen_of(raw), base_dec.decision, final))

        run(u["test"], 0, lambda r: "normal")
        run(u["attacks"], 1, lambda r: r["scenario"])
    return rows


def metrics(rows):
    a = [r for r in rows if r[0] == 1]
    n = [r for r in rows if r[0] == 0]
    ch = lambda d: RANK[d] >= RANK["challenge"]
    wn = lambda d: RANK[d] >= RANK["warn"]
    tp = sum(ch(r[3]) for r in a)
    fp = sum(ch(r[3]) for r in n)
    # L3 unique = attack ที่ final surfaced (warn+) แต่ base (L1+L2) = allow
    uniq = sum(1 for r in a if wn(r[3]) and not wn(r[2]))
    sub = [r for r in a if r[1] in SUBTLE]
    return dict(
        recall=tp / len(a),
        precision=tp / (tp + fp) if tp + fp else 0.0,
        cfpr=fp / len(n),
        wfpr=sum(wn(r[3]) for r in n) / len(n),
        recall_subtle=sum(wn(r[3]) for r in sub) / len(sub) if sub else 0.0,
        l3_unique=uniq / len(a),
        base_recall=sum(ch(r[2]) for r in a) / len(a),
        n_atk=len(a),
        n_norm=len(n),
    )


def ci95(vals):
    v = np.array(vals)
    return float(v.mean()), float(1.96 * v.std(ddof=1) / math.sqrt(len(v))) if len(
        v
    ) > 1 else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=Path, default=BP.DEFAULT_USERS_XLSX)
    ap.add_argument("--seeds", type=int, nargs="+", default=SEEDS)
    args = ap.parse_args()

    import time

    # เก็บ raw metrics: acc[config][size] = list of metric dicts (per seed)
    acc = {c: {s: [] for s in SIZES} for c in CONFIGS}
    for seed in args.seeds:
        BP.SEED = seed
        t0 = time.time()
        users = LC.gen_all(args.users)
        print(f"seed {seed}: gen {time.time()-t0:.0f}s", flush=True)
        for c in CONFIGS:
            for s in SIZES:
                acc[c][s].append(metrics(evaluate(users, s, c)))
        print(f"  seed {seed} evaluated ({time.time()-t0:.0f}s)", flush=True)

    _report(acc, args.seeds)
    _print(acc)


def _agg(acc, c, s, key):
    return ci95([m[key] for m in acc[c][s]])


def _print(acc):
    print("=" * 84)
    for c in CONFIGS:
        print(f"\n[{CLABEL[c]}]  (mean±CI95 ข้าม {len(acc[c][SIZES[0]])} seeds)")
        print(
            f"  {'size':>6}{'recall':>12}{'subtle':>12}{'L3-unique':>14}{'cFPR':>11}{'prec':>11}"
        )
        for s in SIZES:
            r = _agg(acc, c, s, "recall")
            sub = _agg(acc, c, s, "recall_subtle")
            u = _agg(acc, c, s, "l3_unique")
            f = _agg(acc, c, s, "cfpr")
            p = _agg(acc, c, s, "precision")
            print(
                f"  {s:>6}{r[0]*100:>7.0f}±{r[1]*100:<3.0f}{sub[0]*100:>7.0f}±{sub[1]*100:<3.0f}"
                f"{u[0]*100:>9.1f}±{u[1]*100:<3.1f}{f[0]*100:>6.1f}±{f[1]*100:<3.1f}{p[0]*100:>7.0f}±{p[1]*100:<3.0f}"
            )


def _report(acc, seeds):
    L = [
        "# L3 Feature-Ownership Experiment — L3 จับ 'anomaly ร่วม' ที่ L1/L2 พลาดไหม\n",
        "**วันที่:** 25 ส.ค. 2026  \n",
        f"**seeds:** {seeds} (mean ± 95% CI) · sizes {SIZES} · per-user IForest · bounded bonus ≤{L3_BONUS_CAP}\n",
        "**4 configs** (ต่างกันแค่ feature set ของ L3): A=ไม่มี L3 · B=all-23 · "
        "C=continuous-owned · D=residual/interaction (per-user z)\n",
        "**integration:** L3 เพิ่ม bonus เฉพาะเมื่อ L1+L2 ยัง < challenge (ไม่ยืนยันซ้ำ) · "
        "abstain ถ้า train < 50 · anomaly=-score_samples calibrate 99th pct (ไม่ใช้ sigmoid)\n",
        "\n## Metric สำคัญสุด: L3 unique detection (attack ที่ L3 ทำให้ surfaced แต่ L1+L2 พลาด)\n",
        "| config | " + " | ".join(str(s) for s in SIZES) + " |",
        "|---|" + "---|" * len(SIZES),
    ]
    for c in CONFIGS:
        cells = []
        for s in SIZES:
            m, e = _agg(acc, c, s, "l3_unique")
            cells.append(f"{m*100:.1f}±{e*100:.1f}")
        L.append(f"| {CLABEL[c]} | " + " | ".join(cells) + " |")
    L.append("\n## Recall รวม (challenge+) · mean±CI\n")
    L.append("| config | " + " | ".join(str(s) for s in SIZES) + " |")
    L.append("|---|" + "---|" * len(SIZES))
    for c in CONFIGS:
        cells = [
            f"{_agg(acc,c,s,'recall')[0]*100:.0f}±{_agg(acc,c,s,'recall')[1]*100:.0f}"
            for s in SIZES
        ]
        L.append(f"| {CLABEL[c]} | " + " | ".join(cells) + " |")

    # marginal recall over A ที่ size 5000 + verdict
    def marg(c):
        d = [m["recall"] for m in acc[c][5000]]
        a = [m["recall"] for m in acc["A_no_l3"][5000]]
        return ci95([x - y for x, y in zip(d, a)])

    L.append("\n## Marginal recall เหนือ A (config − A) ที่ size 5000\n")
    L.append("| config | Δrecall (pp) mean±CI | Δchallenge-FPR (pp) |")
    L.append("|---|---|---|")
    for c in ["B_all23", "C_continuous", "D_residual"]:
        dm, de = marg(c)
        df = _agg(acc, c, 5000, "cfpr")[0] - _agg(acc, "A_no_l3", 5000, "cfpr")[0]
        verdict = (
            "✅ คุ้ม (≥3pp)"
            if dm * 100 >= 3
            else (
                "⚠️ CI คร่อม 0 → shadow-only"
                if abs(dm) * 100 < de * 100 or dm <= 0
                else "เล็กน้อย"
            )
        )
        L.append(
            f"| {CLABEL[c]} | {dm*100:+.1f} ± {de*100:.1f} | {df*100:+.1f} | {verdict}"
        )
    L.append(
        "\n## เกณฑ์ตัดสิน (ตาม spec)\n"
        "- C/D +recall ≥3–5pp ที่ FPR เท่าเดิม → L3 มีประโยชน์\n"
        "- +1–2pp และ CI คร่อม 0 → shadow-only\n"
        "- FPR เพิ่ม > recall → ปิด L3 จาก online\n"
        "- D ดีกว่า C ชัด → ปัญหาเดิมคือ feature design ไม่ใช่ IForest\n"
    )
    # ชื่อไฟล์แยกตามชุด attack — กันเขียนทับรายงานคนละเงื่อนไข (เคยโดน race)
    name = (
        "l3_ownership_campaign_autogen.md"
        if getattr(LC, "WITH_CAMPAIGN", False)
        else "l3_ownership_nocampaign_autogen.md"
    )
    (REPORTS / name).write_text(chr(10).join(L), encoding="utf-8")
    print("report ->", REPORTS / name)


if __name__ == "__main__":
    main()
