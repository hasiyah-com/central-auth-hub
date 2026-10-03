import hashlib
from types import SimpleNamespace
import pytest

from app import model as M


def test_fingerprint_is_bound_to_bytes_actually_loaded(tmp_path, monkeypatch):
    path = tmp_path / "model.pkl"
    path.write_bytes(b"model version one")
    monkeypatch.setattr(M, "MODEL_PATH", path)
    monkeypatch.setattr(M, "_model", None)
    monkeypatch.setattr(M, "_model_sha256", None)
    candidate = SimpleNamespace(rba_feature_contract_=M.FEATURE_CONTRACT)
    monkeypatch.setattr(M.joblib, "load", lambda stream: candidate)
    assert M.load_model() is candidate
    path.write_bytes(b"version two")
    assert M.model_sha256() == hashlib.sha256(b"model version one").hexdigest()
    assert M.load_model() is candidate


def test_legacy_model_rejected_without_polluting_cache(tmp_path, monkeypatch):
    path = tmp_path / "legacy.pkl"
    path.write_bytes(b"old model")
    monkeypatch.setattr(M, "MODEL_PATH", path)
    monkeypatch.setattr(M, "_model", None)
    monkeypatch.setattr(M, "_model_sha256", None)
    monkeypatch.setattr(M.joblib, "load", lambda stream: SimpleNamespace())
    with pytest.raises(M.FeatureContractMismatch):
        M.load_model()
    assert M._model is None and M.model_sha256() is None
