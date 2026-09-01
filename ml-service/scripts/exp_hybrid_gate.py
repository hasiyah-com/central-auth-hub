"""HYBRID GATE — การทดลองของสถาปัตยกรรม Hybrid Risk (L1/L2/L3 -> หลักฐาน, L4 ตัดสิน).

**เส้นทางการประเมินทั้งหมด import จาก production โดยตรง** — ไม่มีสำเนาของ
Policy Gate / calibration / L3 mapping / fusion / threshold อยู่ในไฟล์นี้เลย
(บทเรียน B66: harness เดิมมี `_decide()` และเรียก `aggregate(..., NEUTRAL)`
ซึ่งต่างจาก production จนกลายเป็นการวัดคนละระบบ)

`exp_final_gate.py` ถูกเก็บไว้เป็นหลักฐาน baseline แบบอ่านอย่างเดียว ห้ามต่อยอด

การแบ่งข้อมูลสี่ส่วน (ดู hybrid_experiment/dataset.py):
    train  ->  validation-calibration  ->  validation-tuning  ->  final holdout

ลำดับที่บังคับ:
    1. smoke   ตรวจ 1 seed x 1 size ว่าเส้นทางถูก
    2. tune    รันทุก size/seed บน validation แล้วเลือก gamma/threshold
    3. freeze  เขียนค่าที่เลือกลงไฟล์
    4. final   เปิด holdout **ครั้งเดียว** ด้วยค่าที่ freeze แล้ว

Run:
    cd hub/backend
    PYTHONPATH=. python ../../ml-service/scripts/exp_hybrid_gate.py smoke
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
from sklearn.ensemble import IsolationForest

ML = Path(__file__).resolve().parent
if str(ML) not in sys.path:
    sys.path.insert(0, str(ML))

import exp_lc_v3 as E3  # noqa: E402
import build_profiles_v2 as BP  # noqa: E402
import gen_v3 as G3  # noqa: E402
import lc_l3_ownership as OWN  # noqa: E402
import lc_l3_sequence as SEQL  # noqa: E402
import lc_run_4layer as LC  # noqa: E402
from hybrid_experiment import configs as CFG  # noqa: E402
from hybrid_experiment import dataset as DS  # noqa: E402
from hybrid_experiment import metrics as M  # noqa: E402

from app.security.behavior_profiling import evaluate_behavior  # noqa: E402
from app.security.policy_gate import evaluate_policy  # noqa: E402
from app.security.rule_engine import evaluate_rules  # noqa: E402

ARTIFACTS = ML.parent / "data" / "hybrid_experiment"
FROZEN = ARTIFACTS / "frozen_config.json"
SIZES = [50, 100, 500, 1000, 5000]
SEEDS = [42, 43, 44, 45, 46]
HOLDOUT_SEEDS = [101, 102, 103, 104, 105]
MIN_TRAIN_FOR_SEQUENCE = 100
# ไฟล์ผู้ใช้จริง — gitignored โดยตั้งใจ (ข้อมูลจริงห้ามขึ้น git)
DEFAULT_USERS = BP.DEFAULT_USERS_XLSX


# ══════════════════════════ โมเดล L3 ══════════════════════════
def fit_point_model(train_vectors: list) -> IsolationForest | None:
    """point-all — โมเดลตัวเดียวใช้กับทุกคน (ตรงกับที่ production ใช้)."""
    if len(train_vectors) < 50:
        return None
    X = np.asarray(train_vectors, dtype=float)
    return IsolationForest(n_estimators=100, contamination=0.02, random_state=42).fit(X)


def point_score(model, vec) -> float | None:
    if model is None:
        return None
    return float(-model.score_samples(np.asarray([vec], dtype=float))[0])


def fit_sequence_model(u: DS.UserSplit, size: int, raw_user: dict):
    """sequence-residual รายคน — คืน (model, base, profile) หรือ None."""
    prof = LC.build_profile(u.train_raw)
    if prof is None or size < MIN_TRAIN_FOR_SEQUENCE:
        return None, None, prof
    base = OWN._baseline(u.train_ft)
    res = [SEQL._resid(v, r, prof, base) for v, r in zip(u.train_ft, u.train_raw)]
    model = E3._fit(E3._windows_per_episode(res, G3.episode_bounds(raw_user, size)))
    return model, base, prof


def sequence_score(model, base, prof, rows_vecs) -> list[float | None]:
    """คะแนน sequence ของชุดเหตุการณ์ (ต้องต่อเนื่องกัน)."""
    if model is None:
        return [None] * len(rows_vecs)
    res = [SEQL._resid(v, r, prof, base) for r, v in rows_vecs]
    # ชุดนี้ต่อเนื่องกันเป็น episode เดียว -> bounds = [0]
    wins = E3._windows_per_episode(res, [0])
    if len(wins) == 0:
        return [None] * len(rows_vecs)
    scores = list(E3._anom(model, wins))
    pad = len(rows_vecs) - len(scores)
    return [None] * pad + [float(x) for x in scores]


# ══════════════════════════ ประเมินหนึ่ง split ══════════════════════════
def score_events(
    splits, point_model, seq_models, ecdf, cfg, gamma, thresholds, which: str
):
    """ประเมินทุกเหตุการณ์ของ split ที่ระบุ ด้วย config เดียว."""
    rows: list[M.EventOutcome] = []
    for alias, u in splits.items():
        model, base, prof = seq_models[alias]
        if which == "tune":
            normals = [(None, v) for v in u.tune_normal_ft]
            attacks = u.tune_attacks
        else:
            normals = u.holdout_normal
            attacks = u.holdout_attacks

        for is_atk, pairs in ((False, normals), (True, attacks)):
            seq_scores = sequence_score(
                model, base, prof, [(r or {}, v) for r, v in pairs]
            )
            for (raw, vec), sq in zip(pairs, seq_scores):
                raw = raw or {}
                t0 = time.perf_counter()
                policy = evaluate_policy(vec, None, alias, None, None)
                rule = evaluate_rules(
                    vec, db=None, user_id=alias, ip=None, geo_country=None
                )
                beh = evaluate_behavior(
                    vec,
                    prof,
                    subsystem_id=raw.get("subsystem"),
                    user_agent=raw.get("user_agent"),
                )
                l3 = CFG.L3Scores(
                    point_raw=point_score(point_model, vec),
                    sequence_raw=sq,
                    sequence_eligible=sq is not None,
                )
                d = CFG.evaluate(
                    cfg,
                    policy,
                    rule,
                    beh,
                    l3,
                    calibrate_fn=ecdf,
                    gamma=gamma,
                    thresholds=thresholds,
                )
                # counterfactual — ปิดหลักฐาน L3 แต่ใช้ policy/fusion ตัวเดียวกัน
                d0 = CFG.evaluate(
                    CFG.CONFIGS["B"] if cfg.fusion != "legacy" else cfg,
                    policy,
                    rule,
                    beh,
                    CFG.L3Scores(),
                    calibrate_fn=ecdf,
                    gamma=gamma,
                    thresholds=thresholds,
                )
                lat = (time.perf_counter() - t0) * 1000
                ev = d.breakdown.get("evidence", {})
                other_high = any(
                    (ev.get(k) or {}).get("evidence_score", 0)
                    >= thresholds["challenge"]
                    for k in ("rule", "behavior")
                )
                rows.append(
                    M.EventOutcome(
                        user=alias,
                        is_attack=is_atk,
                        family=raw.get("scenario"),
                        campaign=f"{alias}:{raw.get('scenario')}" if is_atk else None,
                        decision=d.decision,
                        score=d.total_score,
                        decision_without_l3=d0.decision,
                        score_without_l3=d0.total_score,
                        l3_evidence=(ev.get("anomaly") or {}).get("evidence_score"),
                        l3_abstained=(ev.get("anomaly") or {}).get("abstained", True),
                        other_layers_high=other_high,
                        latency_ms=lat,
                    )
                )
    return rows


def fit_all(splits, size, raw_users, ecdf_layers=True):
    """fit โมเดลทุกตัว + ECDF จาก calibration split เท่านั้น."""
    point_model = fit_point_model([v for u in splits.values() for v in u.train_ft])
    seq_models = {
        a: fit_sequence_model(u, size, raw_users[a]) for a, u in splits.items()
    }
    ecdf = DS.ECDF()
    if not ecdf_layers:
        return point_model, seq_models, ecdf

    # ── ECDF จาก calibration split (normal ล้วน) ──
    rule_s, beh_s, pt_s, sq_s = [], [], [], []
    for alias, u in splits.items():
        model, base, prof = seq_models[alias]
        for vec in u.cal_normal_ft:
            r = evaluate_rules(vec, db=None, user_id=alias, ip=None, geo_country=None)
            rule_s.append(1.0 if r.blocked else r.score)
            beh_s.append(evaluate_behavior(vec, prof).score)
            p = point_score(point_model, vec)
            if p is not None:
                pt_s.append(p)
        sq = sequence_score(model, base, prof, [({}, v) for v in u.cal_normal_ft])
        sq_s.extend(x for x in sq if x is not None)
    ecdf.fit("rule", rule_s)
    ecdf.fit("behavior", beh_s)
    ecdf.fit("anomaly_point", pt_s)
    ecdf.fit("anomaly_sequence", sq_s)
    return point_model, seq_models, ecdf


# ══════════════════════════ คำสั่ง ══════════════════════════
def cmd_smoke(args):
    print(f"SMOKE — seed {args.seed} · size {args.size}")
    raw_users = G3.build_seed(args.users, args.seed)
    splits = DS.build(args.users, args.seed, args.size)

    leak = DS.check_leakage(splits)
    print(f"  leakage: {leak}")
    assert leak["clean"], "พบข้อมูล holdout ทับ train — หยุดทันที"

    atk = [v for u in splits.values() for _, v in u.tune_attacks]
    nor = [v for u in splits.values() for v in u.tune_normal_ft]
    short = DS.check_shortcut(atk, nor, LC.FEATURES)
    print(f"  shortcut: {len(short)} feature" + (f" -> {short[:3]}" if short else ""))

    point_model, seq_models, ecdf = fit_all(splits, args.size, raw_users)
    n_seq = sum(1 for m, _, _ in seq_models.values() if m is not None)
    print(
        f"  point model: {'fit' if point_model else 'ไม่มี'} · "
        f"sequence model: {n_seq}/{len(seq_models)} คน"
    )
    print(f"  ECDF layers: {ecdf.layers}")

    thr = {"warn": 0.50, "challenge": 0.70, "block": 0.85}
    print(
        f"\n{'cfg':4} {'ชื่อ':30} {'recall':>8} {'prec':>7} {'chFPR':>7} "
        f"{'blkFPR':>7} {'L3 eff':>7}"
    )
    print("-" * 78)
    results = {}
    for key in CFG.ORDER:
        cfg = CFG.CONFIGS[key]
        rows = score_events(
            splits, point_model, seq_models, ecdf, cfg, 0.35, thr, "tune"
        )
        s = M.summarize(rows)
        results[key] = s
        print(
            f"{key:4} {cfg.name[:30]:30} {s.recall:8.3f} {s.precision:7.3f} "
            f"{s.challenge_fpr:7.3f} {s.block_fpr:7.3f} {s.l3_effective_unique:7.3f}"
        )

    print("\nคู่เปรียบเทียบ:")
    for a, b, q in CFG.COMPARISONS:
        d = results[b].recall - results[a].recall
        df = results[b].challenge_fpr - results[a].challenge_fpr
        print(f"  {a} -> {b}  {q:28} recall {d:+.3f} · challenge FPR {df:+.3f}")

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    out = ARTIFACTS / f"smoke_seed{args.seed}_size{args.size}.json"
    out.write_text(
        json.dumps(
            {
                "seed": args.seed,
                "size": args.size,
                "leakage": leak,
                "shortcut": short,
                "ecdf": ecdf.to_artifact(),
                "results": {k: vars(v) for k, v in results.items()},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nartifact -> {out.relative_to(ML.parent.parent)}")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sm = sub.add_parser("smoke", help="ตรวจเส้นทาง 1 seed x 1 size")
    sm.add_argument("--seed", type=int, default=42)
    sm.add_argument("--size", type=int, default=500)
    sm.add_argument("--users", type=Path, default=DEFAULT_USERS)
    sm.set_defaults(func=cmd_smoke)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
