"""Population tuning uses the production resolver and never opens final holdout."""

import math
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "ml-service" / "scripts"))
sys.path.insert(0, str(ROOT / "hub" / "backend"))

from hybrid_experiment import population_tuning as P


def test_requires_twenty_distinct_validation_populations():
    with pytest.raises(ValueError, match="20"):
        P.validate_seeds(list(range(5)), reserved=())
    with pytest.raises(ValueError, match="duplicate"):
        P.validate_seeds([1] * 20, reserved=())


def test_reserved_seeds_are_rejected_before_loading_data():
    with pytest.raises(ValueError, match="reserved"):
        P.validate_seeds(list(range(190, 210)), reserved=range(201, 206))


def test_population_tail_is_not_hidden_by_pooled_events():
    groups = {(seed, 50): [0.1] * 100 for seed in range(20)}
    groups[(0, 50)] = [0.9] * 10
    thresholds = P.threshold_candidates(groups, n_points=3)
    assert any(t["challenge"] > 0.9 for t in thresholds)


def test_threshold_boundary_preserves_inclusive_production_comparison():
    groups = {(seed, 50): [0.8] * 100 for seed in range(20)}
    assert all(
        t["challenge"] == math.nextafter(0.8, math.inf)
        for t in P.threshold_candidates(groups, n_points=3)
    )


@pytest.mark.parametrize("bad", [[], [float("nan")], [float("inf")], [-0.1], [1.1]])
def test_invalid_normal_scores_fail_closed(bad):
    with pytest.raises(ValueError):
        P.threshold_candidates({(0, 50): bad})


def test_saturated_scores_are_evaluated_at_deployable_ceiling():
    groups = {(seed, 50): [1.0] * 100 for seed in range(20)}
    assert P.threshold_candidates(groups, n_points=3) == [
        {"warn": 1.0, "challenge": 1.0, "block": 1.0}
    ]


def test_macro_pass_does_not_hide_one_population_failure():
    from hybrid_experiment.tune import CellStat

    cells = [
        CellStat(
            seed=s,
            size=50,
            per_user_challenge_fpr={"u": 0.02 if s == 0 else 0.0},
            per_user_warn_fpr={"u": 0.0},
            per_user_block_fpr={"u": 0.0},
        )
        for s in range(20)
    ]
    report = P.population_report(cells)
    assert not report["eligible"]
    assert report["per_size"]["50"]["challenge_fpr"]["worst"] == 0.02
    assert "seed0_size50_challenge_fpr" in report["violations"]


def test_incomplete_population_size_grid_is_refused():
    with pytest.raises(ValueError, match="grid"):
        P.validate_grid({(s, 50): [] for s in range(20)} | {(0, 500): []})


def test_search_keeps_policy_floor_and_reports_no_candidate():
    from app.security.risk_fusion import ResolverInput
    from hybrid_experiment.tune import EventRecord

    record = EventRecord(
        user="u",
        is_attack=False,
        family=None,
        campaign=None,
        resolver=ResolverInput(0.2, policy_min_action="challenge"),
    )
    attack = EventRecord(
        user="u",
        is_attack=True,
        family=None,
        campaign=None,
        resolver=ResolverInput(0.9),
    )
    records = {(s, 50): [record, attack] for s in range(20)}
    result = P.search(records, gamma=1.0, n_points=3)
    assert result["best"] is None
    assert result["status"] == "validation_failed"
    assert result["policy_floor"]["per_size"]["50"]["challenge_fpr"]["worst"] == 1.0


def test_search_uses_real_resolver_and_reports_enforcement_recall():
    from app.security.risk_fusion import ResolverInput
    from hybrid_experiment.tune import EventRecord

    rows = [
        EventRecord(
            user="u",
            is_attack=attack,
            family=None,
            campaign=None,
            resolver=ResolverInput(score),
        )
        for attack, score in [(False, 0.1), (True, 0.9)]
    ]
    result = P.search({(s, 50): rows for s in range(20)}, gamma=1.0, n_points=3)
    assert result["status"] == "validation_candidate"
    assert result["best"]["metrics"]["recall_challenge"] == 1.0
    assert result["best"]["population"]["eligible"]
    assert result["deploy_ready"] is False


