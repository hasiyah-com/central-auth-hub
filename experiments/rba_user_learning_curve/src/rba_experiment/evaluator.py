"""Train and evaluate the production-shaped four-layer RBA pipeline."""

from __future__ import annotations

import hashlib
import json
import statistics
from collections import Counter, defaultdict, deque
from datetime import timedelta
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import sklearn
from sklearn.ensemble import IsolationForest
from sklearn.metrics import average_precision_score, roc_auc_score

from .contracts import FEATURE_NAMES, load_config
from .feature_store import parse_timestamp
from .results import empty_metric_fields, upsert_combined_result

WARN_THRESHOLD = 0.5
CHALLENGE_THRESHOLD = 0.7
BLOCK_THRESHOLD = 0.85
BEHAVIOR_LOOKBACK_DAYS = 30
BEHAVIOR_COLD_START_COUNT = 5


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
    temporary.replace(path)


def _feature_matrix(rows: list[dict[str, Any]]) -> np.ndarray:
    return np.asarray(
        [[float(row[name]) for name in FEATURE_NAMES] for row in rows],
        dtype=float,
    )


def _iforest_scores(
    model: IsolationForest, rows: list[dict[str, Any]]
) -> dict[str, float]:
    decisions = model.decision_function(_feature_matrix(rows))
    scores = 1.0 / (1.0 + np.exp(decisions * 5.0))
    return {
        row["event_id"]: float(score)
        for row, score in zip(rows, scores, strict=True)
    }


def _iforest_contribution(raw_score: float) -> float:
    if raw_score >= 0.7:
        return 0.4
    if raw_score >= 0.5:
        return 0.2
    if raw_score >= 0.3:
        return 0.1
    return 0.0


def _behavior_score(
    row: dict[str, Any],
    event: dict[str, Any],
    profile_history: list[dict[str, Any]],
) -> tuple[float, list[str]]:
    now = parse_timestamp(event["created_at"])
    cutoff = now - timedelta(days=BEHAVIOR_LOOKBACK_DAYS)
    history = [
        item
        for item in profile_history
        if cutoff <= parse_timestamp(item["created_at"]) < now
    ]
    if len(history) < BEHAVIOR_COLD_START_COUNT:
        return 0.2, ["behavior_cold_start"]

    hours = [parse_timestamp(item["created_at"]).hour for item in history]
    typical_hour = statistics.mode(hours)
    current_hour = parse_timestamp(event["created_at"]).hour
    raw_diff = abs(current_hour - typical_hour)
    hour_diff = min(raw_diff, 24 - raw_diff)
    weekend_rate = sum(
        parse_timestamp(item["created_at"]).weekday() >= 5 for item in history
    ) / len(history)
    typical_weekend = round(weekend_rate)
    current_weekend = int(now.weekday() >= 5)

    score = 0.0
    reasons: list[str] = []
    if hour_diff >= 10:
        score += 0.4
        reasons.append("behavior_hour_diff_10_plus")
    elif hour_diff >= 6:
        score += 0.2
        reasons.append("behavior_hour_diff_6_plus")
    if float(row["is_new_country"]) > 0:
        score += 0.3
        reasons.append("behavior_new_country")
    if float(row["is_new_device"]) > 0:
        score += 0.2
        reasons.append("behavior_new_device")
    if current_weekend != typical_weekend:
        score += 0.1
        reasons.append("behavior_weekend_mismatch")
    return min(score, 1.0), reasons


