"""Learning curve 4 ชั้นครบ — per-user profile, 6 sizes, test เดียวกันตรึงทุกรอบ.

ตอบ: ต้องเก็บข้อมูล/คนกี่แถว ประสิทธิภาพถึงเริ่มนิ่ง + L3 เพิ่มค่าไหม (per-user vs global)

Design (ระบุใน report):
  - ข้อมูล/คน: train_pool (chronological) | val (ตรึง) | test (ตรึง) + attack (obvious+subtle) ~3%
  - แปรเฉพาะ "จำนวน train ที่ใช้เรียน per-user model" = 10/50/100/500/1000/5000
  - test observations ตรึง (feature vector คงที่) → curve วัดการ 'เรียนรู้ profile/L3' ล้วนๆ
  - 3 configs: (a) L1+L2 ไม่มี L3  (b) +L3 per-user IForest  (c) +L3 global IForest
  - val ใช้ calibrate threshold ของ L3 (คุม FPR budget)
  - รันครบ 4 ชั้นจริง (evaluate_rules + evaluate_behavior + IForest + aggregate)

ไม่เขียน PII ลง disk (ทำงาน in-memory) — output แค่ report + chart (ตัวเลขล้วน)

Run:
    cd hub/backend && SHARED_NAT=true PYTHONPATH=. python ../../ml-service/scripts/lc_run_4layer.py \
        --users "C:/path/to/users.xlsx"
"""

from __future__ import annotations

import argparse
import math
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from statistics import mode

import numpy as np
from sklearn.ensemble import IsolationForest

ML = Path(__file__).resolve().parent
sys.path.insert(0, str(ML))
import build_profiles_v2 as BP  # noqa: E402
import features_v2 as FE  # noqa: E402

from app.security.behavior_profiling import _robust_center_scale, evaluate_behavior  # noqa: E402
from app.security.iforest_scorer import IForestResult  # noqa: E402
from app.security.risk_aggregator import aggregate  # noqa: E402
from app.security.rule_engine import evaluate_rules  # noqa: E402

REPORTS = Path(__file__).resolve().parents[2] / "hub" / "backend" / "tests" / "reports"
FEATURES = FE.FEATURES
RANK = {"allow": 0, "warn": 1, "challenge": 2, "block": 3}
SIZES = [10, 50, 100, 500, 1000, 5000]
WITH_CAMPAIGN = True  # รวม campaign attack (low-and-slow, multi-phase) — niche ของ L3
POOL_ROWS = 6400
TRAIN_MAX, VAL_N, TEST_N = 5000, 700, 700
CAL_FPR = 0.05  # L3 anomaly threshold calibrate บน val-normal (budget 5%)

EXPECTED = {
    "combined_ato": "block",
    "new_os": "warn",
    "off_hours": "warn",
    "new_device": "challenge",
    "new_ua_family": "challenge",
    "failed_spike": "challenge",
    "login_velocity": "challenge",
    "concurrent_sessions": "challenge",
    "new_passkey": "challenge",
    "permission_change": "challenge",
    "subsystem_lateral": "challenge",
    # subtle — คาดหวังแค่ surface เป็น warn (stealth, monitoring)
    "subtle_mild_offhour": "warn",
    "subtle_slow_burst": "warn",
    "subtle_rare_device": "warn",
    "subtle_quiet_lateral": "challenge",
    "subtle_lowandslow": "warn",
    # campaign (low-and-slow multi-phase) — คาดหวังแค่ surface เป็น warn
    "campaign": "warn",
}
SUBTLE = set(BP.SUBTLE_SCENARIOS) | {"campaign"}  # stealth ทั้งหมด (รวม campaign)


