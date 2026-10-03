from datetime import datetime, timedelta
import hashlib
import json
import numpy as np
import pytest

from scripts.train_post_auth_candidate import CONTRACT, FEATURE_NAMES, read_dataset, train


def dataset(tmp_path, labeled=True):
    rows = []
    for user in range(30):
        for event in range(10):
            values = [1, float(np.log1p(10 if event < 8 else 900)), float(np.log1p(3)),
                      .2 if event < 8 else .9, .01 if event < 8 else .8, float(np.log1p(5))]
            start = datetime(2026, 10, 3, 9)+timedelta(minutes=5*event)
            rows.append({"subject": str(user), "window": f"{user}-{event}",
                         "from": start.isoformat()+"Z", "to": (start+timedelta(minutes=5)).isoformat()+"Z",
                         "features": dict(zip(FEATURE_NAMES, values)),
                         "label": int(event >= 8) if labeled else None})
    path = tmp_path/"post.jsonl"
    path.write_text("".join(json.dumps(r)+"\n" for r in rows))
    meta = {"contract": CONTRACT, "feature_names": FEATURE_NAMES,
            "source": "synthetic_unit_test_only",
            "dataset_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    path.with_suffix(".jsonl.meta.json").write_text(json.dumps(meta))
    return path


def test_post_windows_require_independent_labels(tmp_path):
    with pytest.raises(ValueError, match="independent window labels"):
        read_dataset(dataset(tmp_path, labeled=False))


def test_post_candidate_is_separate_from_login_model(tmp_path):
    output = tmp_path/"candidate"
    report = train(dataset(tmp_path), output)
    assert report["activation"].startswith("offline_only")
    assert (output/"post_auth.candidate.pkl").exists()
    assert not (output/"iforest.pkl").exists()
    assert 0 <= report["test"]["roc_auc"] <= 1


def test_modified_post_data_requires_new_checksum(tmp_path):
    path = dataset(tmp_path)
    path.write_text(path.read_text()+"\n")
    with pytest.raises(ValueError, match="checksum"):
        read_dataset(path)