def _rule_score(
    row: dict[str, Any],
    distinct_profiles_last_hour: int,
) -> tuple[float, bool, list[str]]:
    failed = float(row["failed_logins_24h"])
    velocity = float(row["login_count_24h"])
    country_changes = float(row["country_change_count_30d"])
    if failed >= 10:
        return 1.0, True, ["hard_block_failed_logins_10_plus"]
    if velocity >= 50:
        return 1.0, True, ["hard_block_login_velocity_50_plus"]
    if country_changes >= 8:
        return 1.0, True, ["hard_block_country_changes_8_plus"]

    score = 0.0
    reasons: list[str] = []
    weighted_rules = (
        ("is_new_device", 0.30, "rule_new_device"),
        ("is_new_country", 0.30, "rule_new_country"),
        ("is_new_user_agent_family", 0.20, "rule_new_ua_family"),
    )
    for name, weight, reason in weighted_rules:
        if float(row[name]) > 0:
            score += weight
            reasons.append(reason)
    if failed >= 3:
        score += 0.20
        reasons.append("rule_failed_logins_3_plus")
    if float(row["is_thailand"]) == 0:
        score += 0.10
        reasons.append("rule_foreign_login")
        if float(row["is_new_country"]) > 0:
            score += 0.30
            reasons.append("rule_new_foreign_country")
    if float(row["impossible_travel_score"]) >= 0.5:
        score += 0.30
        reasons.append("rule_impossible_travel")
    if distinct_profiles_last_hour > 5:
        score += 0.25
        reasons.append("rule_multi_account_ip")
    return min(score, 1.0), False, reasons


def _decision(score: float, hard_block: bool) -> str:
    if hard_block or score >= BLOCK_THRESHOLD:
        return "would_block"
    if score >= CHALLENGE_THRESHOLD:
        return "would_challenge"
    if score >= WARN_THRESHOLD:
        return "would_warn"
    return "allow"


def _safe_ratio(numerator: int, denominator: int) -> float:
    return float(numerator / denominator) if denominator else 0.0


def _threshold_rates(
    labels: np.ndarray, scores: np.ndarray, threshold: float
) -> tuple[float, float]:
    detected = scores >= threshold
    normal = labels == 0
    attack = labels == 1
    return (
        _safe_ratio(int(np.sum(detected & normal)), int(np.sum(normal))),
        _safe_ratio(int(np.sum(detected & attack)), int(np.sum(attack))),
    )


def _metrics(
    manifest: dict[str, Any], predictions: list[dict[str, Any]]
) -> dict[str, Any]:
    labels = np.asarray([item["label"] for item in predictions], dtype=int)
    scores = np.asarray(
        [item["total_risk_score"] for item in predictions], dtype=float
    )
    detected = scores >= CHALLENGE_THRESHOLD
    attack = labels == 1
    normal = labels == 0
    tp = int(np.sum(detected & attack))
    fp = int(np.sum(detected & normal))
    tn = int(np.sum(~detected & normal))
    fn = int(np.sum(~detected & attack))
    precision = _safe_ratio(tp, tp + fp)
    recall = _safe_ratio(tp, tp + fn)
    warn_fpr, warn_recall = _threshold_rates(labels, scores, WARN_THRESHOLD)
    challenge_fpr, challenge_recall = _threshold_rates(
        labels, scores, CHALLENGE_THRESHOLD
    )
    block_fpr, block_recall = _threshold_rates(labels, scores, BLOCK_THRESHOLD)
    tiers = Counter(
        item["final_decision"].removeprefix("would_") for item in predictions
    )

    return {
        "run_id": manifest["run_id"],
        "scope": "overall",
        "scope_value": "all_evaluation_rows",
        "dataset_size": manifest["dataset_size"],
        "seed": manifest["seed"],
        "normal_count": int(np.sum(normal)),
        "attack_count": int(np.sum(attack)),
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": _safe_ratio(2 * precision * recall, precision + recall),
        "roc_auc": float(roc_auc_score(labels, scores)),
        "pr_auc": float(average_precision_score(labels, scores)),
        "fpr": challenge_fpr,
        "allow_rate": _safe_ratio(tn, int(np.sum(normal))),
        "warn_plus_fpr": warn_fpr,
        "warn_plus_recall": warn_recall,
        "challenge_plus_fpr": challenge_fpr,
        "challenge_plus_recall": challenge_recall,
        "block_fpr": block_fpr,
        "block_recall": block_recall,
        "allow_count": tiers["allow"],
        "warn_count": tiers["warn"],
        "challenge_count": tiers["challenge"],
        "block_count": tiers["block"],
        "mean_risk": float(np.mean(scores)),
        "median_risk": float(np.median(scores)),
        "p90_risk": float(np.quantile(scores, 0.90)),
        "p95_risk": float(np.quantile(scores, 0.95)),
    }