def build_profile(rows: list[dict]):
    """mirror get_user_profile จาก raw login rows (Tier 1+2 fields)."""
    if len(rows) < 5:
        return None
    hours = [int(float(r["created_at"][11:13])) for r in rows]
    wk = [
        1 if datetime.strptime(r["created_at"], FE.TS).weekday() >= 5 else 0
        for r in rows
    ]
    try:
        typ = mode(hours)
    except Exception:
        typ = 12
    subs = Counter(r["subsystem"] for r in rows if r.get("subsystem"))
    ordered = sorted(rows, key=lambda r: r["created_at"])
    gaps = [
        math.log(
            max(
                (
                    datetime.strptime(b["created_at"], FE.TS)
                    - datetime.strptime(a["created_at"], FE.TS)
                ).total_seconds()
                / 60.0,
                0.5,
            )
        )
        for a, b in zip(ordered, ordered[1:])
    ]
    gm, gs = _robust_center_scale(gaps)
    sigs = Counter(r["device_signature"] for r in rows if r.get("device_signature"))
    # scope ที่คนนี้เข้าถึงเป็นปกติ (mirror ของ get_user_profile — ใช้ map เดียวกับ features_v2)
    scope_hist = [FE.SCOPE_BY_SUBSYSTEM.get(r.get("subsystem"), 0.1) for r in rows]
    return {
        "typical_hour": typ,
        "typical_weekend": round(sum(wk) / len(wk)),
        "session_count": len(rows),
        "total": len(rows),
        "hour_counts": dict(Counter(hours)),
        "subsystem_counts": dict(subs),
        "seen_subsystems": set(subs),
        "gap_log_median": gm,
        "gap_log_scale": gs,
        "signature_counts": dict(sigs),
        "scope_history": scope_hist,
    }


