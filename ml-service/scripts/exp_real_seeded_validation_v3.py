"""V3 ablation + consensus validation with conditional one-shot holdout."""

from __future__ import annotations

import argparse
import gc
import json
import os
from pathlib import Path
import sys
import time

import joblib

ML = Path(__file__).resolve().parent
REPO = ML.parent.parent
for path in (ML, ML.parent, REPO / "hub" / "backend"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import exp_hybrid_gate as X  # noqa: E402
import exp_real_seeded_validation as V1E  # noqa: E402
import exp_real_seeded_validation_v2 as V2E  # noqa: E402
import gen_v3 as G3  # noqa: E402
from app.security.risk_fusion import DEFAULT_GAMMA  # noqa: E402
from hybrid_experiment import configs as CFG  # noqa: E402
from hybrid_experiment import dataset as DS  # noqa: E402
from hybrid_experiment import tune as TU  # noqa: E402

SEEDS = [721, 722, 723]
SIZES = [5, 10, 20, 50, 100, 200, 500, 1000, 2000]
CONFIGS = ("B", "C", "D", "E", "G")
L3_CONFIGS = ("C", "D", "E", "G")


def _write_verified_records(records, path: Path) -> None:
    """Write a cell atomically; never calibrate from a truncated pickle."""
    temporary = path.with_suffix(".tmp")
    try:
        joblib.dump(records, temporary, compress=0)
        restored = joblib.load(temporary)
        if len(restored) != len(records):
            raise ValueError(f"calibration cell count mismatch: {path.name}")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _valid_record(path: Path, expected_count: int = 16000) -> bool:
    if not path.is_file():
        return False
    try:
        return len(joblib.load(path)) == expected_count
    except Exception:
        return False


def _load_population(artifact: Path):
    profiles = json.loads((artifact / "population_spec.json").read_text(encoding="utf-8"))
    meta = json.loads((artifact / "population_summary.json").read_text(encoding="utf-8"))
    roster = json.loads(
        (artifact / "roster_real_seeded_v3.json").read_text(encoding="utf-8")
    )
    return profiles, meta, roster


def _generate_raw(artifact, profiles, roster, aliases, seeds):
    selected_profiles = [p for p in profiles if p["alias"] in aliases]
    selected_roster = {key: value for key, value in roster.items() if key in aliases}
    assert len(selected_profiles) == len(aliases)
    out = {}
    for seed in seeds:
        raw = G3.build_seed(
            artifact / "synthetic_users.xlsx",
            seed,
            spec=selected_profiles,
            roster=selected_roster,
        )
        assert set(raw) == aliases
        out[seed] = raw
    return out


def _calibration_phase(args, raw_cache) -> tuple[dict, dict]:
    record_root = args.work_dir / "calibration_records"
    for config in CONFIGS:
        (record_root / config).mkdir(parents=True, exist_ok=True)

    print("V3 CALIBRATION RECORDS: NORMAL-ONLY", flush=True)
    for seed in args.seeds:
        raw = raw_cache[seed]
        for size in args.sizes:
            paths = {
                config: record_root / config / f"{seed}_{size}.joblib"
                for config in CONFIGS
            }
            missing = [config for config, path in paths.items() if not _valid_record(path)]
            if not missing:
                print(f"cal seed={seed} size={size} verified cache", flush=True)
                continue
            started = time.perf_counter()
            splits = DS.build(args.artifact_dir / "synthetic_users.xlsx", seed, size, raw=raw)
            point, sequence, ecdf = X.fit_all(splits, size, raw)
            contexts = X.compute_layer_outputs(splits, point, sequence, "calib")
            assert all(not context.is_attack for context in contexts)
            for config in missing:
                records = X.build_records(
                    contexts, ecdf, CFG.CONFIGS[config], DEFAULT_GAMMA
                )
                _write_verified_records(records, paths[config])
            print(
                f"cal seed={seed} size={size} n={len(contexts)} "
                f"seconds={time.perf_counter() - started:.1f}",
                flush=True,
            )

    thresholds, details = {}, {}
    for config in CONFIGS:
        records_by_cell = {
            (seed, size): joblib.load(
                record_root / config / f"{seed}_{size}.joblib"
            )
            for seed in args.seeds
            for size in args.sizes
        }
        thresholds[config], details[config] = V2E.calibrate_thresholds(records_by_cell)
        print(f"calibrated {config}: {thresholds[config]}", flush=True)
        del records_by_cell
        gc.collect()
    return thresholds, details


def _validation_phase(args, raw_cache, thresholds):
    results = {config: {} for config in CONFIGS}
    leakage, shortcuts, parity = [], [], []
    for size in args.sizes:
        rows_by = {config: {} for config in CONFIGS if thresholds.get(config)}
        cells_by = {config: [] for config in CONFIGS if thresholds.get(config)}
        for seed in args.seeds:
            started = time.perf_counter()
            raw = raw_cache[seed]
            splits = DS.build(args.artifact_dir / "synthetic_users.xlsx", seed, size, raw=raw)
            leak = DS.check_leakage(splits)
            leakage.append({"seed": seed, "size": size, **leak})
            attack = [v for user in splits.values() for _, v in user.tune_attacks]
            normal = [v for user in splits.values() for v in user.tune_normal_ft]
            shortcut = DS.check_shortcut(attack, normal, V1E.FEATURE_NAMES)
            shortcuts.append({"seed": seed, "size": size, "findings": shortcut})
            point, sequence, ecdf = X.fit_all(splits, size, raw)
            parity.append(V1E._model_parity(point, normal, args.artifact_dir))
            contexts = X.compute_layer_outputs(splits, point, sequence, "tune")
            for config in rows_by:
                rows = X.apply_config(
                    contexts,
                    CFG.CONFIGS[config],
                    ecdf,
                    DEFAULT_GAMMA,
                    thresholds[config],
                )
                rows_by[config][seed] = rows
                cells_by[config].append(TU.cell_stat(seed, size, rows))
            print(
                f"tune seed={seed} size={size} seconds={time.perf_counter() - started:.1f}",
                flush=True,
            )
        for config in CONFIGS:
            if config in rows_by:
                results[config][str(size)] = V1E._history_report(
                    rows_by[config], cells_by[config], ci_seed=37000 + size
                )
            else:
                results[config][str(size)] = {
                    "history_gate_passed": False,
                    "calibration_infeasible": True,
                }
        del rows_by, cells_by
        gc.collect()
    return results, leakage, shortcuts, parity


def _select_candidate(results: dict, sizes: list[int], global_gates: bool):
    if not global_gates:
        return None
    choices = []
    for config in L3_CONFIGS:
        for size in sizes:
            row = results[config][str(size)]
            if row.get("history_gate_passed"):
                summary = row["summary"]
                choices.append(
                    (
                        size,
                        -summary["precision"],
                        summary["challenge_fpr"],
                        config,
                    )
                )
                break
    if not choices:
        return None
    size, neg_precision, challenge_fpr, config = min(choices)
    return {
        "config": config,
        "history": size,
        "precision": -neg_precision,
        "challenge_fpr": challenge_fpr,
        "selection_order": [
            "minimum_history",
            "maximum_precision",
            "minimum_challenge_fpr",
            "config_key",
        ],
    }


def _full_protocol(args) -> bool:
    """A smoke/subset run must never select a candidate or open holdout."""
    return args.seeds == SEEDS and args.sizes == SIZES


def _holdout_ratio(raw_cache: dict) -> dict:
    normal = sum(len(user["test"]) for raw in raw_cache.values() for user in raw.values())
    attack = sum(
        len(user["final_attacks"]) for raw in raw_cache.values() for user in raw.values()
    )
    ratio = attack / max(normal + attack, 1)
    return {"normal": normal, "anomaly": attack, "anomaly_ratio": ratio, "passed": ratio <= 0.07}


def _holdout_phase(args, raw_cache, selection, thresholds):
    config = selection["config"]
    size = selection["history"]
    rows_by_seed, cells, leakage, shortcuts, parity = {}, [], [], [], []
    for seed in args.seeds:
        raw = raw_cache[seed]
        splits = DS.build(args.artifact_dir / "synthetic_users.xlsx", seed, size, raw=raw)
        leak = DS.check_leakage(splits)
        leakage.append({"seed": seed, **leak})
        normal = [v for user in splits.values() for _, v in user.holdout_normal]
        attack = [v for user in splits.values() for _, v in user.holdout_attacks]
        shortcuts.append(
            {
                "seed": seed,
                "findings": DS.check_shortcut(attack, normal, V1E.FEATURE_NAMES),
            }
        )
        point, sequence, ecdf = X.fit_all(splits, size, raw)
        parity.append(V1E._model_parity(point, normal, args.artifact_dir))
        contexts = X.compute_layer_outputs(splits, point, sequence, "holdout")
        rows = X.apply_config(
            contexts,
            CFG.CONFIGS[config],
            ecdf,
            DEFAULT_GAMMA,
            thresholds[config],
        )
        rows_by_seed[seed] = rows
        cells.append(TU.cell_stat(seed, size, rows))
        print(f"holdout seed={seed} size={size} config={config}", flush=True)
    report = V1E._history_report(rows_by_seed, cells, ci_seed=47000 + size)
    ratio = _holdout_ratio(raw_cache)
    auxiliary_passed = (
        all(x["clean"] for x in leakage)
        and all(not x["findings"] for x in shortcuts)
        and max(parity, default=0.0) <= 1e-12
        and ratio["passed"]
    )
    return {
        **report,
        "ratio": ratio,
        "leakage_passed": all(x["clean"] for x in leakage),
        "shortcut_passed": all(not x["findings"] for x in shortcuts),
        "model_parity_max_abs_error": max(parity, default=0.0),
        "auxiliary_passed": auxiliary_passed,
        "holdout_gate_passed": report["history_gate_passed"] and auxiliary_passed,
    }


def _markdown(result: dict) -> str:
    lines = [
        "# Real-seeded login-risk validation V3",
        "",
        f"สถานะรวม: **{result['status']}**",
        "",
        "| Config | จุดผ่าน Validation ต่ำสุด | Holdout |",
        "|---|---:|:---:|",
    ]
    selected = result.get("selection") or {}
    for config in L3_CONFIGS:
        passed = [
            size
            for size in result["sizes"]
            if result["results"][config][str(size)].get("history_gate_passed")
        ]
        hold = selected.get("config") == config and result.get("holdout")
        lines.append(
            f"| {config}: {CFG.CONFIGS[config].name} | "
            f"{min(passed) if passed else 'ไม่ผ่าน'} | "
            f"{'ผ่าน' if hold and result['holdout']['holdout_gate_passed'] else ('ไม่ผ่าน' if hold else 'ไม่เปิด')} |"
        )
    selection = result.get("selection")
    lines += ["", "## ข้อสรุป", ""]
    if selection:
        lines.append(
            f"เลือก Config {selection['config']} ที่ history {selection['history']:,}; "
            f"Holdout {'ผ่าน' if result['holdout']['holdout_gate_passed'] else 'ไม่ผ่าน'}"
        )
    else:
        lines.append("ไม่มี L3 candidate ผ่าน Validation ครบทุก gate; Holdout ยังปิด")
    lines += [
        "",
        f"- Anomaly ratio สูงสุดใน Tuning: {result['max_anomaly_ratio']:.3%}",
        f"- Feature contract: {'ผ่าน' if result['feature_contract_passed'] else 'ไม่ผ่าน'}",
        f"- Model/service parity max error: {result['model_parity_max_abs_error']:.3g}",
        "- Production policy/model: ยังไม่เปลี่ยน",
        "",
    ]
    if 2000 in result["sizes"]:
        lines += [
            "## ผลที่ history 2,000 (Validation เท่านั้น)",
            "",
            "| Config | Recall | Precision | Campaign | New passkey | Rare device | ผ่านทุก gate |",
            "|---|---:|---:|---:|---:|---:|:---:|",
        ]
        for config in CONFIGS:
            row = result["results"][config]["2000"]
            summary = row.get("summary")
            if not summary:
                continue
            family = summary["per_family"]
            lines.append(
                f"| {config} | {summary['recall']:.1%} | {summary['precision']:.1%} | "
                f"{family['campaign']['recall']:.1%} | "
                f"{family['new_passkey']['recall']:.1%} | "
                f"{family['subtle_rare_device']['recall']:.1%} | "
                f"{'ผ่าน' if row['history_gate_passed'] else 'ไม่ผ่าน'} |"
            )
        lines += [
            "",
            "เกณฑ์: recall ≥70%, precision ≥70%, ทุก attack family recall ≥50%, "
            "FPR CI และทุก seed ต้องผ่านพร้อมกัน",
            "",
        ]
    return "\n".join(lines)


def run(args) -> int:
    args.work_dir.mkdir(parents=True, exist_ok=True)
    profiles, meta, roster = _load_population(args.artifact_dir)
    validation = set(meta["split"]["validation"])
    holdout = set(meta["split"]["holdout"])
    assert len(validation) == 32 and len(holdout) == 16 and not (validation & holdout)

    raw_cache = _generate_raw(
        args.artifact_dir, profiles, roster, validation, args.seeds
    )
    contracts, ratios = [], []
    for seed, raw in raw_cache.items():
        V1E._trim_dev_attacks(raw)
        contract = V1E._feature_contract(raw)
        ratio = V1E._attack_ratio(raw)
        assert contract["passed"], contract
        assert ratio["passed"], ratio
        contracts.append(contract)
        ratios.append(ratio)

    thresholds, calibration = _calibration_phase(args, raw_cache)
    frozen = {
        "experiment": "real_seeded_population_v3",
        "normal_only": True,
        "configs": list(CONFIGS),
        "gamma": DEFAULT_GAMMA,
        "seeds": args.seeds,
        "sizes": args.sizes,
        "targets": V2E.CAL_TARGETS,
        "thresholds": thresholds,
        "calibration": calibration,
        "population_spec_sha256": V2E._sha256(
            args.artifact_dir / "population_spec.json"
        ),
        "config_source_sha256": V2E._sha256(Path(CFG.__file__)),
        "generator_source_sha256": V2E._sha256(Path(G3.__file__)),
    }
    args.frozen_thresholds.parent.mkdir(parents=True, exist_ok=True)
    args.frozen_thresholds.write_text(
        json.dumps(frozen, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print("V3 THRESHOLDS FROZEN BEFORE TUNING", flush=True)

    results, leakage, shortcuts, parity = _validation_phase(
        args, raw_cache, thresholds
    )
    shortcut_passed = all(not row["findings"] for row in shortcuts)
    parity_error = max(parity, default=0.0)
    global_gates = (
        all(row["passed"] for row in contracts)
        and all(row["clean"] for row in leakage)
        and shortcut_passed
        and parity_error <= 1e-12
    )
    selection = _select_candidate(results, args.sizes, global_gates and _full_protocol(args))
    selection_artifact = {
        "experiment": "real_seeded_population_v3",
        "selection": selection,
        "holdout_open_authorized_by_prereg": bool(selection),
        "thresholds_sha256": V2E._sha256(args.frozen_thresholds),
    }
    args.selection_freeze.parent.mkdir(parents=True, exist_ok=True)
    args.selection_freeze.write_text(
        json.dumps(selection_artifact, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    holdout_report = None
    if selection:
        print(f"SELECTION FROZEN {selection}; OPENING V3 HOLDOUT ONCE", flush=True)
        del raw_cache
        gc.collect()
        holdout_raw = _generate_raw(
            args.artifact_dir, profiles, roster, holdout, args.seeds
        )
        assert all(set(raw) == holdout for raw in holdout_raw.values())
        holdout_report = _holdout_phase(args, holdout_raw, selection, thresholds)
    else:
        print("NO VALIDATION-PASSING L3 CANDIDATE; HOLDOUT CLOSED", flush=True)

    status = (
        "synthetic_holdout_passed_shadow_blocked_by_capacity"
        if holdout_report and holdout_report["holdout_gate_passed"]
        else (
            "holdout_failed_production_closed"
            if holdout_report
            else "validation_failed_holdout_closed"
        )
    )
    result = {
        "experiment": "real_seeded_population_v3_validation",
        "status": status,
        "holdout_opened": bool(holdout_report),
        "validation_profiles": 32,
        "holdout_profiles": 16,
        "seeds": args.seeds,
        "sizes": args.sizes,
        "configs": {key: CFG.CONFIGS[key].name for key in CONFIGS},
        "gamma": DEFAULT_GAMMA,
        "thresholds": thresholds,
        "calibration": calibration,
        "normal_only_train_calibration": True,
        "max_anomaly_ratio": max(x["anomaly_ratio"] for x in ratios),
        "feature_contract_passed": all(x["passed"] for x in contracts),
        "leakage_passed": all(x["clean"] for x in leakage),
        "shortcut_passed": shortcut_passed,
        "shortcut_findings": shortcuts if not shortcut_passed else [],
        "model_parity_max_abs_error": parity_error,
        "model_parity_passed": parity_error <= 1e-12,
        "selection": selection,
        "holdout": holdout_report,
        "results": results,
        "production_changed": False,
        "capacity_gate_latest": "failed",
    }
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    args.out_md.write_text(_markdown(result), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": status,
                "selection": selection,
                "holdout_opened": bool(holdout_report),
                "holdout_passed": bool(
                    holdout_report and holdout_report["holdout_gate_passed"]
                ),
            },
            ensure_ascii=False,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--seeds", nargs="+", type=int, default=SEEDS)
    parser.add_argument("--sizes", nargs="+", type=int, default=SIZES)
    parser.add_argument("--frozen-thresholds", type=Path, required=True)
    parser.add_argument("--selection-freeze", type=Path, required=True)
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--out-md", type=Path, required=True)
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
