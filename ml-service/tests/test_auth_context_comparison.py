import hashlib
import json

import numpy as np
import pytest

from app.features import FEATURE_NAMES, FEATURE_RANGES, FEATURE_CONTRACT
from scripts.compare_auth_context import (
    CONTEXT_NAMES, CONTEXT_CONTRACT, read_dataset, split_users, compare,
)


def dataset(tmp_path):
    rows = []
    rng = np.random.default_rng(42)
    for user in range(30):
        for event in range(10):
            values = {name: float(rng.uniform(*FEATURE_RANGES[name])) for name in FEATURE_NAMES}
            values.update({name: 0.0 for name in CONTEXT_NAMES})
            values["auth_method_known"] = 1.0
            if event >= 8:
                values["recovery_observed"] = 1.0
                values["auth_method_departure"] = 1.0
            rows.append({"subject": str(user), "session": f"{user}-{event}",
                         "captured_at": "2026-10-03T09:00:00Z", "features": values,
                         "label": int(event >= 8)})
    path = tmp_path / "fixture.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    meta = {"contract": CONTEXT_CONTRACT, "base_feature_contract": FEATURE_CONTRACT,
            "feature_names": FEATURE_NAMES + CONTEXT_NAMES,
            "dataset_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "source": "synthetic_unit_test_only"}
    path.with_suffix(".jsonl.meta.json").write_text(json.dumps(meta))
    return path


def test_user_holdouts_are_disjoint_and_cover_all_rows(tmp_path):
    rows, _, _, _ = read_dataset(dataset(tmp_path))
    splits = split_users(rows)
    users = [{rows[i]["subject"] for i in split} for split in splits]
    assert not users[0] & users[1] and not users[1] & users[2] and not users[0] & users[2]
    assert sum(len(split) for split in splits) == len(rows)


def test_corrupted_checksum_fails_before_training(tmp_path):
    path = dataset(tmp_path)
    path.write_text(path.read_text() + "\n")
    with pytest.raises(ValueError, match="checksum"):
        read_dataset(path)


def test_paired_comparison_stages_both_models_without_live_replacement(tmp_path):
    output = tmp_path / "candidate"
    report = compare(dataset(tmp_path), output)
    assert set(report["results"]) == {"baseline_23", "candidate_38"}
    assert report["activation"].startswith("offline_only")
    assert (output / "candidate_38.candidate.pkl").exists()
    assert not (output / "iforest.pkl").exists()
    for result in report["results"].values():
        assert 0 <= result["test"]["roc_auc"] <= 1


def test_existing_v1_dataset_remains_readable_without_fabricated_new_features(tmp_path):
    path = dataset(tmp_path)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    names = FEATURE_NAMES + CONTEXT_NAMES[:9]
    for row in rows:
        row["features"] = {n: row["features"][n] for n in names}
    path.write_text("".join(json.dumps(r)+"\n" for r in rows))
    meta_path = path.with_suffix(".jsonl.meta.json")
    meta = json.loads(meta_path.read_text())
    meta.update(contract="l3-auth-context-v1", feature_names=names,
                dataset_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    meta_path.write_text(json.dumps(meta))
    _, X, _, _ = read_dataset(path)
    assert X.shape[1] == 32
