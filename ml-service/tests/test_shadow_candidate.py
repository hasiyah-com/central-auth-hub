import hashlib, json, copy
from pathlib import Path
import joblib, numpy as np, pytest
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import IsolationForest
from app.features import FEATURE_NAMES, FEATURE_CONTRACT
from app.shadow_candidate import Candidate, CandidateError


@pytest.fixture
def bundle(tmp_path):
    model = make_pipeline(
        StandardScaler(),
        IsolationForest(n_estimators=10, max_samples=32, random_state=42),
    ).fit(np.random.default_rng(42).normal(size=(80, 23)))
    artifact = tmp_path / "candidate.joblib"
    joblib.dump(model, artifact)
    manifest = {
        "version": "if-candidate-shadow-v1",
        "mode": "shadow",
        "input_contract": FEATURE_CONTRACT,
        "training_semantics": "offline-r79-mirror-not-live-certified",
        "features": FEATURE_NAMES,
        "artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        "sklearn_version": "1.5.2",
        "raw_threshold": 0.0918450679660674,
        "score_transform": "sigmoid_5_negative_decision",
        "source_provenance": {
            "experiment": "NF frozen IF-mixed5",
            "model_selection": "diagnostic_only",
        },
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    return model, artifact, path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_real_scaled_forest_returns23_and_same_score(bundle):
    model, artifact, path, digest = bundle
    c = Candidate.load(artifact, path, digest)
    v = [12, 1, 1, 1, 0, 1, 0, 0, 5, 1, 0, 1, 100, 0, 1, 0, 0, 0.8, 0.8, 0, 365, 0, 0]
    before = copy.deepcopy(v)
    out = c.evaluate(v)
    assert v == before and out["applied_to_access"] is False and out["mode"] == "shadow"
    assert out["raw_score"] == pytest.approx(
        -model.decision_function([v])[0], abs=1e-12
    )
    assert out["score"] == pytest.approx(
        1 / (1 + np.exp(5 * model.decision_function([v])[0])), abs=1e-12
    )
    assert len(out["explanation"]) == 23 and {
        e["feature"] for e in out["explanation"]
    } == set(FEATURE_NAMES)
    assert all(
        e["value"] == v[FEATURE_NAMES.index(e["feature"])] for e in out["explanation"]
    )
    assert "decision" not in out and "access_decision" not in out


def test_missing_artifact_fails_closed(bundle):
    _, a, p, d = bundle
    a.unlink()
    with pytest.raises(CandidateError):
        Candidate.load(a, p, d)


def test_bad_manifest_digest_rejected_before_unpickle(bundle, monkeypatch):
    _, a, p, d = bundle
    monkeypatch.setattr(joblib, "load", lambda *a: pytest.fail("must not unpickle"))
    with pytest.raises(CandidateError):
        Candidate.load(a, p, "0" * 64)


def test_bad_artifact_digest_rejected_before_unpickle(bundle, monkeypatch):
    _, a, p, d = bundle
    a.write_bytes(b"wrong")
    monkeypatch.setattr(joblib, "load", lambda *a: pytest.fail("must not unpickle"))
    with pytest.raises(CandidateError):
        Candidate.load(a, p, d)


@pytest.mark.parametrize(
    "field,value",
    [
        ("features", list(reversed(FEATURE_NAMES))),
        ("input_contract", "wrong"),
        ("mode", "enforce"),
        ("sklearn_version", "0"),
        ("raw_threshold", float("nan")),
        ("training_semantics", ""),
        ("source_provenance", {}),
    ],
)
def test_bad_metadata(bundle, field, value):
    _, a, p, d = bundle
    m = json.loads(p.read_text())
    m[field] = value
    p.write_text(json.dumps(m))
    with pytest.raises(CandidateError):
        Candidate.load(a, p, hashlib.sha256(p.read_bytes()).hexdigest())


@pytest.mark.parametrize(
    "v", [[0.0] * 22, [float("nan")] * 23, [float("inf")] * 23, [99.0] * 23]
)
def test_invalid_vectors(bundle, v):
    _, a, p, d = bundle
    c = Candidate.load(a, p, d)
    with pytest.raises(CandidateError):
        c.evaluate(v)


def test_shap_failure_keeps_score_and_reports_unavailable(bundle):
    _, a, p, d = bundle
    c = Candidate.load(a, p, d)

    class Broken:
        def shap_values(self, *a):
            raise RuntimeError("failure")

    c.explainer = Broken()
    r = c.evaluate([0.0] * 23)
    assert (
        r["status"] == "degraded_shap"
        and r["explanation"] == []
        and np.isfinite(r["score"])
    )


def test_load_failure_cannot_pollute_live_model_cache(bundle):
    from app import model as live

    before = (live._model, live._model_sha256, live._explainer, live.MODEL_PATH)
    _, a, p, d = bundle
    Candidate.load(a, p, d)
    assert before == (live._model, live._model_sha256, live._explainer, live.MODEL_PATH)