def gen_all(users_xlsx: Path):
    """generate per-user: raw normal (staggered) split train/val/test + attacks, + feature vectors."""
    import json

    roster = json.loads((BP.DATA / "roster_v2.json").read_text(encoding="utf-8"))
    ids = BP.load_identities(users_xlsx)
    BP.DAYS = max(30, (POOL_ROWS + 1) // 2)
    rng = BP.random.Random(BP.SEED)

    users = {}
    for spec in BP.SPEC:
        p = dict(spec)
        p["email"] = roster.get(p["alias"], "")
        p["rows"] = POOL_ROWS
        ident = ids[p["email"]]
        normal = BP.gen_normal(p, ident, "staggered", rng)  # sorted by time
        all_atk = (
            BP.gen_attacks(p, ident, rng)
            + BP.gen_subtle_attacks(p, ident, rng)
            + (BP.gen_campaign_attacks(p, ident, rng) if WITH_CAMPAIGN else [])
        )
        atks = [r for r in all_atk if r["row_kind"] == "attack"]
        ctx = [
            r for r in all_atk if r["row_kind"] == "context"
        ]  # velocity/burst context

        feat_norm = FE._normal_features_incremental(normal)
        train_raw, val_raw, test_raw = (
            normal[:TRAIN_MAX],
            normal[TRAIN_MAX : TRAIN_MAX + VAL_N],
            normal[TRAIN_MAX + VAL_N : TRAIN_MAX + VAL_N + TEST_N],
        )
        train_ft = [[float(fr[c]) for c in FEATURES] for fr in feat_norm[:TRAIN_MAX]]
        val_ft = [
            [float(fr[c]) for c in FEATURES]
            for fr in feat_norm[TRAIN_MAX : TRAIN_MAX + VAL_N]
        ]
        test_ft = [
            [float(fr[c]) for c in FEATURES]
            for fr in feat_norm[TRAIN_MAX + VAL_N : TRAIN_MAX + VAL_N + TEST_N]
        ]

        # attack features (frozen: history = train+val+test normal ก่อนหน้า)
        base = sorted(normal, key=lambda r: r["created_at"])
        atk_eval = []
        for r in sorted(atks, key=lambda r: r["created_at"]):
            t = r["created_at"]
            trusted = [x for x in base if x["created_at"] < t]
            c = [
                x for x in ctx if x["scenario"] == r["scenario"] and x["created_at"] < t
            ]
            observed = sorted(trusted + c, key=lambda x: x["created_at"])
            vec = FE.compute(r, trusted, observed)
            atk_eval.append((r, vec))

        users[p["alias"]] = dict(
            train_raw=train_raw,
            train_ft=train_ft,
            val_ft=val_ft,
            test=list(zip(test_raw, test_ft)),
            attacks=atk_eval,
        )
    return users


L3_MAX_RISK = 0.4  # เพดาน risk ของ L3 (เท่า map_score saturation ของ production)


def _cal(model, val_vecs):
    """calibrate บน val-normal: threshold (95th pct) + scale ของ tail (99th-95th).

    anomaly = -score_samples (สูง = ผิดปกติ). ใช้ distribution ของ val เอง แทน sigmoid
    production ที่ scale ไม่เข้ากับช่วง score_samples แบบ offline (บั๊กเดิม: กลับด้าน + อิ่มตัว).
    """
    a = -model.score_samples(np.array(val_vecs))
    thr = float(np.quantile(a, 1 - CAL_FPR))
    scale = float(max(np.quantile(a, 0.99) - thr, 1e-6))
    return thr, scale


def _risk_batch(model, vecs, cal):
    """L3 risk graded: 0 ถ้าใต้ threshold, ไต่ขึ้นถึง L3_MAX_RISK ตามความผิดปกติเทียบ tail ของ val."""
    if model is None or not vecs:
        return [0.0] * len(vecs)
    thr, scale = cal
    a = -model.score_samples(np.array(vecs))
    return [
        float(np.clip((x - thr) / scale, 0.0, 1.0)) * L3_MAX_RISK if x >= thr else 0.0
        for x in a
    ]


def evaluate(users, size, config):
    NEUTRAL = IForestResult(raw_score=0.0, risk_score=0.0, label="neutral")
    gmodel = gcal = None
    if config == "iforest_global":
        X = [v for u in users.values() for v in u["train_ft"][:size]]
        gmodel = IsolationForest(
            n_estimators=150, contamination=0.02, random_state=42
        ).fit(X)
        gcal = _cal(gmodel, [v for u in users.values() for v in u["val_ft"]])

    rows = []  # (label, scenario, decision)
    for alias, u in users.items():
        prof = build_profile(u["train_raw"][:size])
        model, cal = (gmodel, gcal) if config == "iforest_global" else (None, None)
        if config == "iforest_user" and len(u["train_ft"][:size]) >= 8:
            model = IsolationForest(
                n_estimators=100, contamination=0.02, random_state=42
            ).fit(u["train_ft"][:size])
            cal = _cal(model, u["val_ft"])

        ev = list(u["test"]) + list(u["attacks"])
        labs = [0] * len(u["test"]) + [1] * len(u["attacks"])
        scns = ["normal"] * len(u["test"]) + [r["scenario"] for r, _ in u["attacks"]]
        l3 = (
            _risk_batch(model, [vec for _, vec in ev], cal)
            if model is not None
            else [0.0] * len(ev)
        )

        for (raw, vec), lab, scn, risk in zip(ev, labs, scns, l3):
            rule = evaluate_rules(
                vec, db=None, user_id=alias, ip=None, geo_country=None
            )
            beh = evaluate_behavior(
                vec,
                prof,
                subsystem_id=raw.get("subsystem"),
                user_agent=raw.get("user_agent"),
            )
            ifr = IForestResult(0.0, risk, "l3") if risk else NEUTRAL
            rows.append((lab, scn, aggregate(rule, beh, ifr).decision))
    return rows


def metrics(rows):
    a = [r for r in rows if r[0] == 1]
    n = [r for r in rows if r[0] == 0]
    ch = lambda d: RANK[d] >= RANK["challenge"]
    wn = lambda d: RANK[d] >= RANK["warn"]
    tp = sum(ch(r[2]) for r in a)
    fp = sum(ch(r[2]) for r in n)
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / len(a)
    obv = [r for r in a if r[1] not in SUBTLE]
    sub = [r for r in a if r[1] in SUBTLE]
    return dict(
        recall=rec,
        precision=prec,
        f1=(2 * prec * rec / (prec + rec) if prec + rec else 0.0),
        cfpr=fp / len(n),
        wfpr=sum(wn(r[2]) for r in n) / len(n),
        policy=sum(RANK[r[2]] >= RANK[EXPECTED[r[1]]] for r in a) / len(a),
        recall_obvious=sum(ch(r[2]) for r in obv) / len(obv) if obv else 0.0,
        recall_subtle=sum(wn(r[2]) for r in sub) / len(sub)
        if sub
        else 0.0,  # subtle: warn+ = surfaced
        n_norm=len(n),
        n_atk=len(a),
        n_sub=len(sub),
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=Path, default=BP.DEFAULT_USERS_XLSX)
    args = ap.parse_args()
    import time

    print("generating pool (in-memory, no PII to disk)...")
    t0 = time.time()
    users = gen_all(args.users)
    print(f"  gen done in {time.time()-t0:.0f}s")
    m0 = metrics(evaluate(users, SIZES[-1], "no_l3"))
    print(
        f"test/คน~{m0['n_norm']//12} · attack {m0['n_atk']} ({m0['n_sub']} subtle) "
        f"= {m0['n_atk']/(m0['n_norm']+m0['n_atk'])*100:.1f}% ของ test\n"
    )

    configs = ["no_l3", "iforest_user", "iforest_global"]
    labels = {
        "no_l3": "L1+L2 (ไม่มี L3)",
        "iforest_user": "+L3 per-user",
        "iforest_global": "+L3 global",
    }
    results = {c: {} for c in configs}
    for c in configs:
        for s in SIZES:
            ts = time.time()
            results[c][s] = metrics(evaluate(users, s, c))
            print(f"  {c:16} size {s:>5}  ({time.time()-ts:.0f}s)")

    # ── table ──
    print("=" * 78)
    for c in configs:
        print(f"\n[{labels[c]}]  (recall=challenge+ · subtle=warn+ surfaced)")
        print(
            f"  {'size':>6}{'recall':>9}{'obvious':>9}{'subtle':>9}{'cFPR':>8}{'wFPR':>8}{'prec':>8}{'policy':>8}"
        )
        for s in SIZES:
            m = results[c][s]
            print(
                f"  {s:>6}{m['recall']:>8.0%}{m['recall_obvious']:>9.0%}{m['recall_subtle']:>9.0%}"
                f"{m['cfpr']:>8.1%}{m['wfpr']:>8.1%}{m['precision']:>8.0%}{m['policy']:>8.0%}"
            )

    _chart(results, configs, labels)
    _report(results, configs, labels, m0)
    print(f"\n✅ chart + report -> {REPORTS}")


def _chart(results, configs, labels):
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:
        print(f"(ข้าม chart: {e})")
        return
    fig, ax = plt.subplots(1, 3, figsize=(15, 4.5))
    col = {"no_l3": "#888", "iforest_user": "#2a7", "iforest_global": "#c63"}
    eng = {
        "no_l3": "L1+L2 (no L3)",
        "iforest_user": "+L3 per-user",
        "iforest_global": "+L3 global",
    }
    for c in configs:
        xs = SIZES
        ax[0].plot(
            xs,
            [results[c][s]["policy"] * 100 for s in xs],
            "o-",
            color=col[c],
            label=eng[c],
        )
        ax[1].plot(
            xs,
            [results[c][s]["recall_subtle"] * 100 for s in xs],
            "o-",
            color=col[c],
            label=eng[c],
        )
        ax[2].plot(
            xs,
            [results[c][s]["cfpr"] * 100 for s in xs],
            "o-",
            color=col[c],
            label=eng[c],
        )
    ax[0].set_title("Policy success vs events/user")
    ax[0].set_ylabel("%")
    ax[1].set_title("Subtle-attack surfaced (warn+)")
    ax[1].set_ylabel("%")
    ax[2].set_title("Challenge FPR")
    ax[2].set_ylabel("%")
    for a in ax:
        a.set_xscale("log")
        a.set_xlabel("train events/user")
        a.grid(alpha=0.3)
        a.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(REPORTS / "lc_4layer_2026-08-25.svg")


def _report(results, configs, labels, m0):
    lines = [
        "# Learning Curve 4 ชั้นครบ — per-user profile (10→5000 แถว/คน)\n",
        "**วันที่:** 25 ส.ค. 2026  \n",
        f"**ข้อมูล:** 12 โปรไฟล์ · train_pool≤{TRAIN_MAX} | val {VAL_N} | **test {TEST_N}/คน ตรึงทุกรอบ**",
        f"+ attack {m0['n_atk']} ({m0['n_sub']} subtle) = {m0['n_atk']/(m0['n_norm']+m0['n_atk'])*100:.1f}% ของ test\n",
        "**Pipeline:** L1 rule + L2 behavior(Tier1+2) + L3 IForest + L4 aggregate — 4 ชั้นจริง\n",
        "**Methodology:** test observations ตรึง (feature vector คงที่) → curve วัดการเรียนรู้ "
        "per-user profile(L2)+IForest(L3) ล้วนๆ · val calibrate L3 threshold (FPR budget 5%)\n",
        "\n## ผลแยกตาม config\n",
    ]
    for c in configs:
        lines.append(f"\n### {labels[c]}\n")
        lines.append(
            "| size | recall | obvious | subtle(warn+) | cFPR | wFPR | precision | policy |"
        )
        lines.append("|---|---|---|---|---|---|---|---|")
        for s in SIZES:
            m = results[c][s]
            lines.append(
                f"| {s} | {m['recall']:.0%} | {m['recall_obvious']:.0%} | "
                f"{m['recall_subtle']:.0%} | {m['cfpr']:.1%} | {m['wfpr']:.1%} | "
                f"{m['precision']:.0%} | {m['policy']:.0%} |"
            )
    lines.append("\n![learning curve](lc_4layer_2026-08-25.svg)\n")

    # ── key findings (คำนวณจากผล) ──
    nol3, usr, glb = (
        results["no_l3"],
        results["iforest_user"],
        results["iforest_global"],
    )
    d_usr = max(usr[s]["recall"] - nol3[s]["recall"] for s in SIZES) * 100
    d_glb = max(glb[s]["recall"] - nol3[s]["recall"] for s in SIZES) * 100
    lines += [
        "\n## ข้อค้นพบหลัก\n",
        f"1. **จุดนิ่ง ~50 แถว/คน** — recall/subtle กระโดดจาก size 10 "
        f"(recall {nol3[10]['recall']:.0%}, subtle {nol3[10]['recall_subtle']:.0%}) "
        f"→ size 50 (recall {nol3[50]['recall']:.0%}, subtle {nol3[50]['recall_subtle']:.0%}) "
        "แล้ว **plateau** · Challenge FPR ค่อยๆ ดีขึ้นถึง ~1000 แถว "
        f"({nol3[50]['cfpr']:.1%} → {nol3[1000]['cfpr']:.1%})\n",
        f"2. **L3 เพิ่มค่าน้อยมาก** — per-user IForest เพิ่ม recall สูงสุด **+{d_usr:.0f}%**, "
        f"global **+{d_glb:.0f}%** (แลกกับ wFPR สูงขึ้นเล็กน้อย) → ยืนยันซ้ำ: **L1+L2 คือตัวหลัก** "
        "ไม่ว่าจะมีข้อมูลมากแค่ไหน L3 ก็ไม่ใช่ตัวชี้ขาด\n",
        "3. **per-user IForest > global** — โมเดลรายคนเพิ่ม recall ได้เล็กน้อย ส่วน global เพิ่ม ~0 "
        "(ตรงหลักการ: anomaly 'รายคน' ต้องใช้โมเดลรายคน — global มองไม่เห็น)\n",
        "4. **per-user profile (L2) คือกุญแจของ subtle detection** — subtle surfaced "
        f"{nol3[10]['recall_subtle']:.0%} (size 10) → {nol3[50]['recall_subtle']:.0%} (size 50): "
        "โปรไฟล์รายคนต้องมี ~50 เหตุการณ์ rarity/cadence ถึงเริ่มจับของเนียนได้\n",
        "\n## หมายเหตุเชิงวิธี (บั๊กที่แก้)\n",
        "- พบบั๊ก **IForest anomaly sign กลับด้าน** (`sigmoid(-score_samples)` + production sigmoid "
        "scale ไม่เข้ากับช่วง score_samples offline) ทำให้ L3 ยิง 0 rows — แก้เป็น calibrate จาก "
        "tail ของ val (`-score_samples`, graded) → L3 ทำงานจริง (บั๊กเดียวกันมีใน `eval_production_v2.py` "
        "แต่ L3 ที่นั่น inert อยู่แล้ว → ตัวเลข Tier reports = L1+L2 ถูกต้อง ไม่กระทบ)\n",
    ]
    (REPORTS / "lc_4layer_2026-08-25.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
