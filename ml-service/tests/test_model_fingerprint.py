import hashlib

from app import model as M


def test_fingerprint_is_bound_to_bytes_actually_loaded(tmp_path, monkeypatch):
    path = tmp_path / "model.pkl"
    path.write_bytes(b"model version one")
    monkeypatch.setattr(M, "MODEL_PATH", path)
    monkeypatch.setattr(M, "_model", None)
    monkeypatch.setattr(M, "_model_sha256", None)
    monkeypatch.setattr(M.joblib, "load", lambda stream: stream.read())
    assert M.load_model() == b"model version one"
    path.write_bytes(b"version two")
    assert M.model_sha256() == hashlib.sha256(b"model version one").hexdigest()
    assert M.load_model() == b"model version one"
