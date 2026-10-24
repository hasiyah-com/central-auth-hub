"""Independent research candidate. Never imports or modifies the live model cache."""

import hashlib, hmac, json, math, threading
from io import BytesIO
from pathlib import Path
import joblib, numpy as np, sklearn
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import IsolationForest
from app.features import FEATURE_NAMES, FEATURE_CONTRACT, FEATURE_RANGES

VERSION = "if-candidate-shadow-v1"


class CandidateError(ValueError):
    pass


def input_digest(values):
    return hashlib.sha256(
        json.dumps(
            [float(v) for v in values], separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


class Candidate:
    def __init__(self, pipeline, manifest, explainer):
        self.pipeline = pipeline
        self.manifest = manifest
        self.explainer = explainer
        self.lock = threading.Lock()

    @classmethod
    def load(cls, artifact_path, manifest_path, expected_manifest_sha256):
        try:
            raw = Path(manifest_path).read_bytes()
            if (
                len(raw) > 65536
                or len(expected_manifest_sha256) != 64
                or not hmac.compare_digest(
                    hashlib.sha256(raw).hexdigest(), expected_manifest_sha256
                )
            ):
                raise CandidateError("manifest_hash_mismatch")
            m = json.loads(raw)
            if (
                m.get("version") != VERSION
                or m.get("mode") != "shadow"
                or m.get("input_contract") != FEATURE_CONTRACT
                or m.get("features") != FEATURE_NAMES
                or m.get("score_transform") != "sigmoid_5_negative_decision"
                or m.get("sklearn_version") != sklearn.__version__
                or not m.get("training_semantics")
                or not m.get("source_provenance")
            ):
                raise CandidateError("candidate_metadata_mismatch")
            threshold = m.get("raw_threshold")
            if (
                type(threshold) not in (float, int)
                or not math.isfinite(threshold)
                or not -1 <= threshold <= 1
            ):
                raise CandidateError("invalid_threshold")
            content = Path(artifact_path).read_bytes()
            if (
                len(content) > 32 * 1024 * 1024
                or not isinstance(m.get("artifact_sha256"), str)
                or not hmac.compare_digest(
                    hashlib.sha256(content).hexdigest(), m["artifact_sha256"]
                )
            ):
                raise CandidateError("artifact_hash_mismatch")
            # Trusted local bytes only; hash and manifest checked before pickle execution.
            pipeline = joblib.load(BytesIO(content))
            if (
                not isinstance(pipeline, Pipeline)
                or len(pipeline.steps) != 2
                or not isinstance(pipeline.steps[0][1], StandardScaler)
                or not isinstance(pipeline.steps[1][1], IsolationForest)
            ):
                raise CandidateError("unsupported_pipeline")
            if any(
                getattr(obj, "n_features_in_", None) != 23
                for obj in [pipeline, pipeline.steps[0][1], pipeline.steps[1][1]]
            ):
                raise CandidateError("invalid_dimensions")
            if pipeline.steps[1][1].n_jobs not in (None, 1):
                raise CandidateError("unbounded_forest_jobs")
            import shap

            explainer = shap.TreeExplainer(
                pipeline.steps[1][1], feature_perturbation="tree_path_dependent"
            )
            return cls(pipeline, m, explainer)
        except CandidateError:
            raise
        except Exception as exc:
            raise CandidateError("candidate_load_failed") from exc

    def evaluate(self, values):
        try:
            v = np.asarray(values, dtype=float)
        except Exception as exc:
            raise CandidateError("invalid_features") from exc
        if v.shape != (23,) or not np.isfinite(v).all():
            raise CandidateError("invalid_features")
        if any(
            not lo <= v[i] <= hi
            for i, name in enumerate(FEATURE_NAMES)
            for lo, hi in [FEATURE_RANGES[name]]
        ):
            raise CandidateError("feature_out_of_range")
        with self.lock:
            transformed = self.pipeline.steps[0][1].transform(v.reshape(1, -1))
            raw = -float(self.pipeline.steps[1][1].decision_function(transformed)[0])
            score = float(1 / (1 + np.exp(np.clip(-5 * raw, -700, 700))))
            cut = float(self.manifest["raw_threshold"])
            if not math.isfinite(raw):
                raise CandidateError("invalid_score")
            explanation = []
            status = "evaluated"
            try:
                contributions = -np.asarray(
                    self.explainer.shap_values(transformed), dtype=float
                )
                if (
                    contributions.shape != (1, 23)
                    or not np.isfinite(contributions).all()
                ):
                    raise CandidateError("invalid_shap")
                explanation = [
                    dict(
                        feature=FEATURE_NAMES[i],
                        value=float(v[i]),
                        shap=float(contributions[0, i]),
                        direction="anomaly" if contributions[0, i] > 0 else "normal",
                    )
                    for i in np.argsort(-np.abs(contributions[0]), kind="stable")
                ]
            except Exception:
                status = "degraded_shap"
        return dict(
            version=VERSION,
            mode="shadow",
            status=status,
            applied_to_access=False,
            input_contract=FEATURE_CONTRACT,
            training_semantics=self.manifest["training_semantics"],
            model_sha256=self.manifest["artifact_sha256"],
            input_sha256=input_digest(v),
            raw_score=raw,
            score=score,
            raw_threshold=cut,
            threshold=float(1 / (1 + math.exp(-5 * cut))),
            flagged=bool(raw > cut),
            explanation=explanation,
            shap_unit="negative_mean_corrected_path_length_not_risk_points",
        )
