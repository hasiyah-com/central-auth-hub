import csv
import hashlib
import json

import pytest
from app.features import FEATURE_NAMES, FEATURE_CONTRACT
from scripts.train_bangkok_model import read_dataset


def test_training_rejects_legacy_or_tampered_data(tmp_path):
    path = tmp_path / "sessions.csv"
    values = [0.] * 23
    with path.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(FEATURE_NAMES + ["label"])
        writer.writerow(values + [0])
    meta_path = path.with_suffix(".csv.meta.json")
    meta = {"feature_contract": FEATURE_CONTRACT, "timezone": "Asia/Bangkok",
        "dataset_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    meta_path.write_text(json.dumps(meta))
    assert read_dataset(path)[0].shape == (1, 23)
    meta["timezone"] = "UTC"
    meta_path.write_text(json.dumps(meta))
    with pytest.raises(ValueError, match="mismatch"):
        read_dataset(path)
    meta["timezone"] = "Asia/Bangkok"
    meta_path.write_text(json.dumps(meta))
    path.write_text(path.read_text() + "\n")
    with pytest.raises(ValueError, match="checksum"):
        read_dataset(path)
