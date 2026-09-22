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

    def add(self, size, user, seed, is_attack, family, inp: ResolverInput, l3info):
        if self.record_l3:
            self.l3.append((size, is_attack, *l3info))
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


def collect(seeds, variants: dict, users_xlsx, record_l3: bool = False) -> dict:
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
            for key, (cfg, gamma, _w) in variants.items():
                st = stores[key]
                for c in ctxs:
                    d = CFG.evaluate(
                        cfg,
                        c.policy,
                        c.rule,
                        c.behavior,
                        c.l3,
                        calibrate_fn=ecdf,
                        gamma=gamma,
                        thresholds=ecdf_probe_thr,
                    )
                    inp = ResolverInput.from_dict(d.breakdown["resolver"])
                    an = (d.breakdown.get("evidence") or {}).get("anomaly") or {}
                    zone = (d.breakdown.get("conditional") or {}).get("zone")
                    st.add(
                        size,
                        c.user,
                        seed,
                        c.is_attack,
                        c.family,
                        inp,
                        (an.get("abstained", True), an.get("evidence_score"), zone),
                    )
            print(
                f"  seed {seed} size {size:>5}: {len(ctxs)} เหตุการณ์ "
                f"{time.perf_counter() - t1:.0f}s",
                flush=True,
            )
    for st in stores.values():
        st.finalize()
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
    args = ap.parse_args()
    return cmd_calibrate(args) if args.cmd == "calibrate" else cmd_validate(args)


if __name__ == "__main__":
    raise SystemExit(main())
