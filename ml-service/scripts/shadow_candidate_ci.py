"""Disposable CI fixture/smoke only. Never prepares a production/research artifact."""

import argparse, hashlib, json, time, urllib.request, urllib.error
from pathlib import Path

TEST_KEY = "ci-candidate-fixture-only-not-for-production-0001"


def prepare(directory):
    import numpy as np, joblib, sklearn
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.ensemble import IsolationForest
    from app.features import FEATURE_NAMES, FEATURE_CONTRACT

    p = Path(directory)
    p.mkdir(parents=True, exist_ok=True)
    model = make_pipeline(
        StandardScaler(),
        IsolationForest(n_estimators=100, max_samples=128, random_state=42, n_jobs=1),
    ).fit(np.random.default_rng(42).normal(size=(256, 23)))
    joblib.dump(model, p / "IF-mixed5.joblib")
    m = dict(
        version="if-candidate-shadow-v1",
        mode="shadow",
        input_contract=FEATURE_CONTRACT,
        training_semantics="CI_SYNTHETIC_FIXTURE_ONLY_NOT_RESEARCH_OR_LIVE",
        features=FEATURE_NAMES,
        artifact_sha256=hashlib.sha256(
            (p / "IF-mixed5.joblib").read_bytes()
        ).hexdigest(),
        sklearn_version=sklearn.__version__,
        raw_threshold=0.0918450679660674,
        score_transform="sigmoid_5_negative_decision",
        source_provenance={
            "purpose": "disposable CI HTTP fixture, not model quality evidence"
        },
    )
    payload = (json.dumps(m, sort_keys=True) + "\n").encode()
    (p / "manifest.json").write_bytes(payload)
    (p / "manifest.sha256").write_text(hashlib.sha256(payload).hexdigest())


def probe(base):
    from app.features import FEATURE_CONTRACT

    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(base + "/health", timeout=2) as response:
                health = json.load(response)
            if health["status"] == "ready" and health["mode"] == "shadow":
                break
        except Exception:
            time.sleep(0.25)
    else:
        raise RuntimeError("candidate_startup_timeout")
    v = [12, 1, 1, 1, 0, 1, 0, 0, 5, 1, 0, 1, 100, 0, 1, 0, 0, 0.8, 0.8, 0, 365, 0, 0]
    body = json.dumps({"feature_contract": FEATURE_CONTRACT, "features": v}).encode()
    results = []
    for _ in range(5):
        request = urllib.request.Request(
            base + "/v1/shadow-score",
            data=body,
            headers={"Content-Type": "application/json", "X-Shadow-Key": TEST_KEY},
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            r = json.load(response)
        assert (
            r["applied_to_access"] is False
            and r["status"] == "evaluated"
            and len(r["explanation"]) == 23
        )
        assert (
            r["model_sha256"] == health["model_sha256"]
            and "access_decision" not in r
            and "decision" not in r
        )
        results.append(r)
    assert all(r == results[0] for r in results)
    try:
        urllib.request.urlopen(
            urllib.request.Request(
                base + "/v1/shadow-score",
                data=body,
                headers={"Content-Type": "application/json"},
            ),
            timeout=3,
        )
    except urllib.error.HTTPError as exc:
        assert exc.code == 401
    else:
        raise AssertionError("missing authentication accepted")
    print(
        json.dumps(
            {
                "scope": "CI fixture only; candidate private image HTTP smoke",
                "passed": True,
                "requests": 5,
                "shap_per_row": 23,
                "live_model_replaced": False,
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["prepare", "probe"])
    parser.add_argument("target")
    a = parser.parse_args()
    (prepare if a.mode == "prepare" else probe)(a.target)