def _write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def evaluate_run(run_dir: Path, combined_result_path: Path | None = None) -> dict[str, Any]:
    """Fit on normal train only, score normal/attack tests, and persist outputs."""
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    events = _read_jsonl(run_dir / "events.jsonl")
    snapshots = _read_jsonl(run_dir / "feature_snapshots.jsonl")
    by_event = {event["event_id"]: event for event in events}
    train = [item for item in snapshots if item["split"] == "train"]
    evaluation = [item for item in snapshots if item["split"] != "train"]
    if not train or not evaluation:
        raise ValueError("run must contain train and evaluation feature snapshots")
    if any(item["label"] != 0 for item in train):
        raise ValueError("Isolation Forest training rows must all be normal")

    model_config = load_config("experiment")["model"]
    effective_max_samples = min(int(model_config["max_samples"]), len(train))
    model = IsolationForest(
        n_estimators=int(model_config["n_estimators"]),
        contamination=float(model_config["contamination"]),
        max_samples=effective_max_samples,
        random_state=int(manifest["seed"]),
        n_jobs=-1,
    )
    model.fit(_feature_matrix(train))
    model_digest = hashlib.sha256(
        json.dumps(
            {
                "run_id": manifest["run_id"],
                "feature_names": FEATURE_NAMES,
                "model": model_config,
                "effective_max_samples": effective_max_samples,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:16]
    model_id = f"iforest-{model_digest}"

    model_dir = run_dir / "model"
    model_dir.mkdir(exist_ok=True)
    model_path = model_dir / "iforest.pkl"
    temporary_model = model_dir / "iforest.pkl.tmp"
    joblib.dump(model, temporary_model)
    temporary_model.replace(model_path)
    _write_json(
        model_dir / "metadata.json",
        {
            "model_id": model_id,
            "run_id": manifest["run_id"],
            "trained_on_split": "train",
            "trained_on_label": 0,
            "train_count": len(train),
            "feature_names": FEATURE_NAMES,
            "n_estimators": int(model_config["n_estimators"]),
            "contamination": float(model_config["contamination"]),
            "max_samples_requested": int(model_config["max_samples"]),
            "max_samples_effective": effective_max_samples,
            "random_state": int(manifest["seed"]),
            "scikit_learn_version": sklearn.__version__,
        },
    )

    normal_events = sorted(
        [event for event in events if event["history_mode"] == "sequential"],
        key=lambda item: (item["created_at"], item["sequence_no"]),
    )
    train_events = [event for event in normal_events if event["split"] == "train"]
    normal_test_events = [
        event for event in normal_events if event["split"] == "normal_test"
    ]
    attack_events = sorted(
        [event for event in events if event["history_mode"] == "frozen_normal_snapshot"],
        key=lambda item: (item["created_at"], item["sequence_no"]),
    )
    snapshot_by_event = {item["event_id"]: item for item in evaluation}
    raw_iforest_by_event = _iforest_scores(model, evaluation)
    all_normal_by_profile: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in normal_events:
        all_normal_by_profile[event["profile_id"]].append(event)
    profile_history: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in train_events:
        profile_history[event["profile_id"]].append(event)

    ip_windows: dict[str, deque[tuple[Any, str]]] = defaultdict(deque)
    ip_profile_counts: dict[str, Counter[str]] = defaultdict(Counter)

    def add_ip_history(event: dict[str, Any]) -> None:
        ip = event["ip"]
        profile_id = event["profile_id"]
        ip_windows[ip].append((parse_timestamp(event["created_at"]), profile_id))
        ip_profile_counts[ip][profile_id] += 1

    def distinct_profiles_before(event: dict[str, Any]) -> int:
        ip = event["ip"]
        cutoff = parse_timestamp(event["created_at"]) - timedelta(hours=1)
        window = ip_windows[ip]
        counts = ip_profile_counts[ip]
        while window and window[0][0] < cutoff:
            _, profile_id = window.popleft()
            counts[profile_id] -= 1
            if counts[profile_id] == 0:
                del counts[profile_id]
        return len(counts)

    for event in train_events:
        add_ip_history(event)

    predictions: list[dict[str, Any]] = []

    def score_event(
        event: dict[str, Any],
        user_history: list[dict[str, Any]],
        distinct_profiles_last_hour: int,
    ) -> dict[str, Any]:
        row = snapshot_by_event[event["event_id"]]
        raw_iforest = raw_iforest_by_event[event["event_id"]]
        iforest_part = _iforest_contribution(raw_iforest)
        rule_part, hard_block, rule_reasons = _rule_score(
            row, distinct_profiles_last_hour
        )
        behavior_part, behavior_reasons = _behavior_score(row, event, user_history)
        total = min(1.0, rule_part + behavior_part + iforest_part)
        final_decision = _decision(total, hard_block)
        reasons = rule_reasons + behavior_reasons
        if iforest_part:
            reasons.append(f"iforest_contribution_{iforest_part:.1f}")
        return {
            "run_id": manifest["run_id"],
            "model_id": model_id,
            "dataset_size": manifest["dataset_size"],
            "seed": manifest["seed"],
            "event_id": event["event_id"],
            "profile_id": event["profile_id"],
            "user_type": event["user_type"],
            "split": event["split"],
            "scenario": event["scenario"],
            "label": event["label"],
            "iforest_raw_score": raw_iforest,
            "iforest_contribution": iforest_part,
            "rule_score": rule_part,
            "behavior_score": behavior_part,
            "total_risk_score": total,
            "final_decision": final_decision,
            "detected_warn_plus": total >= WARN_THRESHOLD,
            "detected_challenge_plus": total >= CHALLENGE_THRESHOLD,
            "detected_block": hard_block or total >= BLOCK_THRESHOLD,
            "risk_reasons": reasons,
        }

    for event in normal_test_events:
        prediction = score_event(
            event,
            profile_history[event["profile_id"]],
            distinct_profiles_before(event),
        )
        predictions.append(prediction)
        profile_history[event["profile_id"]].append(event)
        add_ip_history(event)

    for event in attack_events:
        predictions.append(
            score_event(
                event,
                all_normal_by_profile[event["profile_id"]],
                0,
            )
        )

    predictions.sort(key=lambda item: (by_event[item["event_id"]]["created_at"], item["event_id"]))
    _write_jsonl(run_dir / "predictions.jsonl", predictions)
    metrics = _metrics(manifest, predictions)
    _write_json(run_dir / "metrics.json", metrics)

    if combined_result_path is not None:
        split_counts = Counter(item["split"] for item in snapshots)
        combined = {
            "run_id": manifest["run_id"],
            "status": "evaluated",
            "git_commit_sha": manifest["git_commit_sha"],
            "normal_scenario": manifest["normal_scenario"],
            "dataset_size": manifest["dataset_size"],
            "seed": manifest["seed"],
            "profile_count": len({item["profile_id"] for item in snapshots}),
            "train_count": split_counts["train"],
            "normal_test_count": split_counts["normal_test"],
            "attack_count": split_counts["attack_test"],
            "feature_count": len(FEATURE_NAMES),
            **empty_metric_fields(),
            **{
                key: value
                for key, value in metrics.items()
                if key in empty_metric_fields()
            },
            "model_id": model_id,
            "error": "",
        }
        upsert_combined_result(combined_result_path, combined)

    return {
        "run_id": manifest["run_id"],
        "model_id": model_id,
        "model_path": model_path,
        "prediction_path": run_dir / "predictions.jsonl",
        "metrics_path": run_dir / "metrics.json",
        "prediction_count": len(predictions),
        "metrics": metrics,
    }
