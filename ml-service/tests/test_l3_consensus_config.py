from __future__ import annotations

import sys
from argparse import Namespace
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
BACKEND = Path(__file__).resolve().parents[2] / "hub" / "backend"
for path in (SCRIPTS, BACKEND):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from hybrid_experiment import configs as CFG  # noqa: E402
import exp_real_seeded_validation_v3 as V3  # noqa: E402


def _identity(layer, raw):
    return raw


def test_consensus_uses_weaker_of_point_and_sequence():
    evidence = CFG._anomaly_evidence(
        CFG.L3Scores(point_raw=0.92, sequence_raw=0.81, sequence_eligible=True),
        (CFG.VIEW_CONSENSUS,),
        _identity,
    )
    assert not evidence.abstained
    assert evidence.evidence_score == 0.81
    assert evidence.detail["view"] == "consensus"
    assert evidence.detail["limiting_view"] == "sequence"


def test_consensus_abstains_when_either_view_is_missing():
    evidence = CFG._anomaly_evidence(
        CFG.L3Scores(point_raw=0.92, sequence_raw=None, sequence_eligible=False),
        (CFG.VIEW_CONSENSUS,),
        _identity,
    )
    assert evidence.abstained
    assert evidence.abstain_reason == "consensus_view_missing"


def test_v3_markdown_accepts_closed_holdout_without_selection():
    result = {
        "status": "validation_failed_holdout_closed",
        "selection": None,
        "holdout": None,
        "sizes": [20],
        "results": {
            key: {"20": {"history_gate_passed": False}} for key in V3.L3_CONFIGS
        },
        "max_anomaly_ratio": 0.065,
        "feature_contract_passed": True,
        "model_parity_max_abs_error": 0.0,
    }
    text = V3._markdown(result)
    assert "Holdout ยังปิด" in text


def test_subset_runs_cannot_select_or_open_holdout():
    assert V3._full_protocol(Namespace(seeds=V3.SEEDS, sizes=V3.SIZES))
    assert not V3._full_protocol(Namespace(seeds=V3.SEEDS[:1], sizes=V3.SIZES))
    assert not V3._full_protocol(Namespace(seeds=V3.SEEDS, sizes=V3.SIZES[:1]))
