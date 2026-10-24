"""Bounded private candidate request. Diagnostic values never enter access policy."""

import asyncio, hashlib, hmac, json, math, re
from urllib.parse import urlsplit
import httpx
from app.config import settings
from app.services.feature_time import FEATURE_CONTRACT
from app.security.rule_engine import FEAT

_slots = asyncio.Semaphore(4)


def quiet(status):
    return dict(
        version="if-candidate-shadow-v1",
        mode="shadow",
        status=status,
        applied_to_access=False,
    )


def _digest(v):
    return hashlib.sha256(
        json.dumps(v, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _response(data, v):
    if (
        not isinstance(data, dict)
        or data.get("version") != "if-candidate-shadow-v1"
        or data.get("mode") != "shadow"
        or data.get("applied_to_access") is not False
        or data.get("input_contract") != FEATURE_CONTRACT
        or data.get("training_semantics") != "offline-r79-mirror-not-live-certified"
        or data.get("model_sha256") != settings.l3_candidate_shadow_model_sha256
        or data.get("input_sha256") != _digest(v)
    ):
        raise ValueError("wrong_candidate_response")
    if data.get("status") not in ("evaluated", "degraded_shap"):
        raise ValueError("invalid_status")
    raw, score, cut, threshold = [
        data[k] for k in ["raw_score", "score", "raw_threshold", "threshold"]
    ]
    if any(
        type(x) not in (int, float) or not math.isfinite(x)
        for x in [raw, score, cut, threshold]
    ):
        raise ValueError("invalid_numbers")
    if (
        abs(cut - settings.l3_candidate_shadow_raw_threshold) > 1e-12
        or not 0 <= score <= 1
        or abs(score - 1 / (1 + math.exp(max(-700, min(700, -5 * raw))))) > 1e-10
        or abs(threshold - 1 / (1 + math.exp(-5 * cut))) > 1e-10
        or data.get("flagged") is not (raw > cut)
    ):
        raise ValueError("invalid_score_semantics")
    entries = data.get("explanation")
    if not isinstance(entries, list):
        raise ValueError("invalid_explanation")
    if data["status"] == "evaluated":
        if len(entries) != 23 or {e["feature"] for e in entries} != set(FEAT):
            raise ValueError("missing_explanation")
        if any(
            type(e["shap"]) not in (float, int)
            or not math.isfinite(e["shap"])
            or e["value"] != v[FEAT[e["feature"]]]
            for e in entries
        ):
            raise ValueError("invalid_explanation")
        if any(
            e.get("direction") != ("anomaly" if e["shap"] > 0 else "normal")
            for e in entries
        ):
            raise ValueError("invalid_explanation_direction")
    elif entries:
        raise ValueError("fabricated_explanation")
    if data.get("shap_unit") != "negative_mean_corrected_path_length_not_risk_points":
        raise ValueError("invalid_shap_units")
    # Whitelist telemetry; no externally supplied access/decision fields survive.
    output = {
        k: data[k]
        for k in [
            "version",
            "mode",
            "status",
            "applied_to_access",
            "input_contract",
            "training_semantics",
            "model_sha256",
            "input_sha256",
            "raw_score",
            "score",
            "raw_threshold",
            "threshold",
            "flagged",
            "shap_unit",
        ]
    }
    output["explanation"] = [
        {k: e[k] for k in ["feature", "value", "shap", "direction"]} for e in entries
    ]
    return output


async def evaluate_candidate(features):
    if not settings.l3_candidate_shadow_enabled:
        return None
    try:
        v = [float(x) for x in features]
        url = urlsplit(settings.l3_candidate_shadow_url)
        if len(v) != 23 or not all(math.isfinite(x) for x in v):
            return quiet("invalid_features")
        if (
            url.scheme not in ("http", "https")
            or not url.hostname
            or url.username
            or url.password
            or url.fragment
            or url.query
            or url.path != "/v1/shadow-score"
            or len(settings.l3_candidate_shadow_key) < 32
            or not re.fullmatch(
                "[0-9a-f]{64}", settings.l3_candidate_shadow_model_sha256
            )
        ):
            return quiet("configuration_unavailable")
        if _slots.locked():
            return quiet("busy")
        # No await between the locked check and immediate acquisition: no unbounded queue.
        await _slots.acquire()
        try:
            async with asyncio.timeout(settings.l3_candidate_shadow_timeout_seconds):
                async with httpx.AsyncClient(
                    timeout=settings.l3_candidate_shadow_timeout_seconds,
                    trust_env=False,
                    follow_redirects=False,
                ) as session:
                    r = await session.post(
                        settings.l3_candidate_shadow_url,
                        json={"feature_contract": FEATURE_CONTRACT, "features": v},
                        headers={"X-Shadow-Key": settings.l3_candidate_shadow_key},
                    )
                    r.raise_for_status()
                    if len(r.content) > 32768:
                        return quiet("invalid_response")
                    try:
                        return _response(r.json(), v)
                    except Exception:
                        return quiet("invalid_response")
        finally:
            _slots.release()
    except (TimeoutError, httpx.TimeoutException):
        return quiet("timeout")
    except Exception:
        return quiet("unavailable")
