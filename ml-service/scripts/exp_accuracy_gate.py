"""Accuracy Gate ของ Hybrid RBA — calibrate แล้ว validate (pre-registration 2026-09-23).

เกณฑ์และตรรกะตัดสินทั้งหมดอยู่ใน `hybrid_experiment/accuracy_gate.py` (commit ก่อนวัด) ·
รายงาน `hub/backend/tests/reports/accuracy_gate_2026-09-23.md`

    cd hub/backend
    PYTHONPATH=. python ../../ml-service/scripts/exp_accuracy_gate.py calibrate
    #   -> data/hybrid_experiment/accuracy_gate/calibration.json  (ต้อง commit สำเนาก่อน validate)
    PYTHONPATH=. python ../../ml-service/scripts/exp_accuracy_gate.py validate
    #   -> data/hybrid_experiment/accuracy_gate/validation.json   (เปิดได้ครั้งเดียว — ledger)

ทุก candidate เรียกโค้ด production ผ่าน `hybrid_experiment.configs.evaluate` (B66) · holdout ของ P48-T2
(16 โปรไฟล์) ไม่ถูกสร้างเลย (assert) · seed 101–115 ไม่ถูกใช้
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import random
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ML = Path(__file__).resolve().parent
if str(ML) not in sys.path:
    sys.path.insert(0, str(ML))
REPO = ML.parent.parent
if str(REPO / "hub" / "backend") not in sys.path:
    sys.path.insert(0, str(REPO / "hub" / "backend"))

import build_profiles_v2 as BP  # noqa: E402
import exp_hybrid_gate as X  # noqa: E402
import gen_v3 as G3  # noqa: E402
import population_p48_t2 as P48T2  # noqa: E402
from app.security.calibration import tail_transform  # noqa: E402
from app.security.risk_fusion import (  # noqa: E402
    ConditionalParams,
    ResolverInput,
    resolve_action,
)
from hybrid_experiment import accuracy_gate as AG  # noqa: E402
from hybrid_experiment import bootstrap as BS  # noqa: E402
from hybrid_experiment import configs as CFG  # noqa: E402
from hybrid_experiment import dataset as DS  # noqa: E402

OUT = X.ARTIFACTS / "accuracy_gate"
CALIBRATION = OUT / "calibration.json"
VALIDATION = OUT / "validation.json"
LEDGER = OUT / "validation_ledger.json"
ABLATION = OUT / "ablation.json"
ABLATION_CAL = OUT / "ablation_calibration.json"
RECAL = OUT / "recalibration.json"
RECAL_CAL = OUT / "recalibration_calibration.json"
# สำเนาที่ commit ก่อน validate — validate อ่านจากที่นี่เท่านั้น (พิสูจน์ได้ว่าตรึงก่อนเปิด)
COMMITTED_CALIBRATION = (
    REPO / "hub" / "backend" / "tests" / "provenance" / "accuracy_calibration.json"
)
# เหตุการณ์ปกติที่คะแนน >= ค่านี้เก็บ ResolverInput เต็มไว้ประเมิน block แบบตรงตัว
TAIL = 0.99
N_BOOT = 2000


def _git(*args) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=REPO, capture_output=True, text=True, check=True
        ).stdout.strip()
    except Exception as e:  # noqa: BLE001
        return f"unavailable: {e}"


def _frozen() -> dict:
    return json.loads((X.ARTIFACTS / "frozen_config.json").read_text(encoding="utf-8"))


def _variants(fz: dict, g_params: list[ConditionalParams]) -> dict:
    """key -> (config, gamma, frozen_warn)."""
    gam = fz["per_config_gamma"]
    thr = fz["per_config_thresholds"]
    out = {}
    for key in ("B", "E"):
        out[key] = (
            CFG.CONFIGS[key],
            gam[AG.CANDIDATE_GAMMA_FROM[key]],
            thr[key]["warn"],
        )
    for i, p in enumerate(g_params):
        out[f"G{i:02d}"] = (
            CFG.with_params(CFG.CONFIGS["G"], p),
            gam[AG.CANDIDATE_GAMMA_FROM["G"]],
            thr["E"]["warn"],
        )
    return out


def _population():
    roster = json.loads((BP.DATA / "roster_p48_t2.json").read_text(encoding="utf-8"))
    pop = P48T2.generate_population()
    val, hold = P48T2.split_population(pop)
    return val, {p["alias"] for p in hold}, roster


# ── การเก็บผลต่อ variant ─────────────────────────────────────────────────────


class Store:
    """ผลต่อ variant แบบกระชับ — พอสำหรับ FPR ทุก threshold และ recall แบบตรงตัว."""

    def __init__(self, record_l3: bool = False):
        # normal_seed[size][user][seed] -> {"n", "always", "scores": คะแนนที่ threshold ตัดได้ (เรียงแล้ว)}
        self.normal_seed = defaultdict(
            lambda: defaultdict(
                lambda: defaultdict(lambda: {"n": 0, "always": 0, "scores": []})
            )
        )
        self.tail = []  # (size, user, seed, ResolverInput) ของปกติที่คะแนน >= TAIL หรือ denied
        self.attacks = []  # (size, user, seed, family, ResolverInput)
        self.record_l3 = record_l3
        self.l3 = []  # (size, is_attack, abstained, evidence_score, zone) — validate เท่านั้น
        self.views = []  # (user, is_attack, {view: calibrated}) — ablation เท่านั้น

    def add(
        self,
        size,
        user,
        seed,
        is_attack,
        family,
        inp: ResolverInput,
        l3info,
        views=None,
    ):
        if self.record_l3:
            self.l3.append((size, is_attack, *l3info))
        if views:
            self.views.append((user, is_attack, views))
        if is_attack:
            self.attacks.append((size, user, seed, family, inp))
            return
        always = inp.policy_denied or inp.policy_min_action in ("challenge", "block")
        cell = self.normal_seed[size][user][seed]
        cell["n"] += 1
        if always:
            cell["always"] += 1
        elif inp.action_cap not in ("allow", "warn"):
            cell["scores"].append(inp.final_score)
        if inp.policy_denied or inp.final_score >= TAIL:
            self.tail.append((size, user, seed, inp))

    def finalize(self):
        for size, users in self.normal_seed.items():
            for user, seeds in users.items():
                for c in seeds.values():
                    c["scores"].sort()


# ตรรกะการตัดสินอยู่ใน accuracy_gate (stdlib ล้วน) — เทสได้โดยไม่ต้องมี numpy
caught_fast = AG.caught_fast
_thr = AG.thresholds_at


def challenge_fpr_by_size(store: Store, t: float) -> dict:
    out = {}
    for size, users in store.normal_seed.items():
        k = n = 0
        for seeds in users.values():
            for c in seeds.values():
                n += c["n"]
                k += c["always"] + (
                    len(c["scores"]) - bisect.bisect_left(c["scores"], t)
                )
        out[size] = k / n if n else 0.0
    return out


def block_fpr_by_size(store: Store, warn: float, t_c: float, t_b: float) -> dict:
    thr = _thr(warn, t_c, t_b)
    n = defaultdict(int)
    for size, users in store.normal_seed.items():
        for seeds in users.values():
            for c in seeds.values():
                n[size] += c["n"]
    k = defaultdict(int)
    for size, _u, _s, inp in store.tail:
        if resolve_action(inp, thr)[0] == "block":
            k[size] += 1
    return {s: k[s] / n[s] for s in n}


def parity_check(store: Store, warn: float, t: float, rng: random.Random) -> int:
    """สูตรลัดต้องเท่ากับ resolve_action ตรงตัว — ถ้าไม่เท่าหยุดทันที (B66)."""
    sample = rng.sample(store.tail, min(500, len(store.tail))) if store.tail else []
    sample += [
        (0, "", 0, a[4])
        for a in rng.sample(store.attacks, min(500, len(store.attacks)))
    ]
    thr = _thr(warn, t, 1.0)
    for *_x, inp in sample:
        exact = resolve_action(inp, thr)[0] in ("challenge", "block")
        if exact != caught_fast(inp, t):
            raise AssertionError(f"caught_fast ไม่ตรง resolve_action ที่ t={t}: {inp}")
    return len(sample)


def choose_thresholds(store: Store, warn: float) -> dict:
    ch = AG.pick_threshold(
        lambda t: challenge_fpr_by_size(store, t),
        AG.MATCHED_FPR["challenge"],
        AG.THRESHOLD_GRID,
    )
    t_c = ch["threshold"]
    if t_c < TAIL:
        raise AssertionError(
            f"threshold challenge {t_c} ต่ำกว่า TAIL {TAIL} — block ประเมินไม่ครบ"
        )
    blk = AG.pick_threshold(
        lambda tb: block_fpr_by_size(store, warn, t_c, tb),
        AG.MATCHED_FPR["block"],
        [g for g in AG.THRESHOLD_GRID if g >= t_c],
    )
    return {
        "thresholds": _thr(warn, t_c, blk["threshold"]),
        "challenge": ch,
        "block": blk,
        "reachable": ch["reachable"] and blk["reachable"],
    }


def outcomes(store: Store, thr: dict) -> list[AG.LabeledOutcome]:
    rows = []
    for size, user, seed, fam, inp in store.attacks:
        d = resolve_action(inp, thr)[0]
        rows.append(
            AG.LabeledOutcome(
                user=user,
                seed=seed,
                family=fam,
                decision=d,
                campaign=AG.campaign_key(user, fam or "?", seed, size),
            )
        )
    return rows


def family_recall(rows) -> dict:
    by = defaultdict(list)
    for r in rows:
        by[r.family].append(AG.caught(r.decision))
    return {f: sum(v) / len(v) for f, v in sorted(by.items()) if v}


def pooled_recall(rows, families) -> float:
    v = [AG.caught(r.decision) for r in rows if r.family in families]
    return sum(v) / len(v) if v else 0.0


# ── การสร้างข้อมูลต่อ cell ─────────────────────────────────────────────────────


def collect(
    seeds,
    variants: dict,
    users_xlsx,
    record_l3: bool = False,
    record_views: bool = False,
) -> dict:
    val, held, roster = _population()
    stores = {k: Store(record_l3=record_l3) for k in variants}
    ecdf_probe_thr = {"warn": 0.5, "challenge": 0.7, "block": 0.85}
    for seed in seeds:
        t0 = time.perf_counter()
        raw = G3.build_seed(users_xlsx, seed, spec=val, roster=roster)
        assert not (set(raw) & held), "หลุดไปสร้างโปรไฟล์ holdout — หยุดทันที"
        print(f"  seed {seed}: สร้างข้อมูล {time.perf_counter() - t0:.0f}s", flush=True)
        for size in AG.SIZES:
            t1 = time.perf_counter()
            splits = DS.build(users_xlsx, seed, size, raw=raw)
            pm, sm, ecdf = X.fit_all(splits, size, raw)
            ctxs = X.compute_layer_outputs(splits, pm, sm, "tune")
            for key, spec in variants.items():
                cfg, gamma = spec[0], spec[1]
                wrap = spec[3] if len(spec) > 3 else None
                cal_fn = wrap(ecdf) if wrap else ecdf
                st = stores[key]
                for c in ctxs:
                    d = CFG.evaluate(
                        cfg,
                        c.policy,
                        c.rule,
                        c.behavior,
                        c.l3,
                        calibrate_fn=cal_fn,
                        gamma=gamma,
                        thresholds=ecdf_probe_thr,
                    )
                    inp = ResolverInput.from_dict(d.breakdown["resolver"])
                    an = (d.breakdown.get("evidence") or {}).get("anomaly") or {}
                    zone = (d.breakdown.get("conditional") or {}).get("zone")
                    views = None
                    if record_views:
                        # ต้องสร้างหลักฐานจากตัวจริง — `to_contract()` ไม่มี detail
                        # (สาเหตุที่รอบแรกเก็บคะแนนรายมุมมองไม่ได้และเงียบ)
                        views = dict(
                            CFG._anomaly_evidence(c.l3, cfg.views, cal_fn).detail.get(
                                "views"
                            )
                            or {}
                        )
                    st.add(
                        size,
                        c.user,
                        seed,
                        c.is_attack,
                        c.family,
                        inp,
                        (an.get("abstained", True), an.get("evidence_score"), zone),
                        views=views,
                    )
            print(
                f"  seed {seed} size {size:>5}: {len(ctxs)} เหตุการณ์ "
                f"{time.perf_counter() - t1:.0f}s",
                flush=True,
            )
    for st in stores.values():
        st.finalize()
    if record_views and not any(st.views for st in stores.values()):
        # fail-closed: เก็บไม่ได้ต้องหยุด ไม่งั้นข้อสรุปกลายเป็นผลของ "ไม่มีข้อมูล" (B61)
        raise AssertionError("เปิด record_views แล้วแต่ไม่ได้คะแนนรายมุมมองเลย — ตัววัดพัง")
    return stores


# ── calibrate ─────────────────────────────────────────────────────────────────


def cmd_calibrate(args) -> int:
    fz = _frozen()
    combos = [ConditionalParams(**c) for c in AG.g_combinations()]
    variants = _variants(fz, combos)
    print(f"CALIBRATE — seeds {AG.CALIBRATION_SEEDS} · variants {len(variants)}")
    stores = collect(AG.CALIBRATION_SEEDS, variants, args.users)
    rng = random.Random(20260923)

    chosen = {}
    for key, (_cfg, _g, warn) in variants.items():
        st = stores[key]
        sel = choose_thresholds(st, warn)
        checked = parity_check(st, warn, sel["thresholds"]["challenge"], rng)
        rows = outcomes(st, sel["thresholds"])
        fam = family_recall(rows)
        weak = [fam.get(f, 0.0) for f in AG.FAMILY_TARGETS]
        chosen[key] = {
            **sel,
            "parity_checked": checked,
            "family_recall": fam,
            "weak_recall_mean": sum(weak) / len(weak),
            "severe_recall": pooled_recall(rows, AG.SEVERE_FAMILIES),
            "challenge_fpr": sel["challenge"]["worst_fpr"],
        }
        if key.startswith("G"):
            chosen[key]["params"] = combos[int(key[1:])].to_dict()
        print(
            f"  {key}: t_c={sel['thresholds']['challenge']} t_b={sel['thresholds']['block']} "
            f"reach={sel['reachable']} weak={chosen[key]['weak_recall_mean']:.3f} "
            f"severe={chosen[key]['severe_recall']:.3f}",
            flush=True,
        )

    g_results = [
        {**v, "key": k, "reachable": v["reachable"]}
        for k, v in chosen.items()
        if k.startswith("G")
    ]
    best = AG.select_g(g_results)
    out = {
        "stage": "calibration",
        "pre_registration": "hub/backend/tests/reports/accuracy_gate_2026-09-23.md",
        "git_commit": _git("rev-parse", "HEAD"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "seeds": list(AG.CALIBRATION_SEEDS),
        "sizes": list(AG.SIZES),
        "matched_fpr": AG.MATCHED_FPR,
        "gamma": {
            k: fz["per_config_gamma"][AG.CANDIDATE_GAMMA_FROM[k]] for k in AG.CANDIDATES
        },
        "candidates": {
            "B": {
                "thresholds": chosen["B"]["thresholds"],
                "reachable": chosen["B"]["reachable"],
            },
            "E": {
                "thresholds": chosen["E"]["thresholds"],
                "reachable": chosen["E"]["reachable"],
            },
            "G": {
                "thresholds": best["thresholds"],
                "reachable": best["reachable"],
                "params": best["params"],
                "selected_from": best["key"],
            },
        },
        "all": {
            k: {kk: vv for kk, vv in v.items() if kk not in ("challenge", "block")}
            | {
                "challenge_search": {
                    kk: v["challenge"][kk]
                    for kk in ("threshold", "worst_fpr", "reachable")
                },
                "block_search": {
                    kk: v["block"][kk] for kk in ("threshold", "worst_fpr", "reachable")
                },
            }
            for k, v in chosen.items()
        },
    }
    OUT.mkdir(parents=True, exist_ok=True)
    CALIBRATION.write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"\nG ที่เลือก: {best['key']} {best['params']} · thresholds {best['thresholds']}"
    )
    print(
        f"เขียน {CALIBRATION}\nขั้นต่อไป: คัดลอกไป {COMMITTED_CALIBRATION} แล้ว commit ก่อน validate"
    )
    return 0


# ── validate ──────────────────────────────────────────────────────────────────


def _fpr_verdict(store: Store, thr: dict, level: str) -> dict:
    budget = AG.FPR_BUDGETS[level]
    per_size = {}
    for size, users in sorted(store.normal_seed.items()):
        tree = {}
        for user, seeds in users.items():
            for seed, c in seeds.items():
                if level == "challenge":
                    k = c["always"] + (
                        len(c["scores"])
                        - bisect.bisect_left(c["scores"], thr["challenge"])
                    )
                else:
                    k = 0
                tree.setdefault(user, {})[seed] = {"k": int(k), "n": int(c["n"])}
        if level == "block":
            for s, u, sd, inp in store.tail:
                if s == size and resolve_action(inp, thr)[0] == "block":
                    tree[u][sd]["k"] += 1
        ci = BS.cluster_rate_ci(tree, n_boot=N_BOOT, seed=0)
        per_size[size] = BS.rate_verdict(ci, budget)
    verdicts = [v["verdict"] for v in per_size.values()]
    overall = (
        "failed"
        if "failed" in verdicts
        else "inconclusive"
        if "inconclusive" in verdicts
        else "passed"
    )
    return {"verdict": overall, "per_size": per_size}


def _recall_block(rows, families, target) -> dict:
    tree = AG.recall_tree(rows, families=families)
    ci = BS.hierarchical_proportion(tree, n_boot=N_BOOT, seed=0)
    return AG.recall_verdict(ci, target) | {"n_users": len(tree)}


def _campaign_block(rows) -> dict:
    ci = BS.hierarchical_proportion(AG.campaign_tree(rows), n_boot=N_BOOT, seed=0)
    return AG.recall_verdict(ci, AG.CAMPAIGN_RECALL_MIN) | {"n_units": ci["n_units"]}


def _precision(store: Store, rows, thr) -> dict:
    tp_c = sum(AG.caught(r.decision) for r in rows)
    tp_b = sum(r.decision == "block" for r in rows)
    fp_c = sum(
        c["always"]
        + (len(c["scores"]) - bisect.bisect_left(c["scores"], thr["challenge"]))
        for users in store.normal_seed.values()
        for seeds in users.values()
        for c in seeds.values()
    )
    fp_b = sum(1 for *_x, inp in store.tail if resolve_action(inp, thr)[0] == "block")
    return {
        "challenge": tp_c / (tp_c + fp_c) if tp_c + fp_c else None,
        "block": tp_b / (tp_b + fp_b) if tp_b + fp_b else None,
    }


def _l3_stats(store: Store, t_c: float) -> dict:
    by = defaultdict(lambda: {"n": 0, "abstain": 0, "normal": 0, "normal_fire": 0})
    zones = defaultdict(lambda: defaultdict(int))
    for size, is_attack, abstained, ev, zone in store.l3:
        b = by[size]
        b["n"] += 1
        b["abstain"] += bool(abstained)
        if not is_attack:
            b["normal"] += 1
            b["normal_fire"] += bool(not abstained and ev is not None and ev >= t_c)
            if zone:
                zones[size][zone] += 1
    return {
        s: {
            "abstain_rate": v["abstain"] / v["n"],
            "l3_fire_rate_on_normal": v["normal_fire"] / v["normal"]
            if v["normal"]
            else None,
            "normal_zone_share": {z: c / v["normal"] for z, c in zones[s].items()}
            if zones[s]
            else {},
        }
        for s, v in sorted(by.items())
    }


def _paired_delta(rows_a, rows_b, families, n_boot=N_BOOT) -> dict:
    """recall(a) − recall(b) บนเหตุการณ์เดียวกัน · CI จาก bootstrap ระดับผู้ใช้."""
    per_user = defaultdict(lambda: [0, 0, 0])  # hits_a, hits_b, n
    for ra, rb in zip(rows_a, rows_b):
        if ra.family not in families:
            continue
        u = per_user[ra.user]
        u[0] += AG.caught(ra.decision)
        u[1] += AG.caught(rb.decision)
        u[2] += 1
    users = list(per_user)
    if not users:
        return {"delta": None}
    tot = [sum(per_user[u][i] for u in users) for i in range(3)]
    point = (tot[0] - tot[1]) / tot[2]
    rng = random.Random(0)
    dist = []
    for _ in range(n_boot):
        pick = [rng.choice(users) for _ in users]
        a = sum(per_user[u][0] for u in pick)
        b = sum(per_user[u][1] for u in pick)
        n = sum(per_user[u][2] for u in pick)
        dist.append((a - b) / n if n else 0.0)
    dist.sort()
    return {
        "delta": point,
        "ci_low": dist[int(0.025 * n_boot)],
        "ci_high": dist[int(0.975 * n_boot) - 1],
    }


def _l3_value(rows_g, rows_b, store_g: Store, store_b: Store, thr_g, thr_b) -> dict:
    changed = [
        (g, b)
        for g, b in zip(rows_g, rows_b)
        if AG.caught(g.decision) != AG.caught(b.decision)
    ]
    gained = sum(1 for g, b in changed if AG.caught(g.decision))
    lost = sum(1 for g, b in changed if AG.caught(b.decision))
    fp_g = sum(challenge_fpr_by_size(store_g, thr_g["challenge"]).values())
    fp_b = sum(challenge_fpr_by_size(store_b, thr_b["challenge"]).values())
    return {
        "attack_events_changed": len(changed),
        "attack_newly_caught_by_g": gained,
        "attack_lost_by_g": lost,
        "net_attack_caught": gained - lost,
        "sum_over_sizes_challenge_fpr_g_minus_b": fp_g - fp_b,
    }


def _candidate_report(store: Store, thr: dict, base_family: dict | None) -> dict:
    rows = outcomes(store, thr)
    fam = family_recall(rows)
    rep = {
        "thresholds": thr,
        "fpr": {lvl: _fpr_verdict(store, thr, lvl) for lvl in ("challenge", "block")},
        "severe_recall": _recall_block(rows, AG.SEVERE_FAMILIES, AG.SEVERE_RECALL_MIN),
        "campaign_recall": _campaign_block(rows),
        "families": {
            f: _recall_block(rows, {f}, tgt) for f, tgt in AG.FAMILY_TARGETS.items()
        },
        "family_recall_point": fam,
        "precision": _precision(store, rows, thr),
        "l3": _l3_stats(store, thr["challenge"]),
    }
    reg = AG.non_regression(base_family, fam) if base_family is not None else []
    rep["verdict"] = AG.overall_verdict(
        {
            "fpr": {k: v["verdict"] for k, v in rep["fpr"].items()},
            "severe_recall": rep["severe_recall"]["verdict"],
            "campaign_recall": rep["campaign_recall"]["verdict"],
            "families": {f: v["verdict"] for f, v in rep["families"].items()},
            "non_regression": reg,
        }
    )
    return rep, rows


def cmd_validate(args) -> int:
    if not COMMITTED_CALIBRATION.exists():
        print(f"ยังไม่มี {COMMITTED_CALIBRATION} — calibrate แล้ว commit ก่อน")
        return 1
    tracked = _git(
        "ls-files", "--error-unmatch", str(COMMITTED_CALIBRATION.relative_to(REPO))
    )
    dirty = _git(
        "status", "--porcelain", "--", str(COMMITTED_CALIBRATION.relative_to(REPO))
    )
    if tracked.startswith("unavailable") or dirty:
        print("calibration ต้อง commit แล้วและไม่มีการแก้ค้าง — พิสูจน์ว่าตรึงก่อนเปิด validation")
        return 1
    if LEDGER.exists() and not args.reopen:
        print(
            f"validation เปิดไปแล้ว ({LEDGER}) — ห้ามเปิดซ้ำ (B68) · ใช้ --reopen พร้อมเหตุผลเท่านั้น"
        )
        return 1
    cal = json.loads(COMMITTED_CALIBRATION.read_text(encoding="utf-8"))
    cal_sha = hashlib.sha256(
        COMMITTED_CALIBRATION.read_bytes().replace(b"\r\n", b"\n")
    ).hexdigest()
    fz = _frozen()
    g = ConditionalParams(**cal["candidates"]["G"]["params"])
    variants = _variants(fz, [g])
    variants = {"B": variants["B"], "E": variants["E"], "G": variants["G00"]}

    OUT.mkdir(parents=True, exist_ok=True)
    ledger = (
        json.loads(LEDGER.read_text(encoding="utf-8"))
        if LEDGER.exists()
        else {"opens": []}
    )
    ledger["opens"].append(
        {
            "at": datetime.now(timezone.utc).isoformat(),
            "git_commit": _git("rev-parse", "HEAD"),
            "seeds": list(AG.VALIDATION_SEEDS),
            "calibration_sha256": cal_sha,
            "reopen_reason": args.reopen,
        }
    )
    LEDGER.write_text(
        json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"VALIDATE — seeds {AG.VALIDATION_SEEDS} · G = {g.to_dict()}")
    stores = collect(AG.VALIDATION_SEEDS, variants, args.users, record_l3=True)
    thr = {k: cal["candidates"][k]["thresholds"] for k in ("B", "E", "G")}
    rep_b, rows_b = _candidate_report(stores["B"], thr["B"], None)
    rep_e, rows_e = _candidate_report(
        stores["E"], thr["E"], rep_b["family_recall_point"]
    )
    rep_g, rows_g = _candidate_report(
        stores["G"], thr["G"], rep_b["family_recall_point"]
    )
    weak = set(AG.FAMILY_TARGETS)
    out = {
        "stage": "validation",
        "gated_candidate": AG.GATED_CANDIDATE,
        "verdict": rep_g["verdict"],
        "git_commit": _git("rev-parse", "HEAD"),
        "calibration_sha256": cal_sha,
        "seeds": list(AG.VALIDATION_SEEDS),
        "candidates": {"B": rep_b, "E": rep_e, "G": rep_g},
        "paired": {
            "G_minus_B": {
                "severe": _paired_delta(rows_g, rows_b, AG.SEVERE_FAMILIES),
                "weak_families": _paired_delta(rows_g, rows_b, weak),
            },
            "G_minus_E": {
                "severe": _paired_delta(rows_g, rows_e, AG.SEVERE_FAMILIES),
                "weak_families": _paired_delta(rows_g, rows_e, weak),
            },
        },
        "l3_value_vs_B": _l3_value(
            rows_g, rows_b, stores["G"], stores["B"], thr["G"], thr["B"]
        ),
        "holdout_opened": False,
    }
    VALIDATION.write_text(
        json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(
        f"\nคำตัดสินของ G: {rep_g['verdict']['verdict']} · failed {rep_g['verdict']['failed']} "
        f"· inconclusive {rep_g['verdict']['inconclusive']}"
    )
    print(f"เขียน {VALIDATION}")
    return 0


def _arm_variants(fz: dict, g: ConditionalParams) -> dict:
    """แขนของ ablation — ใช้ config production ทุกตัว (B66)."""
    gam, thr = fz["per_config_gamma"], fz["per_config_thresholds"]
    out = {
        "B": (CFG.CONFIGS["B"], gam["B"], thr["B"]["warn"]),
        "C": (CFG.CONFIGS["C"], gam["C"], thr["C"]["warn"]),
        "D": (CFG.CONFIGS["D"], gam["D"], thr["D"]["warn"]),
        "E": (CFG.CONFIGS["E"], gam["E"], thr["E"]["warn"]),
        "G": (CFG.with_params(CFG.CONFIGS["G"], g), gam["E"], thr["E"]["warn"]),
    }
    return {k: out[k] for k in AG.ABLATION_ARMS}


def _view_auc(store: Store, view: str, n_boot: int = 500) -> dict | None:
    """AUC ของหลักฐานมุมมองเดียวล้วน + CI จาก bootstrap ระดับผู้ใช้."""
    by_user: dict = defaultdict(lambda: ([], []))
    for user, is_attack, views in store.views:
        v = (views or {}).get(view)
        if v is None:
            continue
        by_user[user][1 if is_attack else 0].append(float(v))
    if not by_user:
        return None
    normal = [x for u in by_user.values() for x in u[0]]
    attack = [x for u in by_user.values() for x in u[1]]
    point = AG.auc(normal, attack)
    if point is None:
        return None
    users = list(by_user)
    rng = random.Random(0)
    dist = []
    for _ in range(n_boot):
        pick = [rng.choice(users) for _ in users]
        n = [x for u in pick for x in by_user[u][0]]
        a = [x for u in pick for x in by_user[u][1]]
        val = AG.auc(n, a)
        if val is not None:
            dist.append(val)
    dist.sort()
    return {
        "auc": round(point, 4),
        "ci_low": round(dist[int(0.025 * len(dist))], 4) if dist else None,
        "ci_high": round(dist[min(len(dist) - 1, int(0.975 * len(dist)))], 4)
        if dist
        else None,
        "n_normal": len(normal),
        "n_attack": len(attack),
        "n_users": len(users),
    }


def cmd_ablation(args) -> int:
    if not COMMITTED_CALIBRATION.exists():
        print("ต้องมี calibration ที่ commit แล้ว (candidate G)")
        return 1
    cal = json.loads(COMMITTED_CALIBRATION.read_text(encoding="utf-8"))
    g = ConditionalParams(**cal["candidates"]["G"]["params"])
    fz = _frozen()
    arms = _arm_variants(fz, g)

    print(
        f"ABLATION ขั้นที่ 1 — ตั้ง threshold ให้ FPR เท่ากันบน calibration {AG.CALIBRATION_SEEDS}"
    )
    cal_stores = collect(AG.CALIBRATION_SEEDS, arms, args.users)
    rng = random.Random(20260923)
    thresholds = {}
    for key, (_c, _g, warn) in arms.items():
        sel = choose_thresholds(cal_stores[key], warn)
        parity_check(cal_stores[key], warn, sel["thresholds"]["challenge"], rng)
        thresholds[key] = sel
        print(
            f"  {key}: t_c={sel['thresholds']['challenge']} t_b={sel['thresholds']['block']} "
            f"reach={sel['reachable']}",
            flush=True,
        )
    del cal_stores
    OUT.mkdir(parents=True, exist_ok=True)
    ABLATION_CAL.write_text(
        json.dumps(
            {
                "stage": "ablation_calibration",
                "seeds": list(AG.CALIBRATION_SEEDS),
                "git_commit": _git("rev-parse", "HEAD"),
                "arms": {k: v["thresholds"] for k, v in thresholds.items()},
                "reachable": {k: v["reachable"] for k, v in thresholds.items()},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"\nABLATION ขั้นที่ 2 — วัดบน seed ใหม่ {AG.ABLATION_SEEDS}")
    stores = collect(
        AG.ABLATION_SEEDS, arms, args.users, record_l3=True, record_views=True
    )
    rows = {k: outcomes(stores[k], thresholds[k]["thresholds"]) for k in arms}
    weak = set(AG.FAMILY_TARGETS)
    report = {}
    for key in arms:
        st, thr = stores[key], thresholds[key]["thresholds"]
        report[key] = {
            "thresholds": thr,
            "challenge_fpr_by_size": {
                s: round(v, 5)
                for s, v in sorted(challenge_fpr_by_size(st, thr["challenge"]).items())
            },
            "family_recall": family_recall(rows[key]),
            "weak_recall_mean": sum(
                family_recall(rows[key]).get(f, 0.0) for f in AG.FAMILY_TARGETS
            )
            / len(AG.FAMILY_TARGETS),
            "severe_recall": pooled_recall(rows[key], AG.SEVERE_FAMILIES),
            "campaign_recall": _campaign_block(rows[key]),
            "paired_vs_B": _paired_delta(rows[key], rows["B"], weak),
            "normal_score_quantiles": _normal_quantiles(st),
        }
    views = {v: _view_auc(stores["E"], v) for v in ("point", "sequence")}
    out = {
        "stage": "ablation",
        "question": "L3 มุมมองไหนมีสัญญาณ และมุมมองไหนดันคะแนนของเหตุการณ์ปกติขึ้น",
        "pre_registration": "hub/backend/tests/reports/accuracy_gate_2026-09-23.md §7",
        "git_commit": _git("rev-parse", "HEAD"),
        "seeds": list(AG.ABLATION_SEEDS),
        "arms": report,
        "views": views,
        "conclusion": AG.ablation_conclusion(views, report),
        "holdout_opened": False,
    }
    ABLATION.write_text(
        json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(f"\nข้อสรุป: {out['conclusion']}")
    print(f"เขียน {ABLATION}")
    return 0


def _normal_quantiles(store: Store) -> dict:
    """ควอนไทล์ของคะแนนสุดท้ายบนเหตุการณ์ปกติ — ใช้ดูว่าหลักฐาน L3 ดันคะแนนขึ้นแค่ไหน."""
    vals = sorted(
        s
        for users in store.normal_seed.values()
        for seeds in users.values()
        for c in seeds.values()
        for s in c["scores"]
    )
    if not vals:
        return {}
    return {
        f"q{int(p * 1000) / 10}": round(vals[min(len(vals) - 1, int(p * len(vals)))], 6)
        for p in (0.5, 0.9, 0.99, 0.995, 0.999)
    }


def cmd_views(args) -> int:
    """วัด AUC ของหลักฐานรายมุมมองบน seed ชุดใหม่ (ไม่ใช้ threshold · ไม่แตะผลของแขนใน ablation.json)."""
    cal = json.loads(COMMITTED_CALIBRATION.read_text(encoding="utf-8"))
    g = ConditionalParams(**cal["candidates"]["G"]["params"])
    only_e = {"E": _arm_variants(_frozen(), g)["E"]}
    print(f"VIEW AUC — seeds {AG.ABLATION_VIEW_SEEDS} · แขน E (มีทั้งสองมุมมอง)")
    stores = collect(AG.ABLATION_VIEW_SEEDS, only_e, args.users, record_views=True)
    views = {v: _view_auc(stores["E"], v) for v in ("point", "sequence")}
    prev = json.loads(ABLATION.read_text(encoding="utf-8"))
    out = {
        "stage": "ablation_views",
        "seeds": list(AG.ABLATION_VIEW_SEEDS),
        "git_commit": _git("rev-parse", "HEAD"),
        "views": views,
        "usable": {v: AG.view_usable(s) for v, s in views.items()},
        "conclusion": AG.ablation_conclusion(views, prev["arms"]),
        "arms_from": {"file": ABLATION.name, "seeds": prev["seeds"]},
        "holdout_opened": False,
    }
    (OUT / "ablation_views.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print("\nAUC: " + json.dumps(views, ensure_ascii=False))
    print(f"ข้อสรุป: {out['conclusion']}")
    return 0


def _tail_wrapper(tau: float):
    """calibrate_fn ของแขน H — percentile เดิมทุกชั้น ยกเว้น point ที่ผ่าน tail transform ของ production."""

    def make(ecdf):
        def cal(layer: str, raw: float) -> float:
            value = ecdf(layer, raw)
            return tail_transform(value, tau) if layer == "anomaly_point" else value

        return cal

    return make


def _recal_variants(fz: dict, taus) -> dict:
    gam, thr = fz["per_config_gamma"], fz["per_config_thresholds"]
    out = {
        "B": (CFG.CONFIGS["B"], gam["B"], thr["B"]["warn"]),
        "C": (CFG.CONFIGS["C"], gam["C"], thr["C"]["warn"]),
    }
    for tau in taus:
        out[f"H{tau}"] = (
            CFG.CONFIGS["C"],  # point อย่างเดียว — sequence ไม่เข้า fusion รอบนี้
            gam["C"],
            thr["C"]["warn"],
            _tail_wrapper(tau),
        )
    return out


def paired_campaign_delta(rows_h, rows_b, n_boot=N_BOOT) -> dict:
    """delta ของ **campaign recall** (หน่วย = แคมเปญ) แบบจับคู่ · bootstrap ระดับผู้ใช้.

    §10.5: เกณฑ์ §9.4 เขียนว่า "campaign recall" ซึ่งนิยามไว้ที่หน่วยแคมเปญ (§5.1) แต่โค้ดรอบแรก
    ส่ง `_paired_delta(..., {"campaign"})` ซึ่งเป็น recall **ระดับเหตุการณ์** ของตระกูลชื่อ campaign
    """

    def by_user(rows):
        out: dict = defaultdict(dict)
        for r in rows:
            if not r.campaign:
                continue
            out[r.user][r.campaign] = out[r.user].get(r.campaign, False) or AG.caught(
                r.decision
            )
        return out

    ha, ba = by_user(rows_h), by_user(rows_b)
    users = sorted(set(ha) & set(ba))
    if not users:
        return {"delta": None}
    per_user = {
        u: (
            sum(ha[u].values()),
            sum(ba[u][c] for c in ha[u] if c in ba[u]),
            len(ha[u]),
        )
        for u in users
    }
    tot = [sum(per_user[u][i] for u in users) for i in range(3)]
    point = (tot[0] - tot[1]) / tot[2] if tot[2] else 0.0
    rng = random.Random(0)
    dist = []
    for _ in range(n_boot):
        pick = [rng.choice(users) for _ in users]
        a = sum(per_user[u][0] for u in pick)
        b = sum(per_user[u][1] for u in pick)
        n = sum(per_user[u][2] for u in pick)
        dist.append((a - b) / n if n else 0.0)
    dist.sort()
    return {
        "delta": point,
        "ci_low": dist[int(0.025 * n_boot)],
        "ci_high": dist[min(len(dist) - 1, int(0.975 * n_boot))],
        "unit": "campaign",
    }


def _families_worse(rows_h, rows_b) -> list:
    """ตระกูลที่แย่ลงอย่างมีนัย (ขอบบนของ paired delta < 0)."""
    worse = []
    for fam in AG.FAMILY_TARGETS:
        d = _paired_delta(rows_h, rows_b, {fam})
        if d.get("ci_high") is not None and d["ci_high"] < 0:
            worse.append(fam)
    return sorted(worse)


def _campaign_raw(rows) -> list:
    """ผลดิบระดับแคมเปญ (ผู้ใช้ × แคมเปญ × จับได้ไหม) — เก็บไว้ให้แก้การวิเคราะห์ภายหลังได้โดยไม่ต้องวัดใหม่.

    B81 ข้อสอง: รอบแรกเก็บแต่ค่าสรุป → พอพบว่า guard ใช้หน่วยผิด ก็คำนวณ CI ที่หน่วยถูกต้องจากไฟล์เดิมไม่ได้
    """
    seen: dict = {}
    for r in rows:
        if not r.campaign:
            continue
        key = (r.user, r.campaign)
        seen[key] = seen.get(key, False) or AG.caught(r.decision)
    return [[u, c, bool(v)] for (u, c), v in sorted(seen.items())]


def _recal_phase1(args, fz):
    """เลือก tau + threshold บน calibration — ข้ามได้เมื่อใช้ค่าที่ตรึงไว้."""
    print(
        f"RECALIBRATION ขั้นที่ 1 — เลือก tau + threshold บน calibration {AG.CALIBRATION_SEEDS}"
    )
    cal_variants = _recal_variants(fz, AG.TAU_GRID)
    cal_stores = collect(AG.CALIBRATION_SEEDS, cal_variants, args.users)
    rng = random.Random(20260923)
    picked = {}
    for key, spec in cal_variants.items():
        warn = spec[2]
        sel = choose_thresholds(cal_stores[key], warn)
        parity_check(cal_stores[key], warn, sel["thresholds"]["challenge"], rng)
        rows = outcomes(cal_stores[key], sel["thresholds"])
        fam = family_recall(rows)
        weak = sum(fam.get(f, 0.0) for f in AG.FAMILY_TARGETS) / len(AG.FAMILY_TARGETS)
        picked[key] = {
            **sel,
            "weak_recall_mean": weak,
            "severe_recall": pooled_recall(rows, AG.SEVERE_FAMILIES),
        }
        print(
            f"  {key}: t_c={sel['thresholds']['challenge']} reach={sel['reachable']} "
            f"weak={weak:.3f}",
            flush=True,
        )
    del cal_stores
    # เลือก tau ตามกฎที่ประกาศไว้: weak recall สูงสุด · เสมอ -> tau สูงกว่า (L3 มีอิทธิพลน้อยกว่า)
    h_keys = [k for k in picked if k.startswith("H")]
    best = max(
        h_keys,
        key=lambda k: (round(picked[k]["weak_recall_mean"], 6), float(k[1:])),
    )
    tau = float(best[1:])
    OUT.mkdir(parents=True, exist_ok=True)
    RECAL_CAL.write_text(
        json.dumps(
            {
                "stage": "recalibration_calibration",
                "seeds": list(AG.CALIBRATION_SEEDS),
                "git_commit": _git("rev-parse", "HEAD"),
                "tau_grid": list(AG.TAU_GRID),
                "selected_tau": tau,
                "thresholds": {k: v["thresholds"] for k, v in picked.items()},
                "weak_recall_mean": {
                    k: v["weak_recall_mean"] for k, v in picked.items()
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n  tau ที่เลือก = {tau}")
    return picked, best, tau


def cmd_recal(args) -> int:
    fz = _frozen()
    cal_variants = _recal_variants(fz, AG.TAU_GRID)
    if args.reuse_calibration:
        if not RECAL_CAL.exists():
            print(f"ไม่มี {RECAL_CAL} — ต้องรันแบบปกติก่อน")
            return 1
        prev = json.loads(RECAL_CAL.read_text(encoding="utf-8"))
        tau = float(prev["selected_tau"])
        best = f"H{tau}"
        picked = {
            k: {"thresholds": v, "weak_recall_mean": prev["weak_recall_mean"].get(k)}
            for k, v in prev["thresholds"].items()
        }
        print(
            f"RECALIBRATION — ใช้ tau/threshold ที่ตรึงไว้ (tau={tau}) ไม่เลือกค่าใหม่ "
            "· แก้การวิเคราะห์ตาม B81 เท่านั้น"
        )
    else:
        picked, best, tau = _recal_phase1(args, fz)

    print(f"RECALIBRATION ขั้นที่ 2 — วัดบน seed ใหม่ {AG.RECAL_SEEDS}")
    arms = {
        "B": cal_variants["B"],
        "C": cal_variants["C"],
        "H": cal_variants[best],
    }
    thr = {k: picked[{"B": "B", "C": "C", "H": best}[k]]["thresholds"] for k in arms}
    stores = collect(AG.RECAL_SEEDS, arms, args.users, record_l3=True)
    rows = {k: outcomes(stores[k], thr[k]) for k in arms}
    weak = set(AG.FAMILY_TARGETS)
    report = {}
    for k in arms:
        st = stores[k]
        report[k] = {
            "thresholds": thr[k],
            "fpr": {
                lvl: _fpr_verdict(st, thr[k], lvl) for lvl in ("challenge", "block")
            },
            "challenge_fpr_by_size": {
                s: round(v, 5)
                for s, v in sorted(
                    challenge_fpr_by_size(st, thr[k]["challenge"]).items()
                )
            },
            "family_recall": family_recall(rows[k]),
            "weak_recall_mean": sum(
                family_recall(rows[k]).get(f, 0.0) for f in AG.FAMILY_TARGETS
            )
            / len(AG.FAMILY_TARGETS),
            "severe_recall": pooled_recall(rows[k], AG.SEVERE_FAMILIES),
            "campaign_recall": _campaign_block(rows[k]),
            "paired_vs_B": _paired_delta(rows[k], rows["B"], weak),
            # ผลดิบระดับแคมเปญ — แก้การวิเคราะห์ภายหลังได้โดยไม่ต้องวัดใหม่ (B81)
            "campaign_raw": _campaign_raw(rows[k]),
        }
    parts = {
        "primary_weak_delta": report["H"]["paired_vs_B"],
        # หน่วยเหตุการณ์ของตระกูล campaign — เก็บไว้เทียบกับของเดิมที่ guard เคยใช้ผิดหน่วย (B81)
        "campaign_delta_event_unit": _paired_delta(rows["H"], rows["B"], {"campaign"}),
        "severe_delta": _paired_delta(rows["H"], rows["B"], AG.SEVERE_FAMILIES),
        "campaign_delta": paired_campaign_delta(rows["H"], rows["B"]),
        "fpr_verdicts": {
            lvl: report["H"]["fpr"][lvl]["verdict"] for lvl in ("challenge", "block")
        },
        "severe_recall": report["H"]["severe_recall"],
        "families_worse": _families_worse(rows["H"], rows["B"]),
    }
    verdict = AG.recalibration_verdict(parts)
    # ความซ้ำซ้อนกับ L1/L2 — ในบรรดาที่ H จับได้ มีกี่ส่วนที่ B จับได้อยู่แล้ว
    h_caught = [AG.caught(r.decision) for r in rows["H"]]
    b_caught = [AG.caught(r.decision) for r in rows["B"]]
    both = sum(1 for a, b in zip(h_caught, b_caught) if a and b)
    out = {
        "stage": "recalibration",
        "pre_registration": "hub/backend/tests/reports/accuracy_gate_2026-09-23.md §9",
        "git_commit": _git("rev-parse", "HEAD"),
        "seeds": list(AG.RECAL_SEEDS),
        "selected_tau": tau,
        "arms": report,
        "parts": parts,
        "verdict": verdict,
        "overlap_with_baseline": {
            "h_caught": sum(h_caught),
            "b_caught": sum(b_caught),
            "caught_by_both": both,
            "h_only": sum(1 for a, b in zip(h_caught, b_caught) if a and not b),
            "b_only": sum(1 for a, b in zip(h_caught, b_caught) if b and not a),
        },
        "holdout_opened": False,
    }
    RECAL.write_text(
        json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(f"\nคำตัดสิน H: {verdict}")
    print(f"เขียน {RECAL}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    ca = sub.add_parser("calibrate")
    ca.add_argument("--users", type=Path, default=BP.DEFAULT_USERS_XLSX)
    va = sub.add_parser("validate")
    va.add_argument("--users", type=Path, default=BP.DEFAULT_USERS_XLSX)
    va.add_argument(
        "--reopen", default=None, help="เหตุผลที่ต้องเปิด validation ซ้ำ (บันทึกใน ledger)"
    )
    ab = sub.add_parser("ablation")
    ab.add_argument("--users", type=Path, default=BP.DEFAULT_USERS_XLSX)
    vw = sub.add_parser("views")
    vw.add_argument("--users", type=Path, default=BP.DEFAULT_USERS_XLSX)
    rc = sub.add_parser("recal")
    rc.add_argument("--users", type=Path, default=BP.DEFAULT_USERS_XLSX)
    rc.add_argument(
        "--reuse-calibration",
        action="store_true",
        help="ใช้ tau/threshold ที่ตรึงไว้ (แก้การวิเคราะห์ ไม่เลือกค่าใหม่ — B81)",
    )
    args = ap.parse_args()
    if args.cmd == "calibrate":
        return cmd_calibrate(args)
    if args.cmd == "ablation":
        return cmd_ablation(args)
    if args.cmd == "views":
        return cmd_views(args)
    if args.cmd == "recal":
        return cmd_recal(args)
    return cmd_validate(args)


if __name__ == "__main__":
    raise SystemExit(main())
