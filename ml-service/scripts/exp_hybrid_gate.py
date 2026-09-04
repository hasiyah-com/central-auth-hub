"""HYBRID GATE — การทดลองของสถาปัตยกรรม Hybrid Risk (L1/L2/L3 -> หลักฐาน, L4 ตัดสิน).

**เส้นทางการประเมินทั้งหมด import จาก production โดยตรง** — ไม่มีสำเนาของ
Policy Gate / calibration / L3 mapping / fusion / threshold อยู่ในไฟล์นี้เลย
(บทเรียน B66: harness เดิมมี `_decide()` และเรียก `aggregate(..., NEUTRAL)`
ซึ่งต่างจาก production จนกลายเป็นการวัดคนละระบบ)

`exp_final_gate.py` ถูกเก็บไว้เป็นหลักฐาน baseline แบบอ่านอย่างเดียว ห้ามต่อยอด

การแบ่งข้อมูลสี่ส่วน (ดู hybrid_experiment/dataset.py):
    train  ->  validation-calibration  ->  validation-tuning  ->  final holdout

ลำดับที่บังคับ:
    1. smoke    ตรวจ 1 seed x 1 size ว่าเส้นทางถูก (วินิจฉัยเท่านั้น ห้ามใช้สรุปผล)
    2. parity   ยืนยันว่า harness คำนวณเหมือน production ทุกจุด
    3. audit    ตรวจ single-feature shortcut **เฉพาะชุดพัฒนา** (ห้ามแตะ holdout)
    4. prepare  คำนวณและ cache ผลของชั้น L1/L2/L3 ทุก cell
    5. tune     กวาด gamma/threshold บน validation-tuning
    6. freeze   ตรึงค่าที่เลือก + hash ของโค้ดและ split
    7. final    เปิด holdout **ครั้งเดียว** ด้วยค่าที่ freeze แล้ว

holdout จะไม่ถูกอ่านเลยในขั้นที่ 1-6 · `final` ปฏิเสธการรันถ้ายังไม่ freeze
parity ไม่ผ่าน หรือโค้ด/ข้อมูลเปลี่ยนหลัง freeze

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
from hybrid_experiment import sweep as SW  # noqa: E402
from hybrid_experiment import tune as TU  # noqa: E402

from app.security.behavior_profiling import evaluate_behavior  # noqa: E402
from app.security.policy_gate import evaluate_policy  # noqa: E402
from app.security.rule_engine import evaluate_rules  # noqa: E402

ARTIFACTS = ML.parent / "data" / "hybrid_experiment"
FROZEN = ARTIFACTS / "frozen_config.json"
# บันทึกถาวรว่า holdout seed ชุดใดถูกเปิดไปแล้ว (B68) — กันเปิดซ้ำโดยไม่ตั้งใจ
# เช่นตอน optimize ความเร็วของ final ซึ่งเผลอรันบน holdout จริงหลายครั้ง
HOLDOUT_LEDGER = ARTIFACTS / "holdout_ledger.json"
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


def point_scores(model, vecs) -> list[float | None]:
    """เหมือน point_score แต่เรียก sklearn ครั้งเดียวทั้งชุด.

    วัดแล้ว: เรียกทีละแถวใช้ ~7.8 ms/แถว (overhead ของ sklearn ล้วน) -> 6,000 แถว
    กิน ~47 วินาที ต่อหนึ่ง split · เรียกเป็นชุดลดเหลือระดับมิลลิวินาที
    ค่าที่ได้เท่ากันทุกหลัก (เทสใน cmd_parity)
    """
    if model is None:
        return [None] * len(vecs)
    if not vecs:
        return []
    arr = -model.score_samples(np.asarray(vecs, dtype=float))
    return [float(x) for x in arr]


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
    feats = []
    for raw, vec in rows_vecs:
        r = SEQL._resid(vec, raw, prof, base)
        w = (tail + [r])[-E3.W :]
        while len(w) < E3.W:
            w = [w[0]] + w
        feats.append(SEQL._winfeat(w))
    if not feats:
        return []
    # เรียก _anom ครั้งเดียวทั้งชุด — ผลเท่ากับเรียกทีละแถวทุกหลัก
    # (เหตุผลเดียวกับ point_scores: overhead ของ sklearn ต่อการเรียกสูงมาก)
    return [float(x) for x in E3._anom(model, feats)]


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
        elif which == "calib":
            # เฉพาะ normal ของ validation-calibration split — ใช้วัด tail shift ภายใน
            # validation (calib vs tuning) เพื่อประมาณ margin โดยไม่พึ่ง holdout
            normals = [(None, v) for v in u.cal_normal_ft]
            attacks = []
        else:
            normals = u.holdout_normal
            attacks = u.holdout_attacks

        for is_atk, pairs in ((False, normals), (True, attacks)):
            seq = sequence_score(
                model, base, prof, train_res, [(r or {}, v) for r, v in pairs]
            )
            pts = point_scores(point_model, [v for _, v in pairs])
            for (raw, vec), sq, pt in zip(pairs, seq, pts):
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
                            point_raw=pt,
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
        pt_s.extend(
            x for x in point_scores(point_model, u.cal_normal_ft) if x is not None
        )
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
        at1 = M.score_only_ranking(rows, 0.01)
        results[key] = {"summary": vars(s_), "ranking_only_at_1pct": at1}
        print(
            f"{key:4} {cfg.name[:30]:30} {s_.recall:8.3f} {s_.precision:7.3f} "
            f"{s_.challenge_fpr:7.3f} {s_.block_fpr:7.3f} "
            f"{s_.within_config_l3_counterfactual_unique:7.3f} {at1['recall']:7.3f}"
        )

    print("\nคู่เปรียบเทียบ (ranking เท่านั้น — ยังไม่ผ่าน resolver ห้ามอ้างเป็นจุดทำงาน):")
    for a, b, q in CFG.COMPARISONS:
        ra = results[a]["ranking_only_at_1pct"]["recall"]
        rb = results[b]["ranking_only_at_1pct"]["recall"]
        print(f"  {a} -> {b}  {q:28} ranking@1% {rb - ra:+.4f}")

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    out = ARTIFACTS / f"smoke_seed{args.seed}_size{args.size}.json"
    out.write_text(
        json.dumps(
            {
                # ผลชุดนี้ตรวจ harness เท่านั้น 1 seed x 1 size x ค่าเริ่มต้น
                # x วัดบน tuning split -> **ห้ามใช้สรุปเรื่องโมเดลในเล่ม**
                "status": "diagnostic_smoke_only",
                "not_for_model_conclusion": True,
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


# ══════════════════════════ Grid search บน validation-tuning ══════════════════════════
CELLS = ARTIFACTS / "cells"
PROBE_THR = {"warn": 0.5, "challenge": 0.7, "block": 0.85}
CANDIDATE_CONFIG = "E"  # config ที่ใช้เลือก gamma กลาง — candidate หลักของระบบ


def build_records(ctxs, ecdf, cfg, gamma):
    """สร้าง EventRecord ของ (config, gamma) หนึ่ง — resolve ซ้ำได้ทุก threshold.

    `PROBE_THR` ที่ใส่ตอนนี้ไม่มีผลต่อค่าที่เก็บ เพราะทุกฟิลด์ใน `ResolverInput`
    (final_score / min_action / primary_layer / other_evidence) ไม่ขึ้นกับ threshold
    การแปลงเป็น action เกิดทีหลังใน `resolve_action()` ของ production
    """
    from app.security.risk_fusion import ResolverInput

    base_cfg = CFG.CONFIGS["B"]
    recs: list[TU.EventRecord] = []
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
            thresholds=PROBE_THR,
        )
        fuse_ms = (time.perf_counter() - t0) * 1000
        d0 = CFG.evaluate(
            base_cfg if cfg.fusion != "legacy" else cfg,
            c.policy,
            c.rule,
            c.behavior,
            CFG.L3Scores(),
            calibrate_fn=ecdf,
            gamma=gamma,
            thresholds=PROBE_THR,
        )
        ev = d.breakdown.get("evidence", {})
        anom = ev.get("anomaly") or {}
        rec = TU.EventRecord(
            user=c.user,
            is_attack=c.is_attack,
            family=c.family,
            campaign=c.campaign,
            l3_evidence=anom.get("evidence_score"),
            l3_abstained=anom.get("abstained", True),
            max_other_evidence=max(
                (ev.get(k) or {}).get("evidence_score", 0.0)
                for k in ("rule", "behavior")
            ),
            latency_ms=c.layer_ms + fuse_ms,
        )
        if cfg.fusion == "legacy":
            # Config A ตัดสินด้วย threshold เดิมของตัวเอง -> ไม่เข้าร่วมการกวาด
            rec.fixed_decision = d.decision
            rec.fixed_score = d.total_score
            rec.fixed_decision_no_l3 = d0.decision
            rec.fixed_score_no_l3 = d0.total_score
        else:
            rec.resolver = ResolverInput.from_dict(d.breakdown["resolver"])
            rec.resolver_no_l3 = ResolverInput.from_dict(d0.breakdown["resolver"])
        recs.append(rec)
    return recs


def prepare_cell(users, seed, size, raw_users):
    """คำนวณผลของชั้น L1/L2/L3 ของหนึ่ง cell แล้ว cache ลงดิสก์.

    cache ไว้เพราะขั้นตอนนี้แพงที่สุด (generate + fit + score) และการกวาด
    threshold ต้องวนอ่านซ้ำหลายรอบ · ไฟล์อยู่ใน ml-service/data ซึ่ง gitignored
    (ข้อมูลจริงห้ามขึ้น git)
    """
    import pickle

    CELLS.mkdir(parents=True, exist_ok=True)
    path = CELLS / f"cell_s{seed}_n{size}.pkl"
    if path.exists():
        return path
    splits = DS.build(users, seed, size, raw=raw_users)
    leak = DS.check_leakage(splits)
    assert leak["clean"], f"seed {seed} size {size}: holdout ทับ train — หยุด"
    point_model, seq_models, ecdf = fit_all(splits, size, raw_users)
    ctxs = compute_layer_outputs(splits, point_model, seq_models, "tune")
    n_seq = sum(1 for m, *_ in seq_models.values() if m is not None)
    with path.open("wb") as f:
        pickle.dump(
            {
                "seed": seed,
                "size": size,
                "leakage": leak,
                "n_sequence_models": n_seq,
                "n_users": len(splits),
                "ecdf": ecdf,
                "ctxs": ctxs,
            },
            f,
            protocol=pickle.HIGHEST_PROTOCOL,
        )
    return path


def load_cell(seed, size):
    """อ่าน cell ที่ cache ไว้ — ใช้ได้ทั้งตอนรันเป็นสคริปต์และตอน import.

    ตอน prepare สคริปต์นี้ทำงานเป็น `__main__` -> pickle บันทึกคลาส EventCtx ว่า
    อยู่ใน `__main__` · ถ้าโหลดจากสคริปต์อื่นจะหาคลาสไม่เจอ จึงผูกชื่อไว้ให้ก่อน
    (ทำแบบนี้แทนการ re-generate เพื่อไม่ให้ hash ของ split เปลี่ยน)
    """
    import pickle

    main = sys.modules.get("__main__")
    if main is not None and not hasattr(main, "EventCtx"):
        main.EventCtx = EventCtx
    with (CELLS / f"cell_s{seed}_n{size}.pkl").open("rb") as f:
        return pickle.load(f)


def cmd_prepare(args):
    """ขั้นที่ 1 ของการ tune — คำนวณและ cache ทุก cell (ทำซ้ำได้ ข้ามตัวที่มีแล้ว)."""
    seeds = args.seeds or SEEDS
    sizes = args.sizes or SIZES
    print(
        f"PREPARE — {len(seeds)} seeds x {len(sizes)} sizes = "
        f"{len(seeds) * len(sizes)} cells"
    )
    for seed in seeds:
        raw_users = None
        for size in sizes:
            path = CELLS / f"cell_s{seed}_n{size}.pkl"
            if path.exists():
                print(f"  seed {seed} size {size:>5} -> มีแล้ว ข้าม", flush=True)
                continue
            if raw_users is None:
                t0 = time.perf_counter()
                raw_users = G3.build_seed(args.users, seed)
                print(
                    f"  seed {seed}: generate {time.perf_counter() - t0:.0f}s",
                    flush=True,
                )
            t0 = time.perf_counter()
            prepare_cell(args.users, seed, size, raw_users)
            mb = path.stat().st_size / 1e6
            print(
                f"  seed {seed} size {size:>5} -> {time.perf_counter() - t0:.0f}s "
                f"({mb:.0f} MB)",
                flush=True,
            )
    return 0


def cmd_tune(args):
    """กวาด gamma/threshold บน validation-tuning เท่านั้น — holdout ไม่ถูกเปิด.

    กวาดครบ (config x gamma x threshold) ครั้งเดียว แล้วอ่านผลออกมา **สองมุม**:

      global-gamma   ทุก config ใช้ gamma ตัวเดียวกัน (เลือกจาก config candidate)
                     = ค่าที่ระบบจริงจะตั้ง เพราะ deploy ได้ gamma เดียว
      per-config     แต่ละ config อยู่ที่ gamma ของตัวเองที่ดีที่สุด
                     = การเทียบสถาปัตยกรรมอย่างเป็นธรรม ทุกฝ่ายอยู่ที่จุดที่ดีที่สุดของตน
                     ภายใต้งบ FPR เดียวกัน

    ต้องรายงานทั้งสองมุม · ถ้ารายงานแค่มุมเดียวจะตอบผิดข้อใดข้อหนึ่งเสมอ:
    มุมแรกทำให้ config ที่ไม่ได้ถูกใช้เลือก gamma เสียเปรียบ · มุมหลังตอบไม่ได้ว่า
    ระบบจริงที่ตั้ง gamma ได้ค่าเดียวจะทำได้เท่าไร

    gamma ไม่แยกตามขนาดข้อมูลในทั้งสองมุม (ขนาดเปลี่ยนไม่ทำให้ gamma เปลี่ยน)
    """
    seeds = args.seeds or SEEDS
    sizes = args.sizes or SIZES
    cells_meta = [(s, n) for s in seeds for n in sizes]
    missing = [
        (s, n) for s, n in cells_meta if not (CELLS / f"cell_s{s}_n{n}.pkl").exists()
    ]
    if missing:
        print(f"ยังไม่ได้ prepare {len(missing)} cell: {missing[:5]}")
        return 1

    print(f"TUNE — {len(cells_meta)} cells · validation-tuning เท่านั้น", flush=True)
    loaded = {k: load_cell(*k) for k in cells_meta}
    n_events = sum(len(c["ctxs"]) for c in loaded.values())
    print(f"  โหลดแล้ว {n_events:,} เหตุการณ์", flush=True)

    def make_eval(recs: dict):
        def _eval(_gamma, thr):
            # stat_direct = ทางเดียวกันแต่ไม่สร้าง EventOutcome กลางทาง
            # (ลูปนี้ถูกเรียกหลายหมื่นครั้ง) — การตัดสินยังมาจาก resolve_action ของ production
            stats = [TU.stat_direct(r, s, n, thr) for (s, n), r in recs.items()]
            return TU.macro(stats)

        return _eval

    def gammas_for(key: str) -> tuple:
        cfg = CFG.CONFIGS[key]
        # legacy ไม่ใช้ gamma เลย · weighted_sum ก็ไม่ใช้ -> รันค่าเดียวพอ
        if cfg.fusion in ("legacy", "weighted_sum"):
            return (0.0,)
        return SW.GAMMA_GRID

    # ── กวาดครบ (config x gamma) ──
    grid: dict[str, dict[float, dict]] = {k: {} for k in CFG.ORDER}
    for key in CFG.ORDER:
        cfg = CFG.CONFIGS[key]
        for g in gammas_for(key):
            t0 = time.perf_counter()
            recs = {
                k: build_records(c["ctxs"], c["ecdf"], cfg, g)
                for k, c in loaded.items()
            }
            if cfg.fusion == "legacy":
                # ระบบเก่าใช้เกณฑ์ของตัวเอง -> วัดที่จุดทำงานเดิม ไม่กวาด threshold
                stats = [
                    TU.stat_direct(r, s, n, PROBE_THR) for (s, n), r in recs.items()
                ]
                m = TU.macro(stats)
                ok, fails = SW.eligible(m)
                res = {
                    "fixed_operating_point": True,
                    "thresholds": "legacy_internal",
                    "best": {
                        "gamma": None,
                        "thresholds": "legacy_internal",
                        "recall": round(m["recall"], 6),
                        "recall_challenge": round(m["recall_challenge"], 6),
                        "precision": round(m["precision"], 6),
                        "challenge_fpr": round(m["challenge_fpr"], 6),
                        "block_fpr": round(m["block_fpr"], 6),
                        "warn_fpr": round(m["warn_fpr"], 6),
                        "within_config_l3_counterfactual_unique": round(
                            m["within_config_l3_counterfactual_unique"], 6
                        ),
                        "campaign_surfaced": round(m["campaign_surfaced"], 6),
                        "eligible": ok,
                        "violations": fails,
                        "per_size": {
                            str(k2): {
                                "recall": round(v["recall"], 6),
                                "recall_challenge": round(v["recall_challenge"], 6),
                                "challenge_fpr": round(v["challenge_fpr"], 6),
                                "block_fpr": round(v["block_fpr"], 6),
                                "warn_fpr": round(v["warn_fpr"], 6),
                            }
                            for k2, v in m["per_size"].items()
                        },
                    },
                    "eligible": ok,
                    "violations": fails,
                }
            else:
                ns = [
                    r.resolver.final_score
                    for rr in recs.values()
                    for r in rr
                    if not r.is_attack and r.resolver is not None
                ]
                res = SW.search(make_eval(recs), ns, gammas=(g,))
            grid[key][g] = res
            b = res.get("best")
            msg = (
                f"recall {b['recall']:.4f} (ch {b['recall_challenge']:.4f}) · "
                f"prec {b['precision']:.4f} · warnFPR {b['warn_fpr']:.4f} · "
                f"chFPR {b['challenge_fpr']:.4f}"
                + ("" if b.get("eligible", True) else "  (เกินงบ)")
                if b
                else "ไม่มีจุดที่อยู่ในงบ"
            )
            print(
                f"  {key} gamma {g:<5} -> {msg}  [{time.perf_counter() - t0:.0f}s]",
                flush=True,
            )
            del recs

    # ── มุมที่ 1: gamma กลางตัวเดียว เลือกจาก config candidate ──
    cand = grid[CANDIDATE_CONFIG]
    ok_g = [(g, r) for g, r in cand.items() if r.get("best") and r["best"]["eligible"]]
    if ok_g:
        global_gamma = max(
            ok_g,
            key=lambda x: (x[1]["best"]["recall"], x[1]["best"]["precision"], -x[0]),
        )[0]
    else:
        global_gamma = None
    print(f"\n[มุมที่ 1] gamma กลาง (เลือกจาก Config {CANDIDATE_CONFIG}) = {global_gamma}")

    global_view = {}
    for key in CFG.ORDER:
        g = (
            0.0
            if CFG.CONFIGS[key].fusion in ("legacy", "weighted_sum")
            else global_gamma
        )
        r = grid[key].get(g) if g is not None else None
        global_view[key] = {
            "gamma": g,
            "best": (r or {}).get("best"),
            "fixed_operating_point": (r or {}).get("fixed_operating_point", False),
        }

    # ── มุมที่ 2: แต่ละ config อยู่ที่ gamma ที่ดีที่สุดของตัวเอง ──
    per_config_view = {}
    for key in CFG.ORDER:
        cands = [
            (g, r)
            for g, r in grid[key].items()
            if r.get("best") and r["best"]["eligible"]
        ]
        if not cands:
            # legacy อาจเกินงบ -> ยังต้องรายงานจุดทำงานจริงของมัน
            any_best = next(
                ((g, r) for g, r in grid[key].items() if r.get("best")), (None, {})
            )
            per_config_view[key] = {
                "gamma": any_best[0],
                "best": any_best[1].get("best"),
                "eligible": False,
                "fixed_operating_point": any_best[1].get(
                    "fixed_operating_point", False
                ),
            }
            continue
        g, r = max(
            cands,
            key=lambda x: (x[1]["best"]["recall"], x[1]["best"]["precision"], -x[0]),
        )
        per_config_view[key] = {
            "gamma": g,
            "best": r["best"],
            "eligible": True,
            "fixed_operating_point": r.get("fixed_operating_point", False),
        }

    def _row(key, v):
        b = v.get("best")
        if not b:
            return f"{key:4} {CFG.CONFIGS[key].name[:26]:26} {'ไม่มีจุดในงบ':>34}"
        flag = "" if b.get("eligible", True) else "  เกินงบ"
        return (
            f"{key:4} {CFG.CONFIGS[key].name[:24]:24} "
            f"g={str(v['gamma']):<5} {b['recall']:7.4f} {b['recall_challenge']:8.4f} "
            f"{b['precision']:7.4f} {b['warn_fpr']:8.4f} {b['challenge_fpr']:7.4f} "
            f"{b['within_config_l3_counterfactual_unique']:7.4f}{flag}"
        )

    for title, view in (
        ("มุมที่ 1 — gamma กลางตัวเดียว (ค่าที่ระบบจริงจะตั้ง)", global_view),
        ("มุมที่ 2 — แต่ละ config ที่ gamma ดีที่สุดของตัวเอง (เทียบสถาปัตยกรรม)", per_config_view),
    ):
        print(f"\n{title}")
        print(
            f"{'cfg':4} {'ชื่อ':24} {'gamma':<7} {'recall':>7} {'rec@ch':>8} "
            f"{'prec':>7} {'warnFPR':>8} {'chFPR':>7} {'L3 eff':>7}"
        )
        print("-" * 92)
        for key in CFG.ORDER:
            print(_row(key, view[key]))

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    out = ARTIFACTS / "tuning_result.json"
    out.write_text(
        json.dumps(
            {
                "split": "validation-tuning",
                "holdout_touched": False,
                "seeds": seeds,
                "sizes": sizes,
                "n_events": n_events,
                "candidate_config": CANDIDATE_CONFIG,
                "gamma_grid": list(SW.GAMMA_GRID),
                "gamma_grid_passes": SW.GAMMA_GRID_PASSES,
                "global_gamma": global_gamma,
                "global_gamma_view": global_view,
                "per_config_gamma_view": per_config_view,
                "full_grid": grid,
                "note": (
                    "รายงานสองมุมเสมอ — มุมที่ 1 คือค่าที่ deploy ได้จริง (gamma เดียว) "
                    "มุมที่ 2 คือการเทียบสถาปัตยกรรมที่ทุกฝ่ายอยู่ที่จุดดีที่สุดของตน "
                    "ภายใต้งบ FPR เดียวกัน · gamma ไม่แยกตามขนาดข้อมูลในทั้งสองมุม"
                ),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nartifact -> {out.relative_to(ML.parent.parent)}")
    return 0


# ══════════════════════════ Final holdout (เปิดครั้งเดียวหลัง freeze) ══════════════════════════


def _load_holdout_ledger() -> dict:
    """อ่าน ledger ของ holdout ที่เปิดแล้ว — คีย์คือ seed ที่เรียงแล้วคั่นด้วย comma."""
    if not HOLDOUT_LEDGER.exists():
        return {}
    try:
        return json.loads(HOLDOUT_LEDGER.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _record_holdout_open(seeds, git_commit: str) -> None:
    """บันทึกว่า holdout seed ชุดนี้ถูกเปิด — เพิ่ม open_count ถ้าเปิดซ้ำ.

    ledger เป็นหลักฐานถาวรว่า seed ใดใช้ไปแล้ว · ห้ามลบ entry (ลบ = เปิดโอกาสให้
    เปิดซ้ำเงียบๆ) · ไฟล์ gitignored (อยู่ใน ml-service/data)
    """
    ledger = _load_holdout_ledger()
    key = ",".join(str(x) for x in sorted(seeds))
    now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    if key in ledger:
        ledger[key]["open_count"] = ledger[key].get("open_count", 1) + 1
        ledger[key]["last_opened_at"] = now
        ledger[key].setdefault("reopened", True)
    else:
        ledger[key] = {
            "seeds": sorted(seeds),
            "first_opened_at": now,
            "last_opened_at": now,
            "open_count": 1,
            "frozen_commit": git_commit,
        }
    HOLDOUT_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    HOLDOUT_LEDGER.write_text(
        json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _final_gate(results: dict, fz: dict) -> dict:
    """สร้าง gate verdict ต่องบ FPR ที่ประกาศไว้ — **per-size** pass/fail ต่อ config.

    candidate/ fallback ถูกประกาศ**ล่วงหน้า**ใน frozen config · การเลือก config ที่
    ผ่านงบแบบย้อนหลัง (post-hoc) ห้ามทำ — gate แค่ตรวจว่า candidate ที่ประกาศไว้ผ่านไหม

    **per-size ไม่ใช่ macro** (ตัดสิน 2026-09-04): `sweep.eligible()` ตอน tune ตรวจ
    ทุกขนาด → gate ต้องใช้มาตรฐานเดียวกัน ไม่งั้น config ที่ผ่าน macro แต่ทะลุงบที่
    cold-start (size เล็ก) จะถูกนับว่าผ่านทั้งที่ผู้ใช้ประวัติน้อยรับภาระเกินงบ ·
    macro ยังเก็บไว้เป็นข้อมูลประกอบ แต่ passed ตัดสินจาก per-size
    """
    budgets = fz.get(
        "fpr_budgets",
        {
            "warn": SW.WARN_FPR_BUDGET,
            "challenge": SW.CHALLENGE_FPR_BUDGET,
            "block": SW.BLOCK_FPR_BUDGET,
        },
    )
    deployed = fz.get("deployed_config", CANDIDATE_CONFIG)
    per_config = {}
    for key, r in results.items():
        m = r["macro"]
        fails = []  # per-size violations — มาตรฐานเดียวกับ tune
        for size, v in m.get("per_size", {}).items():
            for lvl in ("warn", "challenge", "block"):
                if v[f"{lvl}_fpr"] > budgets[lvl]:
                    fails.append(f"{lvl}@{size}={v[f'{lvl}_fpr'] * 100:.2f}%")
        macro_fails = [
            f"{lvl}_macro={m[f'{lvl}_fpr'] * 100:.2f}%"
            for lvl in ("warn", "challenge", "block")
            if m[f"{lvl}_fpr"] > budgets[lvl]
        ]
        per_config[key] = {
            "warn_fpr": round(m["warn_fpr"], 6),
            "challenge_fpr": round(m["challenge_fpr"], 6),
            "block_fpr": round(m["block_fpr"], 6),
            "passed": not fails,  # per-size เป็นเกณฑ์ตัดสิน
            "violations": fails,
            "macro_passed": not macro_fails,
            "macro_violations": macro_fails,
            "gate_standard": "per_size",
        }
    cand_pass = per_config.get(deployed, {}).get("passed", False)
    return {
        "budgets": budgets,
        "declared_candidate": deployed,
        "declared_fallback": fz.get("declared_fallback", "shadow / current deployment"),
        "candidate_passed": cand_pass,
        "per_config": per_config,
        "verdict": (
            f"candidate (Config {deployed}) ผ่าน Final Gate — พร้อมพิจารณา deploy"
            if cand_pass
            else (
                f"candidate (Config {deployed}) ไม่ผ่าน Final Gate — ไม่มี config ใหม่ "
                "พร้อม deploy · ห้ามเลือก config อื่นที่ผ่านงบแบบย้อนหลัง (post-hoc)"
            )
        ),
    }


def cmd_final(args):
    """วัดผลบน final holdout — **ครั้งเดียว** ด้วยค่าที่ freeze แล้วเท่านั้น.

    ปฏิเสธการรันถ้า:
      * ยังไม่ freeze
      * parity ยังไม่ผ่าน
      * โค้ดที่ให้คะแนนเปลี่ยนหลัง freeze (hash ไม่ตรง)
      * split เปลี่ยนหลัง freeze (hash ไม่ตรง)

    การตรวจ shortcut ของ holdout ทำ **ที่นี่** เท่านั้น ไม่ทำก่อน freeze —
    การเห็น AUC ของ holdout ก่อน freeze ก็ถือว่าเปิดดูข้อมูลแล้ว
    """
    from hybrid_experiment import audit as AU
    from hybrid_experiment import bootstrap as BS

    ok, problems = check_frozen_intact()
    if not ok:
        print("ปฏิเสธการเปิด final holdout:")
        for x in problems:
            print(f"  - {x}")
        return 1
    fz = json.loads(FROZEN.read_text(encoding="utf-8"))
    seeds = fz.get("holdout_seeds") or fz["seeds"]

    # ── B68: holdout ledger — กันเปิด seed ชุดเดิมซ้ำ ──
    # ledger บันทึกถาวรว่า seed ชุดใดถูกเปิดไปแล้ว · การเปิดซ้ำทำลายการรับประกัน
    # "เปิดครั้งเดียว" แม้ผลจะ deterministic (เพราะการรันซ้ำระหว่าง optimize เปิดโอกาส
    # ให้ปรับโค้ด/threshold ตามที่เห็นได้) · ต้องใช้ --reopen-spent-holdout อย่างตั้งใจ
    # เท่านั้นถึงจะเปิดซ้ำ และจะถูกบันทึกว่าเป็นการเปิดซ้ำ
    spent = _load_holdout_ledger()
    seed_key = ",".join(str(x) for x in sorted(seeds))
    if seed_key in spent and not args.reopen_spent_holdout:
        entry = spent[seed_key]
        print(
            f"ปฏิเสธ: holdout seeds {seeds} ถูกเปิดไปแล้ว {entry.get('open_count', 1)} ครั้ง"
        )
        print(
            f"  เปิดครั้งแรก {entry.get('first_opened_at')} · frozen {entry.get('frozen_commit','')[:12]}"
        )
        print("  holdout ที่เปิดแล้วใช้เป็น final ที่บริสุทธิ์อีกไม่ได้ (B68)")
        print("  ถ้าจำเป็นต้องเปิดซ้ำจริง ใส่ --reopen-spent-holdout และบันทึกเหตุผลในรายงาน")
        return 1
    if (ARTIFACTS / "final_result.json").exists() and not args.i_know_this_is_a_rerun:
        print("มีผล final อยู่แล้ว — holdout ต้องเปิดครั้งเดียว")
        print("ถ้าจำเป็นต้องรันซ้ำจริง ใส่ --i-know-this-is-a-rerun และบันทึกเหตุผลในรายงาน")
        return 1
    sizes = fz["sizes"]
    gamma_map = fz["per_config_gamma"]
    thr_map = fz["per_config_thresholds"]
    deployed = fz.get("deployed_config", CANDIDATE_CONFIG)
    print(
        f"FINAL HOLDOUT — view {fz['frozen_view']} · deployed Config {deployed} · "
        f"holdout seeds {seeds} x {len(sizes)} sizes"
    )
    print(f"  commit ที่ freeze {fz['git_commit'][:12]}")

    per_config_rows: dict[str, list] = {k: [] for k in CFG.ORDER}
    per_config_cells: dict[str, list] = {k: [] for k in CFG.ORDER}
    # per-event record ต่อ config — ใช้ทำ paired delta ระหว่าง config (เรียงตรงกันทุกตัว)
    per_config_events: dict[str, list] = {k: [] for k in CFG.ORDER}
    audit_runs: list[dict] = []
    leak_total = {"overlapping_rows": 0, "holdout_rows": 0}

    for seed in seeds:
        raw_users = G3.build_seed(args.users, seed)
        for size in sizes:
            splits = DS.build(args.users, seed, size, raw=raw_users)
            leak = DS.check_leakage(splits)
            leak_total["overlapping_rows"] += leak["overlapping_rows"]
            leak_total["holdout_rows"] += leak["holdout_rows"]
            point_model, seq_models, ecdf = fit_all(splits, size, raw_users)
            ctxs = compute_layer_outputs(splits, point_model, seq_models, "holdout")

            # shortcut audit ของ holdout — ทำตรงนี้ครั้งเดียว หลัง freeze แล้วเท่านั้น
            atk = [v for u in splits.values() for _, v in u.holdout_attacks]
            nor = [v for u in splits.values() for _, v in u.holdout_normal]
            rows_f = AU.feature_report(atk, nor, LC.FEATURES)
            for r in rows_f:
                r["_seed"], r["_size"], r["_split"] = seed, size, "final_holdout"
            audit_runs.append(
                {
                    "seed": seed,
                    "size": size,
                    "split": "final_holdout",
                    "n_attack": len(atk),
                    "n_normal": len(nor),
                    "features": rows_f,
                }
            )

            for key in CFG.ORDER:
                recs = build_records(
                    ctxs, ecdf, CFG.CONFIGS[key], gamma_map.get(key) or 0.0
                )
                t = thr_map[key]
                use_thr = PROBE_THR if t in ("legacy_internal", None) else t
                rows = TU.resolve_rows(recs, use_thr)
                per_config_rows[key].extend(rows)
                per_config_cells[key].append(TU.cell_stat(seed, size, rows))
                for r in rows:
                    per_config_events[key].append(
                        {
                            "user": r.user,
                            "seed": seed,
                            "campaign": r.campaign,
                            "is_attack": r.is_attack,
                            "surfaced": r.is_surfaced,
                            "challenged": r.decision.removeprefix("would_")
                            in M.CHALLENGED,
                            # L3-only: L3 ทำให้ผลเปลี่ยนจริง (ไม่มี L3 = ปล่อยผ่าน)
                            "l3_only_hit": (
                                r.is_attack
                                and r.is_surfaced
                                and not r.surfaced_without_l3
                            ),
                        }
                    )
            print(f"  seed {seed} size {size:>5} -> {len(ctxs)} เหตุการณ์", flush=True)

    final_audit = AU.summarize_audit(audit_runs)
    final_audit["splits_audited"] = ["final_holdout"]
    final_audit["conclusion"] = (
        "ไม่พบ single-feature shortcut บน final holdout ตามเกณฑ์ที่กำหนด"
        if final_audit["n_flagged_features"] == 0
        else (
            f"พบ {final_audit['n_flagged_features']} ฟีเจอร์ที่เข้าเกณฑ์ "
            "— ผลรอบนี้เป็นโมฆะ ต้องแก้ generator แล้วเริ่ม calibration/tuning ใหม่"
        )
    )

    from hybrid_experiment import final_stats as FS
    from hybrid_experiment import tailcal as TC

    results = {}
    for key in CFG.ORDER:
        rows = per_config_rows[key]
        # CI แบบ unpaired ด้วย cluster bootstrap บนสถิติพอเพียง (เร็วพอสำหรับ 316k)
        desc = FS.cluster_single_ci(per_config_events[key], n_boot=2000, seed=7)
        results[key] = {
            "name": CFG.CONFIGS[key].name,
            "thresholds": thr_map[key],
            "macro": TU.macro(per_config_cells[key]),
            "pooled": vars(M.summarize(rows)),
            "campaign": M.campaign_level(rows),
            # CI แบบ unpaired — เก็บไว้บรรยายความไม่แน่นอนของแต่ละ config เท่านั้น
            # **ห้ามใช้สรุปความต่างระหว่าง config** ให้ใช้ paired_vs_deployed แทน
            "descriptive_unpaired_ci": {
                "recall": desc["recall"],
                "challenge_fpr": desc["challenge_fpr"],
                "method": desc["method"],
                "note": "unpaired — บรรยายเท่านั้น ไม่ใช่การทดสอบความแตกต่าง",
            },
            # ECE เก็บเป็นข้อมูลดิบพร้อม caveat — ไม่ใช่ metric ตัดสิน (percentile evidence
            # ไม่ใช่ probability) · ใช้ tail_calibration ด้านล่างแทน
            "ece_raw_not_a_verdict": {
                "value": M.calibration_error(rows),
                "caveat": (
                    "ECE เป็นเครื่องมือของ probability prediction แต่ final_risk_score "
                    "เป็น percentile evidence ไม่ใช่ probability — ค่านี้ไม่ตัดสินว่า "
                    "config ดีหรือแย่"
                ),
            },
        }

    # ── paired delta เทียบ deployed config (นี่คือการทดสอบความต่างที่ถูกต้อง) ──
    dep_events = per_config_events[deployed]
    for key in CFG.ORDER:
        if key == deployed:
            results[key]["paired_vs_deployed"] = None
            continue
        oth = per_config_events[key]
        # cluster bootstrap (user->seed) บนสถิติพอเพียง — เร็วพอสำหรับ 316k เหตุการณ์
        # (resample ทุกเหตุการณ์ทุก boot ช้าเกินไป · ดู final_stats.paired_cluster_multi_delta)
        t_pb = time.perf_counter()
        deltas = FS.paired_cluster_multi_delta(dep_events, oth, n_boot=2000, seed=1)
        print(
            f"  paired {deployed} vs {key}: "
            f"ΔRecall {deltas['delta_recall']['delta']:+.4f} "
            f"[{deltas['delta_recall']['ci_low']:+.4f},"
            f"{deltas['delta_recall']['ci_high']:+.4f}] "
            f"[{time.perf_counter() - t_pb:.1f}s]",
            flush=True,
        )
        results[key]["paired_vs_deployed"] = {
            "candidate": deployed,
            **deltas,
            "note": (
                "Δ = deployed − this_config · CI/sign_agreement จาก paired "
                "hierarchical bootstrap (user->seed->event ชุดเดียวกันทั้งสองแขน) · "
                "ทุก metric resample ชุดเดียวกันต่อ boot"
            ),
        }
        # campaign-level L3-only แบบ hierarchical (แทน Wilson) สำหรับ config ที่มี L3
        if CFG.CONFIGS[key].views:
            tree = FS.campaign_l3_only_tree(per_config_events[key])
            results[key]["campaign_l3_only_hierarchical_ci"] = (
                BS.hierarchical_proportion(tree, n_boot=1000, seed=5)
            )

    # ── tail calibration ของ deployed config: validation (reference) -> holdout ──
    ref = fz.get("deployed_validation_normal_score_quantiles") or []
    holdout_dep_normal = [r.score for r in per_config_rows[deployed] if not r.is_attack]
    if ref and holdout_dep_normal:
        tail = {
            "reference": "validation-tuning normal scores ของ deployed config",
            "benign_exceedance": TC.benign_exceedance(ref, holdout_dep_normal),
            "pit_uniformity": TC.pit_uniformity(ref, holdout_dep_normal),
            "note": (
                "ตอบคำถาม Round 1: distribution ของคะแนน normal บน holdout ต่างจาก "
                "validation แค่ไหน (เหตุที่ FPR บน holdout สูงกว่าที่จูน)"
            ),
        }
    else:
        tail = {
            "available": False,
            "reason": (
                "ไม่มี reference scores (deployed อาจเป็น legacy) หรือไม่มี holdout normal"
            ),
        }

    print(f"\n{'cfg':4} {'ชื่อ':28} {'recall':>8} {'prec':>7} {'chFPR':>7} {'L3 eff':>7}")
    print("-" * 68)
    for key in CFG.ORDER:
        m = results[key]["macro"]
        print(
            f"{key:4} {CFG.CONFIGS[key].name[:28]:28} {m['recall']:8.4f} "
            f"{m['precision']:7.4f} {m['challenge_fpr']:7.4f} "
            f"{m['within_config_l3_counterfactual_unique']:7.4f}"
        )
    gate = _final_gate(results, fz)
    print(f"\nleakage: {leak_total}")
    print(f"shortcut (final): {final_audit['conclusion']}")
    print(f"\nFINAL GATE — candidate Config {deployed}:")
    for key in CFG.ORDER:
        g = gate["per_config"][key]
        mark = "ผ่าน" if g["passed"] else "ไม่ผ่าน"
        star = "  <-- candidate" if key == deployed else ""
        print(
            f"  {key}  warn {g['warn_fpr']:.4f} ch {g['challenge_fpr']:.4f} "
            f"blk {g['block_fpr']:.4f}  {mark}{star}"
        )
    print(f"  => {gate['verdict']}")
    if isinstance(tail, dict) and tail.get("benign_exceedance"):
        be = tail["benign_exceedance"]
        print(
            f"\ntail calibration (deployed, validation->holdout): "
            f"p99 exceedance {be['p99']['observed_exceedance']:.4f} "
            f"(nominal 0.01) · shift={be['tail_shift_detected']}"
        )

    out = ARTIFACTS / "final_result.json"
    out.write_text(
        json.dumps(
            {
                "split": "final_holdout",
                "opened_once": True,
                "frozen_commit": fz["git_commit"],
                "frozen_at": fz["frozen_at"],
                "frozen_view": fz["frozen_view"],
                "gamma": fz["chosen_gamma"],
                "per_config_gamma": gamma_map,
                "per_config_thresholds": thr_map,
                "deployed_config": deployed,
                "holdout_seeds": seeds,
                "leakage": leak_total,
                "shortcut_audit_final": final_audit,
                "tail_calibration_deployed": tail,
                "final_gate": _final_gate(results, fz),
                "results": results,
                "metric_definitions": METRIC_DEFINITIONS,
                "comparison_note": (
                    "ความต่างระหว่าง config อ่านจาก results[k]['paired_vs_deployed'] "
                    "เท่านั้น · descriptive_unpaired_ci ใช้บรรยาย ไม่ใช่ทดสอบความต่าง · "
                    "ECE ไม่ใช่ metric ตัดสิน (ดู tail_calibration_deployed แทน)"
                ),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"artifact -> {out.relative_to(REPO)}")
    _record_holdout_open(seeds, fz.get("git_commit", ""))
    clean = (
        leak_total["overlapping_rows"] == 0 and final_audit["n_flagged_features"] == 0
    )
    return 0 if clean else 1


# ══════════════════════════ Legacy floor (ตอบว่าเทียบที่ FPR เท่ากันได้ไหม) ══════════════════════════
def cmd_legacy_floor(args):
    """FPR ต่ำสุดที่ระบบเดิม (Config A) ทำได้ — ดัน threshold ภายในของมันจนสุด.

    ทำไมต้องวัด: Config A ตัดสินด้วย threshold ที่ตรึงมากับดีไซน์เดิม จึงเทียบกับ
    B–F ที่จูนมาให้อยู่ในงบไม่ได้ตรงๆ · ถ้าจะบอกว่า "เทียบที่ FPR เท่ากัน" ต้อง
    รู้ก่อนว่าระบบเดิมลง FPR ได้ถึงเท่าไร — ถ้า floor ของมันสูงกว่างบอยู่แล้ว
    แปลว่าเทียบที่ FPR เท่ากัน **ทำไม่ได้ทางโครงสร้าง** ต้องรายงานตามนั้น

    ส่วนที่เหลือหลังดัน threshold จนสุดมาจาก policy floor ที่ฝังอยู่ในชั้นให้คะแนน
    ของดีไซน์เดิม (`rule.min_action` / `behavior.min_action`) ซึ่ง threshold
    ไม่มีอำนาจลด — เป็นเหตุผลเชิงสถาปัตยกรรมที่ต้องแยก Policy Gate ออกมา
    """
    from app.security import risk_aggregator as RA

    seeds = args.seeds or SEEDS
    sizes = args.sizes or SIZES
    cells_meta = [(s, n) for s in seeds for n in sizes]
    missing = [
        (s, n) for s, n in cells_meta if not (CELLS / f"cell_s{s}_n{n}.pkl").exists()
    ]
    if missing:
        print(f"ยังไม่ได้ prepare {len(missing)} cell")
        return 1
    loaded = {k: load_cell(*k) for k in cells_meta}

    original = dict(RA.THRESHOLDS)
    UNREACHABLE = {"warn": 9.0, "challenge": 9.0, "block": 9.0}
    print("LEGACY FLOOR — Config A")
    print(f"  threshold เดิมของระบบเก่า: {original}")

    out = {}
    try:
        for label, thr in (
            ("as_shipped", original),
            ("thresholds_unreachable", UNREACHABLE),
        ):
            RA.THRESHOLDS.clear()
            RA.THRESHOLDS.update(thr)
            stats = [
                TU.stat_direct(
                    build_records(c["ctxs"], c["ecdf"], CFG.CONFIGS["A"], 0.0),
                    s,
                    n,
                    PROBE_THR,
                )
                for (s, n), c in loaded.items()
            ]
            m = TU.macro(stats)
            out[label] = {
                "legacy_thresholds": dict(thr),
                "recall": round(m["recall"], 6),
                "challenge_fpr": round(m["challenge_fpr"], 6),
                "block_fpr": round(m["block_fpr"], 6),
                "warn_fpr": round(m["warn_fpr"], 6),
                "per_size": {
                    str(k): {
                        "recall": round(v["recall"], 6),
                        "challenge_fpr": round(v["challenge_fpr"], 6),
                    }
                    for k, v in m["per_size"].items()
                },
            }
            print(
                f"  {label:24} recall {m['recall']:.4f} · "
                f"chFPR {m['challenge_fpr']:.4f} · blkFPR {m['block_fpr']:.4f}"
            )
    finally:
        RA.THRESHOLDS.clear()
        RA.THRESHOLDS.update(original)

    floor = out["thresholds_unreachable"]["challenge_fpr"]
    attainable = floor <= SW.CHALLENGE_FPR_BUDGET
    verdict = (
        "ระบบเดิมลง FPR ถึงงบได้ -> เทียบที่ FPR เท่ากันทำได้ถ้าย้าย threshold ของมัน"
        if attainable
        else (
            f"ระบบเดิมลง challenge FPR ได้ต่ำสุด {floor:.4%} ซึ่งสูงกว่างบ "
            f"{SW.CHALLENGE_FPR_BUDGET:.2%} -> **เทียบที่ FPR เท่ากันทำไม่ได้ทางโครงสร้าง** "
            "เพราะ policy floor ฝังอยู่ในชั้นให้คะแนนของดีไซน์เดิม"
        )
    )
    print(f"\n  สรุป: {verdict}")

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    f = ARTIFACTS / "legacy_floor.json"
    f.write_text(
        json.dumps(
            {
                "split": "validation-tuning",
                "holdout_touched": False,
                "method": (
                    "ดัน THRESHOLDS ของ risk_aggregator ให้คะแนนไม่มีทางถึง "
                    "แล้ววัดว่า FPR ที่เหลือเท่าไร (คืนค่าเดิมหลังวัดเสร็จ)"
                ),
                "budget_challenge_fpr": SW.CHALLENGE_FPR_BUDGET,
                "minimum_attainable_challenge_fpr": floor,
                "equal_fpr_comparison_possible": attainable,
                "verdict": verdict,
                "measurements": out,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"artifact -> {f.relative_to(REPO)}")
    return 0


# ══════════════════════════ Freeze ══════════════════════════
# ไฟล์ที่ "ถ้าแก้แล้วตัวเลขเปลี่ยน" — hash ไว้ตอน freeze แล้วตรวจซ้ำก่อนเปิด holdout
SCORING_FILES = [
    "hub/backend/app/security/evidence.py",
    "hub/backend/app/security/policy_gate.py",
    "hub/backend/app/security/calibration.py",
    "hub/backend/app/security/rule_engine.py",
    "hub/backend/app/security/behavior_profiling.py",
    "hub/backend/app/security/risk_evidence.py",
    "hub/backend/app/security/risk_fusion.py",
    "hub/backend/app/security/risk_aggregator.py",
    "hub/backend/app/security/iforest_scorer.py",
    "ml-service/scripts/exp_hybrid_gate.py",
    "ml-service/scripts/hybrid_experiment/configs.py",
    "ml-service/scripts/hybrid_experiment/dataset.py",
    "ml-service/scripts/hybrid_experiment/metrics.py",
    "ml-service/scripts/hybrid_experiment/sweep.py",
    "ml-service/scripts/hybrid_experiment/tune.py",
    "ml-service/scripts/hybrid_experiment/audit.py",
    "ml-service/scripts/gen_v3.py",
    "ml-service/scripts/exp_lc_v3.py",
    "ml-service/scripts/lc_l3_sequence.py",
    "ml-service/scripts/lc_l3_ownership.py",
    "ml-service/scripts/lc_run_4layer.py",
]

REPO = ML.parent.parent


def _sha256_lf(path: Path) -> str:
    """hash แบบ normalize CRLF -> LF เพื่อให้ตรวจซ้ำได้ทั้งบน Windows และ Linux."""
    import hashlib

    data = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def scoring_fingerprint() -> dict:
    out = {}
    for rel in SCORING_FILES:
        f = REPO / rel
        out[rel] = _sha256_lf(f) if f.exists() else "MISSING"
    return out


def _git(*args) -> str:
    import subprocess

    try:
        return subprocess.run(
            ["git", *args], cwd=REPO, capture_output=True, text=True, check=True
        ).stdout.strip()
    except Exception as e:  # noqa: BLE001
        return f"unavailable: {e}"


def split_fingerprint(seeds, sizes) -> dict:
    """hash ของ cell ที่ prepare ไว้ — พิสูจน์ว่า final ใช้ข้อมูลชุดเดียวกับที่ tune."""
    out = {}
    for seed in seeds:
        for size in sizes:
            f = CELLS / f"cell_s{seed}_n{size}.pkl"
            out[f"s{seed}_n{size}"] = _sha256_lf(f) if f.exists() else "MISSING"
    return out


METRIC_DEFINITIONS = {
    "surfaced": "decision อยู่ใน {warn, challenge, block}",
    "recall": "สัดส่วน attack ที่ถูก surfaced (macro ข้าม seed x size x user)",
    "precision": "TP / (TP + FP) แบบ pooled ต่อ cell แล้วเฉลี่ยข้าม cell",
    "challenge_fpr": "สัดส่วน login ปกติที่ได้ challenge หรือ block",
    "block_fpr": "สัดส่วน login ปกติที่ได้ block",
    "within_config_l3_counterfactual_unique": (
        "สัดส่วน attack ที่ **เปลี่ยนผลจริง** เพราะ L3 "
        "(ไม่มี L3 = ปล่อยผ่าน · มี L3 = ถูกหยิบขึ้นมา) "
        "ไม่นับกรณีคะแนนขยับแต่ผลเท่าเดิม"
    ),
    "campaign_surfaced": "แคมเปญที่มีอย่างน้อยหนึ่งเหตุการณ์ถูก surfaced",
    "macro_average": "เฉลี่ยรายผู้ใช้ก่อน แล้วเฉลี่ยข้าม cell — ไม่ pool รวม",
}


def _deployed_validation_scores(
    deploy_config, gamma, thresholds, seeds, sizes
) -> list[float]:
    """คะแนน final ของ normal บน validation-tuning ของ deployed config (ควอนไทล์ย่อ).

    ใช้เป็น reference ของ tail calibration ตอน final — เก็บที่ freeze แล้วเทียบกับ
    holdout ตอน final โดยไม่ต้องเปิด validation ซ้ำ · legacy (Config A) ไม่มี
    resolver.final_score จึงคืนลิสต์ว่าง (tail calibration ไม่นิยามกับระบบเก่า)
    """
    if CFG.CONFIGS[deploy_config].fusion == "legacy":
        return []
    scores: list[float] = []
    for seed in seeds:
        for size in sizes:
            path = CELLS / f"cell_s{seed}_n{size}.pkl"
            if not path.exists():
                continue
            cell = load_cell(seed, size)
            recs = build_records(
                cell["ctxs"], cell["ecdf"], CFG.CONFIGS[deploy_config], gamma
            )
            scores.extend(
                r.resolver.final_score
                for r in recs
                if not r.is_attack and r.resolver is not None
            )
    if not scores:
        return []
    scores.sort()
    # ย่อเหลือ <= 512 จุด เพื่อไม่ให้ frozen_config ใหญ่ · เพียงพอต่อ exceedance
    step = max(1, len(scores) // 512)
    return [round(v, 6) for v in scores[::step]]


def cmd_freeze(args):
    """ตรึงค่าที่เลือกจาก validation — หลังจากนี้ห้ามแก้อะไรที่กระทบคะแนน.

    freeze ต้องเก็บทุกอย่างที่จำเป็นต่อการพิสูจน์ว่า final ใช้ระบบเดียวกับที่จูน
    (commit, hash ของโค้ดที่ให้คะแนน, hash ของ split, เกณฑ์ที่ประกาศไว้ก่อนรัน)
    """
    tuning_file = ARTIFACTS / "tuning_result.json"
    audit_file = ARTIFACTS / "shortcut_audit_dev.json"
    for f in (tuning_file, audit_file):
        if not f.exists():
            print(f"ขาด {f.name} — ต้องรัน tune และ audit ให้ครบก่อน freeze")
            return 1
    tuning = json.loads(tuning_file.read_text(encoding="utf-8"))
    audit = json.loads(audit_file.read_text(encoding="utf-8"))

    if tuning["global_gamma"] is None:
        print("tune ไม่ได้เลือก gamma (ไม่มีจุดใดอยู่ในงบ FPR) — ห้าม freeze")
        print("ต้องรายงานว่าเป้า FPR ทำไม่ได้ พร้อม attainable_floor ไม่ใช่ขยับเป้า")
        return 1

    view_key = (
        "per_config_gamma_view" if args.view == "per-config" else "global_gamma_view"
    )
    view = tuning[view_key]
    per_config_thresholds = {}
    per_config_gamma = {}
    for key, v in view.items():
        b = v.get("best")
        per_config_gamma[key] = v.get("gamma")
        if v.get("fixed_operating_point"):
            per_config_thresholds[key] = "legacy_internal"
        elif b:
            per_config_thresholds[key] = b["thresholds"]
        else:
            per_config_thresholds[key] = None

    if per_config_thresholds.get(CANDIDATE_CONFIG) is None:
        print(f"Config {CANDIDATE_CONFIG} ไม่มี threshold ที่อยู่ในงบ — ห้าม freeze")
        return 1

    # override block threshold ของ deployed config (ประกาศล่วงหน้าใน protocol)
    # การยก block เป็นคันโยกฟรี: block->challenge ไม่กระทบ recall/challenge FPR
    # (พิสูจน์บน validation ใน round2_prefreeze_2026-09-03.md) · บันทึกทั้งค่าเดิม
    # และค่าใหม่ใน frozen record เพื่อ audit ได้
    block_override = None
    dep_thr = per_config_thresholds.get(args.deploy_config)
    if args.deployed_block is not None and isinstance(dep_thr, dict):
        block_override = {
            "config": args.deploy_config,
            "block_from": dep_thr["block"],
            "block_to": args.deployed_block,
            "rationale": (
                "ยก block บน validation (คันโยกฟรี ไม่กระทบ recall/challenge FPR) "
                "ประกาศล่วงหน้าใน RBA_ROUND2_PROTOCOL.md"
            ),
        }
        dep_thr = {**dep_thr, "block": args.deployed_block}
        per_config_thresholds[args.deploy_config] = dep_thr
        print(
            f"  override block ของ Config {args.deploy_config}: "
            f"{block_override['block_from']} -> {args.deployed_block}"
        )

    # override warn threshold (Round 2b) — ต่างจาก block: warn **ไม่ใช่คันโยกฟรี**
    # ยก warn ลด warn FPR แต่ลด recall แบบ warn+ (soft) ด้วย · recall@challenge ไม่กระทบ
    # เลือกจากเกณฑ์ worst-seed บน validation (population variance คือตัวขับ shift ไม่ใช่
    # in-sample optimism ซึ่งวัดได้ ~0) · ประกาศล่วงหน้าใน RBA_ROUND2_PROTOCOL.md
    warn_override = None
    if args.deployed_warn is not None and isinstance(dep_thr, dict):
        warn_override = {
            "config": args.deploy_config,
            "warn_from": dep_thr["warn"],
            "warn_to": args.deployed_warn,
            "rationale": (
                "ยก warn ตามเกณฑ์ worst-seed บน validation (ทน population variance) "
                "แลก soft-warn recall · enforcement (recall@challenge) ไม่กระทบ"
            ),
        }
        dep_thr = {**dep_thr, "warn": args.deployed_warn}
        per_config_thresholds[args.deploy_config] = dep_thr
        print(
            f"  override warn ของ Config {args.deploy_config}: "
            f"{warn_override['warn_from']} -> {args.deployed_warn}"
        )

    # reference scores ของ deployed config บน validation-tuning — ใช้ตอน final
    # ทำ tail calibration (validation -> holdout) โดยไม่ต้องเปิด validation ซ้ำ
    # (เก็บควอนไทล์ย่อไว้ ไม่เก็บทุกจุด เพื่อไม่ให้ไฟล์ใหญ่ · เป็นคะแนนของ normal ล้วน)
    ref_scores = _deployed_validation_scores(
        args.deploy_config,
        per_config_gamma.get(args.deploy_config) or 0.0,
        per_config_thresholds.get(args.deploy_config),
        tuning["seeds"],
        tuning["sizes"],
    )

    holdout_seeds = args.holdout_seeds or HOLDOUT_SEEDS
    if set(holdout_seeds) & set(tuning["seeds"]):
        print(
            f"holdout_seeds {holdout_seeds} ทับกับ seeds ที่ใช้ tune {tuning['seeds']} "
            "— ห้าม freeze (holdout ต้องเป็น seed ที่ไม่เคยเห็น)"
        )
        return 1

    parity = args.parity_passed
    frozen = {
        "frozen_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "git_commit": _git("rev-parse", "HEAD"),
        "git_branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "git_dirty": bool(_git("status", "--porcelain")),
        "dataset_generator": {
            "module": "gen_v3",
            "train_pool": G3.TRAIN_POOL,
            "val_n": G3.VAL_N,
            "test_n": G3.TEST_N,
            "episode_events": G3.EPISODE_EVENTS,
            "episode_days": G3.EPISODE_DAYS,
            "dev_final_split": [G3.DEV, G3.FINAL],
        },
        "seeds": tuning["seeds"],
        "sizes": tuning["sizes"],
        "holdout_seeds_reserve": HOLDOUT_SEEDS,
        # seed ของ final holdout — ต้องไม่เคยถูกใช้ tune (Round 2 ใช้ [101-105])
        "holdout_seeds": holdout_seeds,
        # คะแนน normal บน validation-tuning ของ deployed config (ควอนไทล์ย่อ)
        # ใช้เป็น reference ของ tail calibration ตอน final — ไม่ต้องเปิด validation ซ้ำ
        "deployed_validation_normal_score_quantiles": ref_scores,
        "feature_order": list(LC.FEATURES),
        "n_features": len(LC.FEATURES),
        "split_hashes": split_fingerprint(tuning["seeds"], tuning["sizes"]),
        "scoring_fingerprint": scoring_fingerprint(),
        "metric_definitions": METRIC_DEFINITIONS,
        "shortcut_criteria": audit["summary"]["criteria"],
        "shortcut_conclusion_dev": audit["summary"]["conclusion"],
        "gamma_grid": tuning["gamma_grid"],
        "gamma_grid_passes": tuning["gamma_grid_passes"],
        "frozen_view": view_key,
        "chosen_gamma": tuning["global_gamma"],
        "per_config_gamma": per_config_gamma,
        "gamma_selected_on_config": tuning["candidate_config"],
        "per_config_thresholds": per_config_thresholds,
        "fpr_budgets": {
            "challenge": SW.CHALLENGE_FPR_BUDGET,
            "block": SW.BLOCK_FPR_BUDGET,
            "warn": SW.WARN_FPR_BUDGET,
        },
        "selection_rule": (
            "macro recall -> precision -> gamma ต่ำสุด · "
            "FPR ต้องอยู่ในงบทั้งค่ารวมและทุกขนาดข้อมูล"
        ),
        "parity_passed": parity,
        "holdout_touched_before_freeze": False,
        # config ที่จะใช้ตัดสินการเข้าถึงจริง — เลือกจากหลักฐานบน validation
        # config อื่นยังถูกวัดบน holdout ด้วย เพื่อรายงานเปรียบเทียบ
        "deployed_config": args.deploy_config,
        "declared_candidate": args.deploy_config,
        "declared_fallback": args.fallback,
        "deployed_block_override": block_override,
        "deployed_warn_override": warn_override,
        "deployed_config_gamma": per_config_gamma.get(args.deploy_config),
        "deployed_config_thresholds": per_config_thresholds.get(args.deploy_config),
        "l3_mode_implied": (
            "shadow" if not CFG.CONFIGS[args.deploy_config].views else "enforcing"
        ),
    }
    FROZEN.parent.mkdir(parents=True, exist_ok=True)
    FROZEN.write_text(
        json.dumps(frozen, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("FREEZE เรียบร้อย")
    print(f"  commit        {frozen['git_commit'][:12]} (dirty={frozen['git_dirty']})")
    print(f"  view          {view_key}")
    print(f"  gamma         {frozen['chosen_gamma']} (ต่อ config: {per_config_gamma})")
    for k, v in per_config_thresholds.items():
        print(f"  threshold {k}   {v}")
    print(
        f"  deploy        Config {args.deploy_config} "
        f"-> L3 mode = {frozen['l3_mode_implied']}"
    )
    print(f"  parity_passed {parity}")
    print(f"artifact -> {FROZEN.relative_to(REPO)}")
    if not parity:
        print("\nยังไม่ได้ยืนยัน parity — รัน `parity` แล้ว freeze ด้วย --parity-passed")
    return 0


def check_frozen_intact() -> tuple[bool, list[str]]:
    """ตรวจว่าเปิด holdout ได้หรือยัง — ต้องผ่านทุกข้อ ไม่มีข้อยกเว้น."""
    problems: list[str] = []
    if not FROZEN.exists():
        return False, ["ยังไม่ได้ freeze — ห้ามเปิด final holdout"]
    fz = json.loads(FROZEN.read_text(encoding="utf-8"))
    if not fz.get("parity_passed"):
        problems.append("parity ยังไม่ผ่าน")
    now = scoring_fingerprint()
    for rel, want in fz["scoring_fingerprint"].items():
        if now.get(rel) != want:
            problems.append(f"โค้ดที่ให้คะแนนเปลี่ยนหลัง freeze: {rel}")
    for key, want in fz["split_hashes"].items():
        seed, size = key[1:].split("_n")
        f = CELLS / f"cell_s{seed}_n{size}.pkl"
        got = _sha256_lf(f) if f.exists() else "MISSING"
        if got != want:
            problems.append(f"split เปลี่ยนหลัง freeze: {key}")
    return (not problems), problems


# ══════════════════════════ Shortcut audit (ชุดพัฒนาเท่านั้น) ══════════════════════════
def cmd_audit(args):
    """ตรวจ single-feature shortcut ครบทุก feature x seed x size — **ห้ามแตะ holdout**.

    เหตุผลที่ต้องแยกคำสั่งนี้ออกมาและทำ **ก่อน** freeze:
      * ตัวตรวจเดิม (exp_final_gate.py) ใช้ AUC ที่ไม่จัดการค่าเสมอ -> ผลรอบก่อน
        เชื่อถือไม่ได้ ต้องประกาศว่า superseded ไม่ใช่ยืนยันซ้ำ
      * ถ้ารันบน final holdout ก่อน freeze = เปิดดูข้อมูลแล้ว แม้จะไม่พิมพ์ recall
        ออกมา ก็อาจมีผลต่อการตัดสินใจแก้ generator/โมเดลโดยไม่รู้ตัว

    ฝั่ง attack ที่ใช้คือ `dev_attacks` เท่านั้น (`final_attacks` ยังไม่ถูกอ่าน)
    """
    from hybrid_experiment import audit as AU

    seeds = args.seeds or SEEDS
    sizes = args.sizes or SIZES
    print(
        f"SHORTCUT AUDIT — ชุดพัฒนาเท่านั้น · {len(seeds)} seeds x {len(sizes)} sizes "
        f"x {len(AU.SPLITS_ALLOWED_BEFORE_FREEZE)} splits"
    )
    print(f"  เกณฑ์: AUC > {AU.AUC_THRESHOLD} หรือ coverage < {AU.COVERAGE_THRESHOLD}")
    print("  ไม่อ่าน holdout_normal / holdout_attacks ในคำสั่งนี้เลย\n")

    per_run: list[dict] = []
    for seed in seeds:
        raw_users = G3.build_seed(args.users, seed)
        for size in sizes:
            splits = DS.build(args.users, seed, size, raw=raw_users)
            # ฝั่ง attack — dev เท่านั้น
            atk = [v for u in splits.values() for _, v in u.tune_attacks]
            normals = {
                "train": [v for u in splits.values() for v in u.train_ft],
                "calibration": [v for u in splits.values() for v in u.cal_normal_ft],
                "tuning": [v for u in splits.values() for v in u.tune_normal_ft],
            }
            for split_name in AU.SPLITS_ALLOWED_BEFORE_FREEZE:
                rows = AU.feature_report(atk, normals[split_name], LC.FEATURES)
                for r in rows:
                    r["_seed"], r["_size"], r["_split"] = seed, size, split_name
                per_run.append(
                    {
                        "seed": seed,
                        "size": size,
                        "split": split_name,
                        "n_attack": len(atk),
                        "n_normal": len(normals[split_name]),
                        "features": rows,
                    }
                )
            flags = sum(
                1
                for r in per_run[-len(AU.SPLITS_ALLOWED_BEFORE_FREEZE) :]
                for x in r["features"]
                if x["flagged"]
            )
            print(f"  seed {seed} · size {size:>5} -> flagged {flags}")

    summary = AU.summarize_audit(per_run)
    print(f"\n{'feature':32} {'auc_max':>8} {'auc_mean':>9} {'cov_min':>8} {'flag':>5}")
    print("-" * 68)
    for a in summary["top_by_auc"]:
        print(
            f"{a['feature'][:32]:32} {a['auc_max']:8.4f} {a['auc_mean']:9.4f} "
            f"{a['coverage_min']:8.4f} {a['n_flagged']:5d}"
        )
    print(f"\nสรุป: {summary['conclusion']}")
    print(f"ขอบเขต: {summary['scope_note']}")

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    out = ARTIFACTS / "shortcut_audit_dev.json"
    out.write_text(
        json.dumps(
            {
                "scope": "development_splits_only",
                "holdout_touched": False,
                "seeds": seeds,
                "sizes": sizes,
                "n_features": len(LC.FEATURES),
                "feature_order": list(LC.FEATURES),
                "attack_source": "dev_attacks",
                "supersedes": {
                    "artifact": "exp_final_gate.py shortcut check",
                    "status": "superseded",
                    "reason": "tie-unsafe AUC implementation",
                },
                "summary": summary,
                "runs": per_run,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"artifact -> {out.relative_to(ML.parent.parent)}")
    return 0 if summary["n_flagged_features"] == 0 else 1


# ══════════════════════════ Parity gate ══════════════════════════
def cmd_parity(args):
    """ตรวจว่า harness กับ production คำนวณตรงกันจริง — ต้องผ่านก่อนรันเต็ม.

    ถ้าไม่ผ่าน ผลการทดลองจะอธิบายไม่ได้ว่าเกิดจากระบบหรือจากความต่างของ harness
    (บทเรียน B66)
    """
    import json
    import tempfile

    from app.security import calibration as PCAL
    from app.security.policy_gate import PolicyOutcome
    from app.security.risk_evidence import behavior_evidence as P_beh
    from app.security.risk_evidence import rule_evidence as P_rule
    from app.security.risk_fusion import fuse as P_fuse

    ok = True
    print(f"PARITY GATE — seed {args.seed} · size {args.size}")

    raw_users = G3.build_seed(args.users, args.seed)
    splits = DS.build(args.users, args.seed, args.size)
    point_model, seq_models, ecdf = fit_all(splits, args.size, raw_users)

    # ── 1. sequence parity: production _windows vs harness _winfeat ──
    print("  [1] sequence parity")
    ok &= _parity_sequence(splits, seq_models)

    # ── 2. ECDF parity: harness ECDF vs ตาราง calibration ของ production ──
    print("  [2] ECDF / calibration parity")
    with tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump({"version": "parity", "quantiles": ecdf.to_artifact()}, f)
        cal_path = Path(f.name)
    PCAL.CALIBRATION_FILE = cal_path
    PCAL.reload_for_tests()
    diffs = []
    for layer in ("rule", "behavior", "anomaly_point", "anomaly_sequence"):
        for raw in (0.0, 0.05, 0.2, 0.5, 0.8, 1.0):
            a = ecdf(layer, raw)
            b = PCAL.calibrate(layer, raw).value
            if abs(a - b) > 0.02:  # to_artifact ย่อควอนไทล์ จึงยอมคลาดได้เล็กน้อย
                diffs.append((layer, raw, round(a, 4), round(b, 4)))
    if diffs:
        ok = False
        print(f"      ไม่ตรง {len(diffs)} จุด: {diffs[:4]}")
    else:
        print("      ตรงกันทุกจุดที่สุ่มตรวจ")

    # ── 3. fusion parity: harness apply_config vs production fuse ──
    print("  [3] fusion parity")
    ctxs = compute_layer_outputs(splits, point_model, seq_models, "tune")[:400]
    thr = {"warn": 0.5, "challenge": 0.7, "block": 0.85}
    rows = apply_config(ctxs, CFG.CONFIGS["B"], ecdf, 0.35, thr)
    bad = 0
    for c, r in zip(ctxs, rows):
        evs = [P_rule(c.rule), P_beh(c.behavior)]
        for e in evs:
            e.evidence_score = ecdf(e.layer, e.raw_score or 0.0)
        d = P_fuse(c.policy, evs, gamma=0.35, thresholds=thr)
        if d.decision != r.decision or abs(d.total_score - r.score) > 1e-9:
            bad += 1
    if bad:
        ok = False
        print(f"      ไม่ตรง {bad}/{len(rows)} แถว")
    else:
        print(f"      ตรงกันทุกหลัก {len(rows)} แถว")

    # ── 4. counterfactual parity: Policy Gate ต้องเป็น object เดียวกันสองรอบ ──
    print("  [4] counterfactual parity")
    forced = PolicyOutcome(min_action="challenge", reasons=["parity"], policy="test")
    a = CFG.evaluate(
        CFG.CONFIGS["E"],
        forced,
        ctxs[0].rule,
        ctxs[0].behavior,
        ctxs[0].l3,
        calibrate_fn=ecdf,
        gamma=0.35,
        thresholds=thr,
    )
    b = CFG.evaluate(
        CFG.CONFIGS["B"],
        forced,
        ctxs[0].rule,
        ctxs[0].behavior,
        CFG.L3Scores(),
        calibrate_fn=ecdf,
        gamma=0.35,
        thresholds=thr,
    )
    same_policy = a.breakdown["policy"] == b.breakdown["policy"] == forced.to_contract()
    floors_ok = a.decision != "allow" and b.decision != "allow"
    if not (same_policy and floors_ok):
        ok = False
        print("      policy ไม่ตรงกันสองรอบ หรือ min_action ไม่ถูกบังคับ")
    else:
        print("      Policy Gate เดียวกันทั้งสองรอบ และ min_action ถูกบังคับครบ")

    # ── 5. batch parity: เรียก sklearn เป็นชุด ต้องได้ค่าเท่ากับเรียกทีละแถว ──
    print("  [5] batch scoring parity")
    sample = [v for u in splits.values() for v in u.tune_normal_ft][:500]
    one = [point_score(point_model, v) for v in sample]
    many = point_scores(point_model, sample)
    if one and any(
        (a is None) != (b is None) or (a is not None and abs(a - b) > 1e-12)
        for a, b in zip(one, many)
    ):
        ok = False
        print("      point score เรียกเป็นชุดไม่เท่ากับทีละแถว")
    else:
        print(f"      point score เท่ากันทุกหลัก ({len(sample)} แถว)")

    # ── 6. resolver parity: fuse ต้องได้ผลเดียวกับ resolve_action บน resolver ของมันเอง ──
    print("  [6] resolver parity (จุดแปลงคะแนน->action มีจุดเดียว)")
    from app.security.risk_fusion import ResolverInput, resolve_action

    bad_r = 0
    for c, r in zip(ctxs, rows):
        evs = [P_rule(c.rule), P_beh(c.behavior)]
        for e in evs:
            e.evidence_score = ecdf(e.layer, e.raw_score or 0.0)
        d = P_fuse(c.policy, evs, gamma=0.35, thresholds=thr)
        ri = ResolverInput.from_dict(d.breakdown["resolver"])
        for probe in ({"warn": 0.2, "challenge": 0.4, "block": 0.6}, thr):
            d2 = P_fuse(c.policy, evs, gamma=0.35, thresholds=probe)
            if resolve_action(ri, probe)[0] != d2.decision:
                bad_r += 1
                break
    if bad_r:
        ok = False
        print(f"      ไม่ตรง {bad_r}/{len(rows)} แถว")
    else:
        print(f"      ตรงกันทุกแถวที่ทุก threshold ที่ลอง ({len(rows)} แถว)")

    cal_path.unlink(missing_ok=True)
    PCAL.CALIBRATION_FILE = Path(PCAL.__file__).with_name("calibration_v1.json")
    PCAL.reload_for_tests()
    print(f"\nPARITY GATE: {'ผ่าน' if ok else 'ไม่ผ่าน — ห้ามรันเต็ม'}")
    return 0 if ok else 1


def _parity_sequence(splits, seq_models) -> bool:
    """residual ชุดเดียวกัน -> 18 มิติของ production ต้องเท่ากับของ harness ทุกตำแหน่ง."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "prod_sequence", ML.parent / "app" / "sequence.py"
    )
    prod = importlib.util.module_from_spec(spec)
    # ต้องลงทะเบียนก่อน exec — @dataclass อ่าน sys.modules[cls.__module__]
    sys.modules["prod_sequence"] = prod
    spec.loader.exec_module(prod)

    alias = sorted(splits)[0]
    model, base, prof, train_res = seq_models[alias]
    if model is None or len(train_res) < prod.WINDOW:
        print("      ข้าม — ไม่มีโมเดล sequence")
        return True
    win = train_res[-prod.WINDOW :]
    prod_feat = prod._windows(np.asarray(win, dtype=float))[0]
    harness_feat = SEQL._winfeat(win)
    same = np.allclose(prod_feat, harness_feat, atol=1e-12)
    if same:
        print(
            f"      18 มิติตรงกันทุกตำแหน่ง (max diff "
            f"{float(np.max(np.abs(prod_feat - harness_feat))):.2e})"
        )
    else:
        print(
            f"      ไม่ตรง: prod={np.round(prod_feat, 4)[:4]} "
            f"harness={np.round(harness_feat, 4)[:4]}"
        )
    return bool(same)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sm = sub.add_parser("smoke", help="ตรวจเส้นทาง 1 seed x 1 size")
    sm.add_argument("--seed", type=int, default=42)
    sm.add_argument("--size", type=int, default=500)
    sm.add_argument("--users", type=Path, default=DEFAULT_USERS)
    sm.set_defaults(func=cmd_smoke)
    pr = sub.add_parser("prepare", help="ขั้นที่ 1 ของ tune — cache ผลของชั้นทุก cell")
    pr.add_argument("--seeds", type=int, nargs="*", default=None)
    pr.add_argument("--sizes", type=int, nargs="*", default=None)
    pr.add_argument("--users", type=Path, default=DEFAULT_USERS)
    pr.set_defaults(func=cmd_prepare)
    tn = sub.add_parser("tune", help="ขั้นที่ 2 — กวาด gamma/threshold บน validation")
    tn.add_argument("--seeds", type=int, nargs="*", default=None)
    tn.add_argument("--sizes", type=int, nargs="*", default=None)
    tn.add_argument("--users", type=Path, default=DEFAULT_USERS)
    tn.set_defaults(func=cmd_tune)
    fz = sub.add_parser("freeze", help="ตรึงค่าที่เลือกก่อนเปิด final holdout")
    fz.add_argument(
        "--parity-passed",
        action="store_true",
        help="ยืนยันว่ารัน parity ผ่านแล้ว (ต้องใส่ ไม่งั้น final จะไม่ยอมรัน)",
    )
    fz.add_argument(
        "--holdout-seeds",
        type=int,
        nargs="*",
        default=None,
        help="seed ของ final holdout (ค่าเริ่มต้น HOLDOUT_SEEDS=[101-105]) ต้องไม่ทับ tune",
    )
    fz.add_argument(
        "--deploy-config",
        choices=list(CFG.ORDER),
        default="B",
        help="config ที่จะใช้ตัดสินการเข้าถึงจริง (config อื่นยังถูกวัดบน holdout)",
    )
    fz.add_argument(
        "--fallback",
        default="shadow / current deployment",
        help="แผนสำรองถ้า candidate ไม่ผ่าน gate (ประกาศล่วงหน้า · ห้ามเลือก post-hoc)",
    )
    fz.add_argument(
        "--deployed-block",
        type=float,
        default=None,
        help="override block threshold ของ deployed config (คันโยกฟรีที่พิสูจน์บน validation)",
    )
    fz.add_argument(
        "--deployed-warn",
        type=float,
        default=None,
        help="override warn threshold ของ deployed config (เกณฑ์ worst-seed · แลก soft-warn recall)",
    )
    fz.add_argument(
        "--view",
        choices=("global-gamma", "per-config"),
        default="global-gamma",
        help="มุมที่จะตรึง: gamma กลางตัวเดียว (ค่าที่ deploy) หรือ gamma ที่ดีที่สุดต่อ config",
    )
    fz.set_defaults(func=cmd_freeze)
    fi = sub.add_parser("final", help="เปิด final holdout ครั้งเดียวหลัง freeze")
    fi.add_argument("--users", type=Path, default=DEFAULT_USERS)
    fi.add_argument(
        "--i-know-this-is-a-rerun",
        action="store_true",
        help="รันซ้ำทั้งที่มีผลแล้ว — ต้องบันทึกเหตุผลในรายงาน",
    )
    fi.add_argument(
        "--reopen-spent-holdout",
        action="store_true",
        help="เปิด holdout seed ที่อยู่ใน ledger แล้ว (B68) — ทำลาย single-open ต้องบันทึกเหตุผล",
    )
    fi.set_defaults(func=cmd_final)
    lf = sub.add_parser(
        "legacy-floor", help="FPR ต่ำสุดที่ระบบเดิมทำได้ (ตอบเรื่องการเทียบที่ FPR เท่ากัน)"
    )
    lf.add_argument("--seeds", type=int, nargs="*", default=None)
    lf.add_argument("--sizes", type=int, nargs="*", default=None)
    lf.set_defaults(func=cmd_legacy_floor)
    au = sub.add_parser("audit", help="ตรวจ shortcut บนชุดพัฒนา (ห้ามแตะ holdout)")
    au.add_argument("--seeds", type=int, nargs="*", default=None)
    au.add_argument("--sizes", type=int, nargs="*", default=None)
    au.add_argument("--users", type=Path, default=DEFAULT_USERS)
    au.set_defaults(func=cmd_audit)
    pa = sub.add_parser("parity", help="ตรวจ harness == production ก่อนรันเต็ม")
    pa.add_argument("--seed", type=int, default=42)
    pa.add_argument("--size", type=int, default=500)
    pa.add_argument("--users", type=Path, default=DEFAULT_USERS)
    pa.set_defaults(func=cmd_parity)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