def test_cli_refuses_holdout_before_cache_load(tmp_path, monkeypatch):
    gate = pytest.importorskip(
        "exp_hybrid_gate", reason="ML harness dependencies required"
    )

    def forbidden(*args):
        raise AssertionError("must reject holdout before reading cache")

    monkeypatch.setattr(gate, "load_cell", forbidden)
    args = SimpleNamespace(
        seeds=list(range(101, 121)), sizes=[50], output=tmp_path / "report.json"
    )
    with pytest.raises(ValueError, match="reserved"):
        gate.cmd_tune_population(args)
    assert not args.output.exists()


def test_cli_missing_validation_data_does_not_generate_or_open_holdout(
    tmp_path, monkeypatch
):
    gate = pytest.importorskip(
        "exp_hybrid_gate", reason="ML harness dependencies required"
    )

    monkeypatch.setattr(gate, "CELLS", tmp_path / "empty")
    args = SimpleNamespace(
        seeds=list(range(10001, 10021)),
        gamma=1.0,
        sizes=[50],
        output=tmp_path / "report.json",
    )
    assert gate.cmd_tune_population(args) == 1
    assert not args.output.exists()


def test_cli_writes_separate_report_with_fingerprints(tmp_path, monkeypatch):
    import json

    gate = pytest.importorskip(
        "exp_hybrid_gate", reason="ML harness dependencies required"
    )
    from app.security.risk_fusion import ResolverInput
    from hybrid_experiment.tune import EventRecord

    rows = [
        EventRecord(
            user="u",
            is_attack=attack,
            family=None,
            campaign=None,
            resolver=ResolverInput(score),
        )
        for attack, score in [(False, 0.1), (True, 0.9)]
    ]
    monkeypatch.setattr(gate, "CELLS", tmp_path)
    monkeypatch.setattr(
        gate,
        "load_cell",
        lambda s, n: {
            "seed": s,
            "size": n,
            "leakage": {"clean": True},
            "ctxs": [],
            "ecdf": None,
        },
    )
    monkeypatch.setattr(gate, "build_records", lambda *args: rows)
    monkeypatch.setattr(gate, "scoring_fingerprint", lambda: {"hash": "scoring"})
    monkeypatch.setattr(gate, "split_fingerprint", lambda *args: {"hash": "split"})
    args = SimpleNamespace(
        seeds=list(range(10001, 10021)),
        sizes=[50],
        config="B",
        gamma=1.0,
        output=tmp_path / "report.json",
    )
    for seed in args.seeds:
        (tmp_path / f"cell_s{seed}_n50.pkl").touch()
    assert gate.cmd_tune_population(args) == 0
    report = json.loads(args.output.read_text())
    assert report["split"] == "validation-tuning"
    assert report["scoring_fingerprint"] == {"hash": "scoring"}
    assert report["deploy_ready"] is False
    with pytest.raises(ValueError, match="already exists"):
        gate.cmd_tune_population(args)


def test_cli_corrupt_local_ledger_fails_closed(tmp_path, monkeypatch):
    import json

    gate = pytest.importorskip(
        "exp_hybrid_gate", reason="ML harness dependencies required"
    )
    ledger = tmp_path / "ledger.json"
    ledger.write_text("{broken")
    monkeypatch.setattr(gate, "HOLDOUT_LEDGER", ledger)
    args = SimpleNamespace(
        seeds=list(range(10001, 10021)),
        gamma=1.0,
        sizes=[50],
        output=tmp_path / "report.json",
    )
    with pytest.raises(json.JSONDecodeError):
        gate.cmd_tune_population(args)
    assert not args.output.exists()
