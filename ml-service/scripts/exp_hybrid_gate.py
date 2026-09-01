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
from dataclasses import dataclass
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
    """sequence-residual รายคน — คืน (model, base, profile, train_residuals)."""
    prof = LC.build_profile(u.train_raw)
    if prof is None or size < MIN_TRAIN_FOR_SEQUENCE:
        return None, None, prof, []
    base = OWN._baseline(u.train_ft)
    res = [SEQL._resid(v, r, prof, base) for v, r in zip(u.train_ft, u.train_raw)]
    model = E3._fit(E3._windows_per_episode(res, G3.episode_bounds(raw_user, size)))
    return model, base, prof, res


def sequence_score(model, base, prof, train_res, rows_vecs) -> list[float | None]:
    """คะแนน sequence ต่อเหตุการณ์ — **ทำ window แบบเดียวกับ production เป๊ะ**.

    production: window = residual 4 แถวสุดท้ายของ history + residual ของเหตุการณ์นี้
    (`_load_tail()` + residual ปัจจุบัน ใน ml-service/app/sequence.py)

    เดิมผมรวมทุกเหตุการณ์เป็น episode เดียวแล้วเลื่อน window ซึ่ง (1) ไม่ตรงกับ
    production และ (2) `_windows_per_episode(res, [0])` คืนลิสต์ว่างเพราะ
    `zip(bounds, bounds[1:])` ต้องการขอบสองค่า -> sequence ไม่เคยถูกคำนวณเลย
    ทำให้ Config D เท่ากับ B ทุกตัวเลข (บั๊กที่จับได้ 2 ก.ย. 2569)
    """
    if model is None or not train_res:
        return [None] * len(rows_vecs)
    tail = list(train_res[-(E3.W - 1) :])
    out: list[float | None] = []
    for raw, vec in rows_vecs:
        r = SEQL._resid(vec, raw, prof, base)
        w = (tail + [r])[-E3.W :]
        while len(w) < E3.W:
            w = [w[0]] + w
        out.append(float(E3._anom(model, [SEQL._winfeat(w)])[0]))
    return out


# ══════════════════════════ ประเมินหนึ่ง split ══════════════════════════
@dataclass
class EventCtx:
    """ผลของชั้น L1/L2/L3 ต่อหนึ่งเหตุการณ์ — คำนวณ **ครั้งเดียว** ใช้ซ้ำทุก config.

    สองเหตุผล:
      1. เร็วขึ้นราว 6 เท่า (เดิมคำนวณ policy/rule/behavior ใหม่ทุก config)
      2. **รับประกันว่าทุก config เห็นข้อมูลชุดเดียวกันเป๊ะ** ซึ่งเป็นเงื่อนไข
         ที่ต้องเป็นจริงถ้าจะเทียบกันได้ — ถ้าคำนวณแยกอาจต่างกันโดยไม่ตั้งใจ
    """

    user: str
    is_attack: bool
    family: str | None
    campaign: str | None
    policy: object
    rule: object
    behavior: object
    l3: CFG.L3Scores
    layer_ms: float = 0.0


def compute_layer_outputs(
    splits, point_model, seq_models, which: str
) -> list[EventCtx]:
    """เรียก Policy Gate + L1 + L2 + L3 ครั้งเดียวต่อเหตุการณ์."""
    out: list[EventCtx] = []
    for alias, u in splits.items():
        model, base, prof, train_res = seq_models[alias]
        if which == "tune":
            normals = [(None, v) for v in u.tune_normal_ft]
            attacks = u.tune_attacks
        else:
            normals = u.holdout_normal
            attacks = u.holdout_attacks

        for is_atk, pairs in ((False, normals), (True, attacks)):
            seq = sequence_score(
                model, base, prof, train_res, [(r or {}, v) for r, v in pairs]
            )
            for (raw, vec), sq in zip(pairs, seq):
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
                out.append(
                    EventCtx(
                        user=alias,
                        is_attack=is_atk,
                        family=raw.get("scenario"),
                        campaign=f"{alias}:{raw.get('scenario')}" if is_atk else None,
                        policy=policy,
                        rule=rule,
                        behavior=beh,
                        l3=CFG.L3Scores(
                            point_raw=point_score(point_model, vec),
                            sequence_raw=sq,
                            sequence_eligible=sq is not None,
                        ),
                        layer_ms=(time.perf_counter() - t0) * 1000,
                    )
                )
    return out


