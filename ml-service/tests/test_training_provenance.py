import csv
import hashlib
import json

from app.features import FEATURE_CONTRACT, FEATURE_NAMES
from scripts import train_model


def test_provenance_is_the_metadata_validated_when_samples_are_read(tmp_path, monkeypatch):
    path = tmp_path / 'samples.csv'
    with path.open('w', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(FEATURE_NAMES + ['label'])
        writer.writerow([0.] * 23 + [0])
    meta = dict(feature_contract=FEATURE_CONTRACT, timezone='Asia/Bangkok',
        dataset_sha256=hashlib.sha256(path.read_bytes()).hexdigest(), country_count_mode='distinct-v1')
    sidecar = path.with_suffix('.csv.meta.json')
    sidecar.write_text(json.dumps(meta))
    monkeypatch.setattr(train_model, 'DATA_PATH', path)
    monkeypatch.setattr(train_model, 'REAL_DATA_PATH', tmp_path / 'no_real.csv')
    X, y, provenance = train_model.load_data(include_provenance=True)
    meta['country_count_mode'] = 'replaced_after_read'
    sidecar.write_text(json.dumps(meta))
    assert X.shape == (1, 23)
    assert provenance['synthetic']['country_count_mode'] == 'distinct-v1'
    assert provenance['real_labeled'] is None
