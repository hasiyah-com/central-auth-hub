"""Role-calibrated L3 warnings. Never changes an access decision or risk score."""

from __future__ import annotations

import json
import math
import re
from bisect import bisect_left
from functools import lru_cache
from pathlib import Path

ROLES = ("student", "teacher", "staff", "admin")
MIN_SAMPLES = 200
SCHEMA = "l3-point-role-percentile-v1"


def _hash(value):
    return isinstance(value, str) and re.fullmatch("[0-9a-f]{64}", value) is not None


def validate_artifact(a):
    if (
        not isinstance(a, dict)
        or a.get("schema") != SCHEMA
        or not _hash(a.get("model_sha256"))
    ):
        raise ValueError("invalid schema/model fingerprint")
    p = a.get("provenance", {})
    if p.get("split") != "validation-calibration" or not _hash(p.get("dataset_sha256")):
        raise ValueError("independent validation-calibration provenance required")
    roles = a.get("roles", {})
    if set(roles) != set(ROLES):
        raise ValueError("all four role distributions required")
    for role in ROLES:
        row = roles[role]
        scores = row.get("normal_scores", [])
        threshold = row.get("warn_percentile")
        if (
            not isinstance(scores, list)
            or len(scores) < MIN_SAMPLES
            or any(
                isinstance(x, bool)
                or not isinstance(x, (int, float))
                or not math.isfinite(x)
                or not 0 <= x <= 1
                for x in scores
            )
            or scores != sorted(scores)
        ):
            raise ValueError(f"invalid/insufficient normal scores: {role}")
        if (
            isinstance(threshold, bool)
            or not isinstance(threshold, (int, float))
            or not math.isfinite(threshold)
            or not 0.5 <= threshold <= 1
        ):
            raise ValueError(f"invalid percentile threshold: {role}")
    return a


def build_artifact(samples, thresholds, *, model_sha256, provenance):
    a = {
        "schema": SCHEMA,
        "model_sha256": model_sha256,
        "provenance": provenance,
        "roles": {
            r: {"normal_scores": sorted(samples[r]), "warn_percentile": thresholds[r]}
            for r in ROLES
        },
    }
    return validate_artifact(a)


@lru_cache(maxsize=4)
def _load(path, mtime_ns, size):
    return validate_artifact(json.loads(Path(path).read_text(encoding="utf-8")))


def _quiet(status, reason, role):
    return {
        "status": status,
        "reason": reason,
        "user_type": role,
        "percentile": None,
        "warn_percentile": None,
        "calibration_schema": SCHEMA,
    }


def evaluate(a, baseline_decision, role, score, model_sha256, *, validated=False):
    # Do not score a fallback even in shadow when the baseline did not allow.
    if baseline_decision != "allow":
        return _quiet("skipped", "baseline_not_allow", role)
    try:
        if not validated:
            validate_artifact(a)
        if role not in a["roles"]:
            return _quiet("abstain", "unknown_role", role)
        if not _hash(model_sha256) or model_sha256 != a["model_sha256"]:
            return _quiet("abstain", "model_mismatch", role)
        if (
            isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not math.isfinite(score)
            or not 0 <= score <= 1
        ):
            return _quiet("abstain", "invalid_score", role)
        row = a["roles"][role]
        percentile = bisect_left(row["normal_scores"], score) / len(
            row["normal_scores"]
        )
        threshold = row["warn_percentile"]
        return {
            "status": "warn" if percentile > threshold else "normal",
            "reason": "role_percentile",
            "user_type": role,
            "percentile": percentile,
            "warn_percentile": threshold,
            "n_calibration": len(row["normal_scores"]),
            "calibration_schema": SCHEMA,
            "model_sha256": model_sha256,
        }
    except (KeyError, TypeError, ValueError, AttributeError):
        return _quiet("abstain", "invalid_calibration", role)


def evaluate_file(path, baseline_decision, role, score, model_sha256):
    if baseline_decision != "allow":
        return _quiet("skipped", "baseline_not_allow", role)
    if not path:
        return _quiet("abstain", "not_configured", role)
    try:
        p = Path(path)
        stat = p.stat()
        a = _load(str(p.resolve()), stat.st_mtime_ns, stat.st_size)
        result = evaluate(
            a, baseline_decision, role, score, model_sha256, validated=True
        )
        return result
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return _quiet("abstain", "calibration_unavailable", role)