def apply_config(ctxs, cfg, ecdf, gamma, thresholds) -> list[M.EventOutcome]:
    """ใช้ config หนึ่งกับผลของชั้นที่คำนวณไว้แล้ว — ส่วนนี้เท่านั้นที่ต่างกันระหว่าง config."""
    rows: list[M.EventOutcome] = []
    base_cfg = CFG.CONFIGS["B"] if cfg.fusion != "legacy" else cfg
    for c in ctxs:
        t0 = time.perf_counter()
        d = CFG.evaluate(
            cfg,
            c.policy,
            c.rule,
            c.behavior,
            c.l3,
            calibrate_fn=ecdf,
            gamma=gamma,
            thresholds=thresholds,
        )
        fuse_ms = (time.perf_counter() - t0) * 1000
        # counterfactual — ปิดหลักฐาน L3 แต่ใช้ Policy Gate และ fusion ตัวเดียวกัน
        d0 = CFG.evaluate(
            base_cfg,
            c.policy,
            c.rule,
            c.behavior,
            CFG.L3Scores(),
            calibrate_fn=ecdf,
            gamma=gamma,
            thresholds=thresholds,
        )
        ev = d.breakdown.get("evidence", {})
        rows.append(
            M.EventOutcome(
                user=c.user,
                is_attack=c.is_attack,
                family=c.family,
                campaign=c.campaign,
                decision=d.decision,
                score=d.total_score,
                decision_without_l3=d0.decision,
                score_without_l3=d0.total_score,
                l3_evidence=(ev.get("anomaly") or {}).get("evidence_score"),
                l3_abstained=(ev.get("anomaly") or {}).get("abstained", True),
                other_layers_high=any(
                    (ev.get(k) or {}).get("evidence_score", 0)
                    >= thresholds["challenge"]
                    for k in ("rule", "behavior")
                ),
                latency_ms=c.layer_ms + fuse_ms,
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
        model, base, prof, train_res = seq_models[alias]
        for vec in u.cal_normal_ft:
            r = evaluate_rules(vec, db=None, user_id=alias, ip=None, geo_country=None)
            rule_s.append(1.0 if r.blocked else r.score)
            beh_s.append(evaluate_behavior(vec, prof).score)
            p = point_score(point_model, vec)
            if p is not None:
                pt_s.append(p)
        sq = sequence_score(
            model, base, prof, train_res, [({}, v) for v in u.cal_normal_ft]
        )
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
    n_seq = sum(1 for m, *_ in seq_models.values() if m is not None)
    print(
        f"  point model: {'fit' if point_model else 'ไม่มี'} · "
        f"sequence model: {n_seq}/{len(seq_models)} คน"
    )
    print(f"  ECDF layers: {ecdf.layers}")

    thr = {"warn": 0.50, "challenge": 0.70, "block": 0.85}
    t0 = time.perf_counter()
    ctxs = compute_layer_outputs(splits, point_model, seq_models, "tune")
    print(
        f"  คำนวณชั้น L1/L2/L3 ครั้งเดียว: {len(ctxs)} เหตุการณ์ "
        f"({time.perf_counter() - t0:.1f}s) — ใช้ซ้ำทุก config"
    )

    print(
        f"\n{'cfg':4} {'ชื่อ':30} {'recall':>8} {'prec':>7} {'chFPR':>7} "
        f"{'blkFPR':>7} {'L3 eff':>7} {'R@1%':>7}"
    )
    print("-" * 86)
    results = {}
    for key in CFG.ORDER:
        cfg = CFG.CONFIGS[key]
        rows = apply_config(ctxs, cfg, ecdf, 0.35, thr)
        s_ = M.summarize(rows)
        at1 = M.recall_at_fpr(rows, 0.01)
        results[key] = {"summary": vars(s_), "recall_at_1pct_fpr": at1}
        print(
            f"{key:4} {cfg.name[:30]:30} {s_.recall:8.3f} {s_.precision:7.3f} "
            f"{s_.challenge_fpr:7.3f} {s_.block_fpr:7.3f} "
            f"{s_.l3_effective_unique:7.3f} {at1['recall']:7.3f}"
        )

    print("\nคู่เปรียบเทียบ (recall ที่ FPR 1% เท่ากัน — เทียบได้จริง):")
    for a, b, q in CFG.COMPARISONS:
        ra = results[a]["recall_at_1pct_fpr"]["recall"]
        rb = results[b]["recall_at_1pct_fpr"]["recall"]
        print(f"  {a} -> {b}  {q:28} recall@1%FPR {rb - ra:+.4f}")

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
                "results": results,
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
