"""V4 offline fusion pilot: personal point IF + rolling campaign sequence.

Production L4/Policy/L1/L2 code is called directly. Per-user masked point model
has no production service route yet, so this pilot cannot authorize holdout.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

import numpy as np
from sklearn.ensemble import IsolationForest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
for path in (HERE, HERE.parent, ROOT / "hub" / "backend"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
# Backend owns app.security; ml-service also has an unrelated `app` package.
sys.path.insert(0, str(ROOT / "hub" / "backend"))

import ablate_v4_behavior as A  # noqa: E402
import exp_hybrid_gate as X  # noqa: E402
import exp_real_seeded_validation as V1  # noqa: E402
import exp_real_seeded_validation_v2 as V2  # noqa: E402
import gen_v4_behavior as G4  # noqa: E402
from app.security.risk_fusion import DEFAULT_GAMMA  # noqa: E402
from hybrid_experiment import configs as CFG  # noqa: E402
from hybrid_experiment import dataset as DS  # noqa: E402
from hybrid_experiment import tune as TU  # noqa: E402
from point_scoring import scores_with_model  # noqa: E402

SEEDS = (731, 732, 733)
SIZES = (100, 2000)


def _point_models(splits, names):
    indexes = [A.ALL.index(name) for name in names]
    models = {}
    for alias, user in splits.items():
        if len(user.train_ft) >= 50:
            models[alias] = IsolationForest(
                n_estimators=100, contamination=0.02, random_state=42
            ).fit(np.asarray(user.train_ft, dtype=float)[:, indexes])
    return models, indexes


def _point_scores(model, indexes, vectors):
    if model is None:
        return [None] * len(vectors)
    return scores_with_model(model, np.asarray(vectors, dtype=float)[:, indexes])


def _rolling_sequence(info, pairs):
    model, base, profile, train_res = info
    if model is None or not train_res:
        return [None] * len(pairs)
    tail = list(train_res[-(X.E3.W - 1):])
    features = []
    for raw, vector in pairs:
        residual = X.SEQL._resid(vector, raw, profile, base)
        window = (tail + [residual])[-X.E3.W:]
        while len(window) < X.E3.W:
            window = [window[0]] + window
        features.append(X.SEQL._winfeat(window))
        tail = (tail + [residual])[-(X.E3.W - 1):]
    return [float(s) for s in X.E3._anom(model, features)]


def _score_attack_sequence(info, attacks):
    result = X.sequence_score(info[0], info[1], info[2], info[3], attacks)
    by_campaign = sorted([
        (i, pair) for i, pair in enumerate(attacks)
        if pair[0].get("scenario") == "campaign"
    ], key=lambda item: item[1][0]["created_at"])
    # One ordered campaign stream; only earlier phases enter the tail.
    if by_campaign:
        rolling = _rolling_sequence(info, [pair for _, pair in by_campaign])
        for (index, _), score in zip(by_campaign, rolling):
            result[index] = score
    return result


def _context(alias, is_attack, raw, vector, point, sequence, profile):
    raw = raw or {}
    return X.EventCtx(
        user=alias,
        is_attack=is_attack,
        family=raw.get("scenario"),
        campaign=f"{alias}:{raw.get('scenario')}" if is_attack else None,
        policy=X.evaluate_policy(vector, None, alias, None, None),
        rule=X.evaluate_rules(vector, db=None, user_id=alias, ip=None, geo_country=None),
        behavior=X.evaluate_behavior(
            vector, profile, subsystem_id=raw.get("subsystem"),
            user_agent=raw.get("user_agent"),
        ),
        l3=CFG.L3Scores(
            point_raw=point, sequence_raw=sequence,
            sequence_eligible=sequence is not None,
        ),
    )


def _fit_contexts(raw, size, names):
    # DS.build only consumes validation aliases supplied by the caller.
    splits = DS.build(Path("synthetic_users.xlsx"), 0, size, raw=raw)
    models, indexes = _point_models(splits, names)
    sequence = {alias: X.fit_sequence_model(u, size, raw[alias]) for alias, u in splits.items()}
    cal, tune = [], []
    point_cal = []
    for alias, u in splits.items():
        info = sequence[alias]
        point = models.get(alias)
        calibration_points = _point_scores(point, indexes, u.cal_normal_ft)
        point_cal.extend(s for s in calibration_points if s is not None)
        cal_seq = X.sequence_score(*info, [({}, v) for v in u.cal_normal_ft])
        cal.extend(
            _context(alias, False, {}, v, pt, seq, info[2])
            for v, pt, seq in zip(u.cal_normal_ft, calibration_points, cal_seq)
        )
        normal_points = _point_scores(point, indexes, u.tune_normal_ft)
        normal_seq = X.sequence_score(*info, [({}, v) for v in u.tune_normal_ft])
        tune.extend(
            _context(alias, False, {}, v, pt, seq, info[2])
            for v, pt, seq in zip(u.tune_normal_ft, normal_points, normal_seq)
        )
        campaign_like = raw[alias]["camp_like"]
        assert len(campaign_like) == 5 and all(r["label"] == 0 for r, _ in campaign_like)
        like_points = _point_scores(point, indexes, [v for _, v in campaign_like])
        like_seq = _rolling_sequence(info, campaign_like)
        tune.extend(
            _context(alias, False, r, v, pt, seq, info[2])
            for (r, v), pt, seq in zip(campaign_like, like_points, like_seq)
        )
        attacks = u.tune_attacks
        attack_points = _point_scores(point, indexes, [v for _, v in attacks])
        attack_seq = _score_attack_sequence(info, attacks)
        tune.extend(
            _context(alias, True, r, v, pt, seq, info[2])
            for (r, v), pt, seq in zip(attacks, attack_points, attack_seq)
        )

    ecdf = DS.ECDF()
    ecdf.fit("rule", [1.0 if c.rule.blocked else c.rule.score for c in cal])
    ecdf.fit("behavior", [c.behavior.score for c in cal])
    ecdf.fit("anomaly_point", point_cal)
    ecdf.fit(
        "anomaly_sequence",
        [c.l3.sequence_raw for c in cal if c.l3.sequence_raw is not None],
    )
    return cal, tune, ecdf


def run(args):
    artifact = args.artifact_dir
    profiles = json.loads((artifact / "population_spec.json").read_text())
    meta = json.loads((artifact / "population_summary.json").read_text())
    roster = json.loads((artifact / "roster_real_seeded_v4.json").read_text())
    val, hold = set(meta["split"]["validation"]), set(meta["split"]["holdout"])
    if len(val) != 32 or len(hold) != 16 or val & hold:
        raise ValueError("split invalid")
    selected = [p for p in profiles if p["alias"] in val]
    selected_roster = {alias: roster[alias] for alias in val}
    raw_by_seed = {
        seed: G4.build_seed(
            artifact / "synthetic_users.xlsx", seed, selected, selected_roster
        ) for seed in args.seeds
    }
    for raw in raw_by_seed.values():
        V1._trim_dev_attacks(raw)
        assert V1._feature_contract(raw)["passed"]
        assert sum(len(u["dev_attacks"]) for u in raw.values()) / (
            sum(len(u["dev_attacks"]) + 505 for u in raw.values())
        ) <= 0.07

    records, tuning = {}, {}
    for group, names in A.GROUPS.items():
        records[group] = {}
        tuning[group] = {}
        for seed in args.seeds:
            raw = raw_by_seed[seed]
            for size in args.sizes:
                started = time.perf_counter()
                calibration, tune, ecdf = _fit_contexts(raw, size, names)
                records[group][(seed, size)] = X.build_records(
                    calibration, ecdf, CFG.CONFIGS["E"], DEFAULT_GAMMA
                )
                tuning[group][(seed, size)] = (tune, ecdf)
                print(f"calculated group={group} seed={seed} size={size} "
                      f"seconds={time.perf_counter()-started:.1f}", flush=True)
        # Keep one candidate's cells in memory at a time for calibration.
    thresholds, details = {}, {}
    for group in A.GROUPS:
        thresholds[group], details[group] = V2.calibrate_thresholds(records[group])
        print(f"calibrated {group}: {thresholds[group]}", flush=True)
    frozen = {
        "status": "offline_pilot_no_service_parity_no_holdout",
        "groups": {key: list(names) for key, names in A.GROUPS.items()},
        "seeds": list(args.seeds), "sizes": list(args.sizes),
        "targets": V2.CAL_TARGETS, "thresholds": thresholds,
        "generator_sha256": V2._sha256(Path(G4.__file__)),
        "code_sha256": V2._sha256(Path(__file__)),
        "population_sha256": V2._sha256(artifact / "population_spec.json"),
    }
    args.frozen.parent.mkdir(parents=True, exist_ok=True)
    args.frozen.write_text(json.dumps(frozen, indent=2) + "\n")
    print("NORMAL-ONLY THRESHOLDS FROZEN BEFORE TUNING", flush=True)

    result = {
        "status": "offline_pilot_no_service_parity_no_holdout",
        "holdout_opened": False, "production_changed": False,
        "thresholds": thresholds, "calibration": details, "results": {},
    }
    for group in A.GROUPS:
        result["results"][group] = {}
        if not thresholds[group]:
            continue
        for size in args.sizes:
            rows_by, cells = {}, []
            for seed in args.seeds:
                tune, ecdf = tuning[group][(seed, size)]
                rows = X.apply_config(
                    tune, CFG.CONFIGS["E"], ecdf, DEFAULT_GAMMA, thresholds[group]
                )
                rows_by[seed] = rows
                cells.append(TU.cell_stat(seed, size, rows))
            report = V1._history_report(rows_by, cells, ci_seed=48000 + size)
            summary = report["summary"]
            result["results"][group][str(size)] = {
                "recall": summary["recall"], "precision": summary["precision"],
                "warn_fpr": summary["warn_fpr"],
                "challenge_fpr": summary["challenge_fpr"],
                "block_fpr": summary["block_fpr"],
                "family_recall": {name: data["recall"] for name, data in report["family_recall"].items()},
                "pilot_quality_passed": report["history_gate_passed"],
                "service_parity_passed": False,
            }
            print(f"tuning group={group} size={size}", flush=True)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "holdout_opened": False}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--frozen", type=Path, required=True)
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--seeds", type=int, nargs="+", default=SEEDS)
    parser.add_argument("--sizes", type=int, nargs="+", default=SIZES)
    args = parser.parse_args()
    if not set(args.seeds) <= set(SEEDS) or not set(args.sizes) <= set(SIZES):
        raise ValueError("non-preregistered pilot seeds/sizes")
    run(args)


if __name__ == "__main__":
    main()
