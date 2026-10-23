import hashlib
import io
import json
from scripts import inspect_running_point as probe


def test_live_worker_identity_is_not_guessed_from_the_disk(tmp_path, monkeypatch):
    artifact = tmp_path / 'model.pkl'
    artifact.write_bytes(b'new on disk')
    response = {'meta': {'model_sha256': 'old-loaded-model', 'feature_contract': 'rba-23-bangkok-v1'},
                'data': {'anomaly_score': .49, 'explanation': []}}
    calls = []
    def send(request, timeout):
        calls.append(request)
        return io.BytesIO(json.dumps(response).encode())
    monkeypatch.setattr(probe, 'urlopen', send)
    result = probe.inspect('http://127.0.0.1:9000', artifact, attempts=1)
    assert result['on_disk_sha256'] == hashlib.sha256(b'new on disk').hexdigest()
    assert result['attempts'][0]['loaded_worker_sha256'] == 'old-loaded-model'
    assert result['attempts'][0]['disk_matches_worker'] is False
    assert calls[0].full_url.endswith('/v1/score')
    assert set(json.loads(calls[0].data)) == {'features', 'feature_contract'}


def test_old_api_missing_fingerprint_remains_unknown(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, 'urlopen', lambda *a, **kw: io.BytesIO(b'{"data": {}}'))
    result = probe.inspect('http://127.0.0.1:9000', tmp_path / 'absent', attempts=1)
    assert result['attempts'][0]['disk_matches_worker'] is None
