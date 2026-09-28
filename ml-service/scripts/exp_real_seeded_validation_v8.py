"""V8 layer-level comparison with production evidence, fusion and resolver."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import exp_real_seeded_validation_v5 as V5
from app.security.risk_evidence import behavior_evidence, rule_evidence
from app.security.risk_fusion import ResolverInput, fuse

SEEDS = (771, 772, 773)
SIZE = 2000
ARMS = ("L1", "L2", "B", "C", "D", "E", "G")


def solo_records(ctxs, ecdf, layer: str) -> list:
    """Score a single existing evidence layer via the production L4 resolver."""
    recs = []
    for ctx in ctxs:
        evidence = (
            rule_evidence(ctx.rule) if layer == "L1" else behavior_evidence(ctx.behavior)
        )
        evidence.evidence_score = ecdf(evidence.layer, evidence.raw_score or 0.0)
        decision = fuse(
            ctx.policy, [evidence], gamma=V5.DEFAULT_GAMMA,
            thresholds=V5.X.PROBE_THR,
        )
        resolver = ResolverInput.from_dict(decision.breakdown["resolver"])
        recs.append(V5.TU.EventRecord(
            user=ctx.user, is_attack=ctx.is_attack, family=ctx.family,
            campaign=ctx.campaign, resolver=resolver, resolver_no_l3=resolver,
            l3_abstained=True, latency_ms=ctx.layer_ms,
        ))
    return recs


def _surfaced(row) -> bool:
    return row.decision.removeprefix("would_") in ("warn", "challenge", "block")


def run(artifact: Path, frozen: Path, output: Path) -> dict:
    spec = json.loads((artifact / "population_spec.json").read_text())
    meta = json.loads((artifact / "population_summary.json").read_text())
    roster = json.loads((artifact / "roster_real_seeded_v8.json").read_text())
    val, hold = set(meta["split"]["validation"]), set(meta["split"]["holdout"])
    if len(val) != 32 or len(hold) != 16 or val & hold:
        raise ValueError("V8 split invalid")
    records = {arm: {} for arm in ARMS}
    tuning = {arm: {} for arm in ARMS}
    anomaly_rates = {}
    for seed in SEEDS:
        raw = V5.G5.build_seed(
            artifact / "synthetic_users.xlsx", seed,
            [p for p in spec if p["alias"] in val],
            {alias: roster[alias] for alias in val},
        )
        V5.V1._trim_dev_attacks(raw)
        if not V5.V1._feature_contract(raw)["passed"]:
            raise ValueError("V8 23-feature contract failed")
        count = sum(len(u["dev_attacks"]) for u in raw.values())
        anomaly_rates[str(seed)] = count / (count + 505 * len(raw))
        if anomaly_rates[str(seed)] > 0.07:
            raise ValueError("anomaly fraction above 7 percent")
        cal, tune, ecdf = V5.V4._fit_contexts(raw, SIZE, V5.A.GROUPS["behavioral"])
        for arm, cells in records.items():
            if arm in ("L1", "L2"):
                cells[(seed, SIZE)] = solo_records(cal, ecdf, arm)
                tuning[arm][seed] = solo_records(tune, ecdf, arm)
            else:
                cfg = V5.CFG.CONFIGS[arm]
                cells[(seed, SIZE)] = V5.X.build_records(
                    cal, ecdf, cfg, V5.DEFAULT_GAMMA
                )
                tuning[arm][seed] = (tune, ecdf)
        print(f"calculated seed={seed}", flush=True)
    thresholds, calibration = {}, {}
    for arm, cells in records.items():
        thresholds[arm], calibration[arm] = V5.V2.calibrate_thresholds(cells)
    frozen.parent.mkdir(parents=True, exist_ok=True)
    frozen.write_text(json.dumps({
        "status": "v8_thresholds_frozen_before_tuning",
        "population_sha256": V5.V2._sha256(artifact / "population_spec.json"),
        "harness_sha256": V5.V2._sha256(Path(__file__)),
        "generator_sha256": V5.V2._sha256(Path(V5.G5.__file__)),
        "thresholds": thresholds, "seeds": list(SEEDS), "history": SIZE,
    }, indent=2) + "\n")
    print("V8 THRESHOLDS FROZEN BEFORE TUNING", flush=True)
    result = {
        "status": "v8_offline_layer_comparison_no_service_parity",
        "holdout_opened": False, "production_changed": False,
        "anomaly_rates": anomaly_rates, "thresholds": thresholds,
        "calibration": calibration, "arms": {}, "l3_vs_baseline": {},
    }
    outcomes = {}
    for arm, threshold in thresholds.items():
        if threshold is None:
            result["arms"][arm] = {"status": "normal_calibration_infeasible"}
            continue
        rows_by, stats = {}, []
        for seed in SEEDS:
            if arm in ("L1", "L2"):
                rows = V5.TU.resolve_rows(tuning[arm][seed], threshold)
            else:
                ctx, ecdf = tuning[arm][seed]
                rows = V5.X.apply_config(
                    ctx, V5.CFG.CONFIGS[arm], ecdf, V5.DEFAULT_GAMMA, threshold
                )
            rows_by[seed] = rows
            stats.append(V5.TU.cell_stat(seed, SIZE, rows))
        outcomes[arm] = rows_by
        report = V5.V1._history_report(rows_by, stats, ci_seed=62000)
        report["totals"] = {
            "attack_surfaced": sum(r.is_attack and _surfaced(r) for rows in rows_by.values() for r in rows),
            "normal_surfaced": sum(not r.is_attack and _surfaced(r) for rows in rows_by.values() for r in rows),
        }
        if arm in ("C", "D", "E", "G"):
            counterfactual = Counter()
            for rows in rows_by.values():
                for row in rows:
                    before = row.decision_without_l3 in ("warn", "challenge", "block")
                    after = _surfaced(row)
                    kind = "attack" if row.is_attack else "normal"
                    if after and not before:
                        counterfactual[f"unique_{kind}_surfaced"] += 1
                    elif before and not after:
                        counterfactual[f"lost_{kind}_surfaced"] += 1
            report["same_threshold_l3_contribution"] = dict(counterfactual)
        result["arms"][arm] = report
        print(f"tuning arm={arm}", flush=True)
    if thresholds["L1"] is None and thresholds["B"] is not None:
        # Explain the otherwise missing L1 row; B's threshold does not certify L1.
        diagnostic = [
            r for seed in SEEDS
            for r in V5.TU.resolve_rows(tuning["L1"][seed], thresholds["B"])
        ]
        summary = V5.V1.M.summarize(diagnostic)
        result["l1_at_baseline_threshold_diagnostic"] = {
            "status": "not_calibrated_for_L1_not_gate_eligible",
            "recall": summary.recall, "precision": summary.precision,
            "warn_fpr": summary.warn_fpr, "challenge_fpr": summary.challenge_fpr,
            "block_fpr": summary.block_fpr,
        }
    if "B" in outcomes:
        for arm in ("C", "D", "E", "G"):
            if arm not in outcomes:
                continue
            delta = Counter()
            for seed in SEEDS:
                base, with_l3 = outcomes["B"][seed], outcomes[arm][seed]
                if len(base) != len(with_l3):
                    raise ValueError("arm event counts differ")
                for prior, current in zip(base, with_l3):
                    if (prior.user, prior.family, prior.is_attack) != (
                        current.user, current.family, current.is_attack
                    ):
                        raise ValueError("arm event order differs")
                    kind = "attack" if current.is_attack else "normal"
                    if not _surfaced(prior) and _surfaced(current):
                        delta[f"new_{kind}_surfaced"] += 1
                    if _surfaced(prior) and not _surfaced(current):
                        delta[f"lost_{kind}_surfaced"] += 1
            result["l3_vs_baseline"][arm] = dict(delta)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--frozen", type=Path, required=True)
    parser.add_argument("--out-json", type=Path, required=True)
    args = parser.parse_args()
    run(args.artifact_dir, args.frozen, args.out_json)


if __name__ == "__main__":
    main()
