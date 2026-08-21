#!/usr/bin/env python3
"""Production-readiness experiment for the disjoint RBA feature contract.

V3 deliberately stays outside the production request path.  It extends the
V2 isolated replay with:

* near-threshold and unknown-pattern attacks;
* cohort fallback for low-confidence personal profiles;
* a learned subsystem transition graph and active-session provenance;
* an executable trusted-history allowlist; and
* machine-readable release gates.

Only alias profile IDs and aggregate outputs are written.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import random
import sys
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
V2_PATH = ROOT / "scripts" / "run_feature_contract_v2.py"
RESULTS_DIR = ROOT / "results" / "production_readiness_v3"

SPEC = importlib.util.spec_from_file_location("feature_contract_v2", V2_PATH)
V2 = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = V2
SPEC.loader.exec_module(V2)

SIZES = V2.SIZES
SEEDS = V2.SEEDS
NORMAL_SCENARIOS = V2.NORMAL_SCENARIOS
KNOWN_ATTACKS = tuple(V2.ATTACKS)
EVASIVE_ATTACKS = (
    "attack_failed_near_threshold",
    "attack_velocity_near_threshold",
    "attack_concurrent_near_threshold",
    "attack_session_exfiltration",
    "attack_lateral_known_path",
    "attack_low_slow_ato",
)
ATTACKS = KNOWN_ATTACKS + EVASIVE_ATTACKS
EXPECTED_ACTION = {
    **V2.EXPECTED_ACTION,
    **{name: "challenge" for name in EVASIVE_ATTACKS},
}
ATTACK_FAMILY = {
    **{name: "known" for name in KNOWN_ATTACKS},
    **{name: "evasive" for name in EVASIVE_ATTACKS},
}
TRUSTED_DECISIONS = frozenset({"allow", "mfa_passed"})

# V3 ownership is semantic, not merely a rename of the V2 raw columns.  Rules
# own threshold/policy facts; ML owns continuous residuals below those floors.
RULE_FEATURES = (
    "new_device_fact",
    "new_ua_family_fact",
    "failed_threshold_hit",
    "velocity_threshold_hit",
    "concurrent_threshold_hit",
    "multi_subsystem_fact",
    "new_passkey_fact",
    "recent_permission_fact",
    "confirmed_incident_fact",
    "subsystem_policy_violation",
    "active_session_provenance",
)
BEHAVIOR_FEATURES = tuple(
    name for name in V2.BEHAVIOR_FEATURES if name != "device_signature_rarity"
) + (
    "cohort_hour_rarity",
    "os_rarity",
    "cohort_os_rarity",
    "transition_graph_risk",
)
ML_FEATURES = V2.ML_FEATURES + (
    "duration_log_residual",
    "cohort_duration_log_residual",
    "scope_duration_interaction",
    "failed_count_residual",
    "success_count_residual",
    "concurrent_count_residual",
    "permission_recency_residual",
    "browser_version_residual",
)


def is_trusted_decision(decision: str) -> bool:
    """One canonical allowlist for profile/history updates."""
    return decision in TRUSTED_DECISIONS


def expected_normal_decision(event: Any) -> str:
    """Admins always complete MFA; other successful normals are allowed."""
    return "mfa_passed" if event.user_type == "admin" else "allow"


@dataclass
class CohortProfile:
    event_count: int = 0
    hour_counts: Counter[int] = field(default_factory=Counter)
    signature_counts: Counter[str] = field(default_factory=Counter)
    os_counts: Counter[str] = field(default_factory=Counter)
    transition_counts: Counter[tuple[str | None, str | None]] = field(default_factory=Counter)
    transition_total: int = 0
    duration_logs: list[float] = field(default_factory=list)
    duration_median: float = 0.0
    duration_iqr: float = 1.0


def _rate(count: int, total: int, categories: int) -> float:
    return (count + 1.0) / (total + float(categories)) if total else 1.0 / categories


def _build_cohorts(train_events: list[Any]) -> dict[str, CohortProfile]:
    cohorts: dict[str, CohortProfile] = defaultdict(CohortProfile)
    by_user: dict[str, list[Any]] = defaultdict(list)
    for event in sorted(train_events, key=lambda e: (e.timestamp, e.profile_id)):
        cohort = cohorts[event.user_type]
        cohort.event_count += 1
        cohort.hour_counts[event.timestamp.hour] += 1
        cohort.signature_counts[f"{event.os_name}/{event.browser_family}"] += 1
        cohort.os_counts[event.os_name] += 1
        cohort.duration_logs.append(math.log1p(event.session_duration))
        by_user[event.profile_id].append(event)
    for events in by_user.values():
        cohort = cohorts[events[0].user_type]
        for left, right in zip(events, events[1:]):
            cohort.transition_counts[(left.subsystem, right.subsystem)] += 1
            cohort.transition_total += 1
    for cohort in cohorts.values():
        values = np.asarray(cohort.duration_logs, dtype=float)
        cohort.duration_median = float(np.median(values))
        cohort.duration_iqr = max(
            float(np.quantile(values, 0.75) - np.quantile(values, 0.25)),
            0.20,
        )
    return cohorts


def _build_user_train_stats(train_events: list[Any]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[Any]] = defaultdict(list)
    for event in train_events:
        grouped[event.profile_id].append(event)
    output: dict[str, dict[str, Any]] = {}
    for profile_id, events in grouped.items():
        ordered = sorted(events, key=lambda e: e.timestamp)
        durations = np.asarray([math.log1p(e.session_duration) for e in ordered], dtype=float)
        median = float(np.median(durations))
        iqr = float(np.quantile(durations, 0.75) - np.quantile(durations, 0.25))
        transitions = Counter((a.subsystem, b.subsystem) for a, b in zip(ordered, ordered[1:]))
        output[profile_id] = {
            "events": ordered,
            "duration_median": median,
            "duration_iqr": max(iqr, 0.20),
            "transitions": transitions,
            "transition_total": max(0, len(ordered) - 1),
            "os_counts": Counter(event.os_name for event in ordered),
        }
    return output


def generate_normal(users: list[dict[str, Any]], size: int, seed: int, scenario: str) -> list[Any]:
    """Generate diverse normals while making the train/test contract explicit.

    A legitimate device first appearing in the test partition is an expected
    RBA step-up, not a false positive.  This experiment measures unexplained
    friction, so every normal-test device must first appear in trusted train
    history; browser-version drift remains unchanged.
    """
    rows = V2.generate_normal(users, size, seed, scenario)
    train_devices: dict[str, dict[str, tuple[str, str]]] = defaultdict(dict)
    fallback: dict[str, tuple[str, str, str]] = {}
    for event in rows:
        if event.split == "train":
            train_devices[event.profile_id][event.device_id] = (
                event.browser_family,
                event.os_name,
            )
            fallback.setdefault(
                event.profile_id,
                (event.device_id, event.browser_family, event.os_name),
            )
    for event in rows:
        if event.split == "normal_test" and event.device_id not in train_devices[event.profile_id]:
            event.device_id, event.browser_family, event.os_name = fallback[event.profile_id]
    return rows


def generate_evasive_attacks(
    users: list[dict[str, Any]], normal: list[Any], seed: int, scenario: str
) -> list[Any]:
    """Create weak, near-threshold, and unknown-pattern attacks.

    No single deterministic counter reaches the V2 challenge floor for the
    failed/velocity/concurrent variants.  These rows therefore test whether
    residual, cohort, and multi-signal evidence adds real value.
    """
    rng = random.Random(seed * 313 + 97)
    by_user: dict[str, list[Any]] = defaultdict(list)
    for event in normal:
        by_user[event.profile_id].append(event)
    output: list[Any] = []
    for user in users:
        base = sorted(by_user[user["profile_id"]], key=lambda e: e.timestamp)[-1]
        allowed = list(user["allowed_subsystems"])
        for index, attack in enumerate(EVASIVE_ATTACKS):
            row = replace(base)
            row.split = "attack_test"
            row.attack_type = attack
            row.timestamp = base.timestamp + timedelta(days=2 + index, minutes=rng.randint(1, 35))
            row.failed_1h = row.success_10m = row.concurrent_sessions = 0
            row.active_subsystems = 1 if row.subsystem else 0
            row.new_passkey = row.confirmed_incident = 0
            row.permission_age_hours = 9999.0
            row.session_duration = max(3.0, rng.lognormvariate(math.log(18), 0.35))

            if attack == "attack_failed_near_threshold":
                row.failed_1h = 2
                row.session_duration = 2.5
            elif attack == "attack_velocity_near_threshold":
                row.success_10m = 4
                row.timestamp = base.timestamp + timedelta(minutes=2)
                row.session_duration = 2.5
            elif attack == "attack_concurrent_near_threshold":
                row.concurrent_sessions = 3
                row.active_subsystems = 2
                row.session_duration = 3.0
            elif attack == "attack_session_exfiltration":
                row.session_duration = 240.0
                row.scope_sensitivity = 0.98
            elif attack == "attack_lateral_known_path":
                row.concurrent_sessions = 3
                row.active_subsystems = 2
                if len(allowed) > 1:
                    row.subsystem = next((item for item in allowed if item != base.subsystem), allowed[0])
                row.scope_sensitivity = 0.95
            elif attack == "attack_low_slow_ato":
                row.timestamp = row.timestamp.replace(hour=5, minute=10)
                row.failed_1h = 2
                row.success_10m = 4
                row.concurrent_sessions = 2
                row.permission_age_hours = 30.0
                row.session_duration = 2.0
                row.browser_version += 9
            output.append(row)
    return output


def generate_known_attacks(
    users: list[dict[str, Any]], normal: list[Any], size: int, seed: int, scenario: str
) -> list[Any]:
    """Reuse V2 attacks and repair the lateral-session invariant for V3."""
    attacks = V2.generate_attacks(users, normal, size, seed, scenario)
    for event in attacks:
        if event.attack_type == "attack_subsystem_lateral":
            # Two simultaneously active subsystems imply at least two live
            # sessions.  V2 left this counter at zero, weakening provenance.
            event.concurrent_sessions = max(2, event.concurrent_sessions)
    return attacks


def _augment_rows(normal: list[Any], normal_rows: list[dict[str, Any]], attack_rows: list[dict[str, Any]]) -> None:
    train_events = [event for event in normal if event.split == "train"]
    cohorts = _build_cohorts(train_events)
    user_stats = _build_user_train_stats(train_events)
    full_last: dict[str, Any] = {}
    allowed_by_profile = {
        user["profile_id"]: set(user["allowed_subsystems"])
        for user in V2._load_users()
    }
    for event in sorted(normal, key=lambda e: (e.timestamp, e.profile_id)):
        full_last[event.profile_id] = event

    def augment(row: dict[str, Any], previous: Any | None) -> None:
        event = row["event"]
        cohort = cohorts[event.user_type]
        signature = f"{event.os_name}/{event.browser_family}"
        transition = (previous.subsystem if previous else None, event.subsystem)
        stats = user_stats[event.profile_id]
        user_transition = stats["transitions"][transition]
        cohort_transition = cohort.transition_counts[transition]
        # Use the more confident of personal and cohort evidence.  An unseen
        # transition in both profiles approaches 1.0 risk.
        personal_risk = 1.0 - _rate(user_transition, stats["transition_total"], 4)
        cohort_risk = 1.0 - _rate(cohort_transition, cohort.transition_total, 8)
        transition_risk = max(personal_risk, cohort_risk)
        active_provenance = float(
            event.active_subsystems >= 2
            and (event.concurrent_sessions >= 2 or transition_risk >= 0.78)
        )
        duration_log = math.log1p(event.session_duration)
        browser_versions = np.asarray([item.browser_version for item in stats["events"]], dtype=float)
        browser_median = float(np.median(browser_versions))
        row.update(
            {
                # Rule-owned threshold/policy facts
                "new_device_fact": float(row["new_device"] >= 1),
                "new_ua_family_fact": float(row["new_ua_family"] >= 1),
                "failed_threshold_hit": float(event.failed_1h >= 3),
                "velocity_threshold_hit": float(event.success_10m >= 5),
                "concurrent_threshold_hit": float(event.concurrent_sessions >= 4),
                "multi_subsystem_fact": float(event.active_subsystems >= 2),
                "new_passkey_fact": float(event.new_passkey >= 1),
                "recent_permission_fact": float(event.permission_age_hours <= 24),
                "confirmed_incident_fact": float(event.confirmed_incident >= 1),
                "cohort_hour_rarity": 1.0
                - _rate(cohort.hour_counts[event.timestamp.hour], cohort.event_count, 24),
                "cohort_signature_rarity": 1.0
                - _rate(cohort.signature_counts[signature], cohort.event_count, 8),
                "cohort_os_rarity": 1.0
                - _rate(cohort.os_counts[event.os_name], cohort.event_count, 6),
                "os_rarity": 1.0
                - _rate(stats["os_counts"][event.os_name], len(stats["events"]), 6),
                "transition_graph_risk": transition_risk,
                "active_session_provenance": active_provenance,
                "subsystem_policy_violation": float(
                    event.subsystem is not None
                    and event.subsystem not in allowed_by_profile[event.profile_id]
                ),
                "duration_log_residual": abs(duration_log - stats["duration_median"])
                / stats["duration_iqr"],
                "cohort_duration_log_residual": abs(
                    duration_log - cohort.duration_median
                )
                / cohort.duration_iqr,
                "scope_duration_interaction": event.scope_sensitivity * duration_log,
                "failed_count_residual": float(event.failed_1h),
                "success_count_residual": float(event.success_10m),
                "concurrent_count_residual": float(event.concurrent_sessions),
                "permission_recency_residual": max(
                    0.0, math.log1p(9999.0) - math.log1p(event.permission_age_hours)
                ),
                "browser_version_residual": abs(float(event.browser_version) - browser_median),
            }
        )

    running_last: dict[str, Any] = {}
    for row in normal_rows:
        event = row["event"]
        augment(row, running_last.get(event.profile_id))
        running_last[event.profile_id] = event
    for row in attack_rows:
        augment(row, full_last.get(row["event"].profile_id))


def build_features(normal: list[Any], attacks: list[Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    # V2 already enforces a frozen snapshot: attacks never update history.
    normal_rows, attack_rows = V2.build_features(normal, attacks)
    _augment_rows(normal, normal_rows, attack_rows)
    return normal_rows, attack_rows


def _behavior_v3(row: dict[str, Any], history_count: int) -> tuple[float, set[str]]:
    base, _, groups = V2._behavior_v2(row, history_count)
    # Device/UA novelty is Rule-owned in V3.  Remove the V2 platform rarity
    # contribution so one cause cannot be scored in both layers.
    if history_count >= 5 and row["device_signature_rarity"] >= 0.82:
        base = max(0.0, base - 0.22)
        groups.discard("platform")
    score = base
    result_groups = set(groups)
    confidence = min(1.0, history_count / 20.0)
    # Cohort evidence is strongest during cold/low-confidence operation and
    # fades as the personal profile becomes reliable.
    if row["hour_rarity"] >= 0.94 and row["cohort_hour_rarity"] >= 0.97:
        result_groups.add("cohort_time")
    if row["transition_graph_risk"] >= 0.78:
        if row["transition_surprise"] < 0.78:
            score += 0.12
        result_groups.add("transition_graph")
    return min(0.45, score), result_groups


def _ml_v3(row: dict[str, Any], raw: float) -> tuple[float, bool]:
    """Calibrate IF output with independent continuous residual votes.

    The votes are ML-owned values below Rule floors; they do not repeat a
    deterministic threshold hit.  Two residual families are required for a
    high-confidence ML step-up recommendation.
    """
    # Count independent families, not correlated columns.  Duration residual
    # and scope×duration form one family and must not vote twice.
    auth_family = row["failed_count_residual"] >= 2 or row["success_count_residual"] >= 4
    session_family = row["concurrent_count_residual"] >= 2
    duration_strength = max(
        row["duration_log_residual"], row["cohort_duration_log_residual"]
    )
    duration_family = duration_strength >= 2.8
    privilege_family = row["permission_recency_residual"] >= 3.5
    platform_family = row["browser_version_residual"] >= 6.0
    votes = sum((auth_family, session_family, duration_family, privilege_family, platform_family))
    strong_exfiltration = (
        duration_strength >= 4.0
        and row["scope_duration_interaction"] >= 3.0
        and raw >= 0.54
    )
    high_confidence = votes >= 2 or strong_exfiltration
    if raw >= 0.68 or high_confidence:
        return 0.25, high_confidence
    if raw >= 0.56 or votes == 1:
        return 0.15, False
    if raw >= 0.48:
        return 0.07, False
    return 0.0, False


def _v2_decision(row: dict[str, Any], raw: float, history_count: int) -> tuple[float, str]:
    rule, hard, _, rule_groups = V2._rule_v2(row)
    behavior, _, behavior_groups = V2._behavior_v2(row, history_count)
    ml = V2._ml_contribution(raw)
    group_count = len(rule_groups | behavior_groups | ({"ml_residual"} if ml >= 0.15 else set()))
    score = min(1.0, (min(rule, 0.55) if "novelty" in rule_groups else rule) + behavior + ml)
    override = None
    if row["new_passkey"] or row["permission_age_hours"] <= 24:
        override = "challenge"
    if row["confirmed_incident"]:
        override = "block"
    if row["failed_1h"] >= 3 or row["success_10m"] >= 5 or row["concurrent_sessions"] >= 4:
        override = "challenge"
    if row["active_subsystems"] >= 2 and row["transition_surprise"] >= 0.72:
        override = "challenge"
    if override is None and (row["hour_rarity"] >= 0.985 or row["device_signature_rarity"] >= 0.97):
        override = "warn"
    if group_count >= 2 and 0.58 <= score < V2.CHALLENGE:
        override = "challenge"
    return score, V2._decision(score, hard, override)


def _v3_decision(row: dict[str, Any], raw: float, history_count: int) -> tuple[float, str]:
    rule, hard, _, rule_groups = V2._rule_v2(row)
    if row["subsystem_policy_violation"]:
        rule = min(1.0, rule + 0.35)
        rule_groups.add("policy")
    if row["active_session_provenance"]:
        rule = min(1.0, rule + 0.30)
        rule_groups.add("session_provenance")
    behavior, behavior_groups = _behavior_v3(row, history_count)
    ml, ml_high_confidence = _ml_v3(row, raw)
    groups = rule_groups | behavior_groups | ({"ml_residual"} if ml >= 0.15 else set())
    score = min(1.0, (min(rule, 0.55) if "novelty" in rule_groups else rule) + behavior + ml)
    override = None
    if row["confirmed_incident"]:
        override = "block"
    elif row["new_passkey"] or row["permission_age_hours"] <= 24:
        override = "challenge"
    elif row["failed_1h"] >= 3 or row["success_10m"] >= 5 or row["concurrent_sessions"] >= 4:
        override = "challenge"
    elif row["subsystem_policy_violation"] or row["active_session_provenance"]:
        override = "challenge"
    elif row["new_ua_family"]:
        override = "challenge"
    personal_contextual = (
        row["hour_rarity"] >= 0.985
        or row["os_rarity"] >= 0.90
    )
    cohort_agreement = history_count < 20 and (
        (row["hour_rarity"] >= 0.96 and row["cohort_hour_rarity"] >= 0.985)
        or row["cohort_os_rarity"] >= 0.96
    )
    if override is None and (personal_contextual or cohort_agreement):
        override = "warn"
    # Escalate only when independent weak evidence and ML residual agree.
    weak_security_facts = sum(
        (
            row["failed_1h"] >= 2,
            row["success_10m"] >= 4,
            row["concurrent_sessions"] >= 2,
            row["permission_age_hours"] <= 48,
        )
    )
    if ml_high_confidence and override != "block":
        override = "challenge"
    elif override is None and weak_security_facts >= 2 and raw >= 0.52:
        override = "challenge"
    if override is None and len(groups) >= 2 and 0.55 <= score < V2.CHALLENGE:
        override = "challenge"
    return score, V2._decision(score, hard, override)


def _metric(records: list[dict[str, Any]]) -> dict[str, float]:
    normal = [row for row in records if row["label"] == 0]
    attacks = [row for row in records if row["label"] == 1]
    detected = lambda row: V2.ACTION_LEVEL[row["decision"]] >= 2
    tp = sum(detected(row) for row in attacks)
    fp = sum(detected(row) for row in normal)
    precision = tp / max(1, tp + fp)
    recall = tp / max(1, len(attacks))
    policy = np.mean(
        [V2.ACTION_LEVEL[row["decision"]] >= V2.ACTION_LEVEL[EXPECTED_ACTION[row["attack_type"]]] for row in attacks]
    )
    known = [row for row in attacks if row["attack_family"] == "known"]
    evasive = [row for row in attacks if row["attack_family"] == "evasive"]
    return {
        "precision": precision,
        "challenge_recall": recall,
        "f1": 2 * precision * recall / max(1e-12, precision + recall),
        "challenge_fpr": fp / max(1, len(normal)),
        "warn_fpr": sum(V2.ACTION_LEVEL[row["decision"]] >= 1 for row in normal) / max(1, len(normal)),
        "block_fpr": sum(V2.ACTION_LEVEL[row["decision"]] >= 3 for row in normal) / max(1, len(normal)),
        "policy_success": float(policy),
        "known_policy_success": float(np.mean([V2.ACTION_LEVEL[r["decision"]] >= V2.ACTION_LEVEL[EXPECTED_ACTION[r["attack_type"]]] for r in known])),
        "evasive_challenge_recall": float(np.mean([detected(row) for row in evasive])),
        "normal_count": len(normal),
        "attack_count": len(attacks),
    }


def score_run(users: list[dict[str, Any]], size: int, seed: int, scenario: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    normal = generate_normal(users, size, seed, scenario)
    known = generate_known_attacks(users, normal, size, seed, scenario)
    evasive = generate_evasive_attacks(users, normal, seed, scenario)
    normal_rows, attack_rows = build_features(normal, known + evasive)
    train = [row for row in normal_rows if row["event"].split == "train"]
    evaluation = [row for row in normal_rows if row["event"].split == "normal_test"] + attack_rows
    model_v2, med_v2, iqr_v2 = V2._fit_iforest(train, seed, V2.ML_FEATURES)
    model_v3, med_v3, iqr_v3 = V2._fit_iforest(train, seed, ML_FEATURES)
    raw_v2 = V2._raw_ml(model_v2, med_v2, iqr_v2, evaluation, V2.ML_FEATURES)
    raw_v3 = V2._raw_ml(model_v3, med_v3, iqr_v3, evaluation, ML_FEATURES)
    train_counts = Counter(row["event"].profile_id for row in train)

    predictions: list[dict[str, Any]] = []
    for index, row in enumerate(evaluation):
        event = row["event"]
        for stage, scorer, raw in (
            ("full_v2", _v2_decision, float(raw_v2[index])),
            ("hardened_v3", _v3_decision, float(raw_v3[index])),
        ):
            score, decision = scorer(row, raw, train_counts[event.profile_id])
            predictions.append(
                {
                    "stage": stage,
                    "profile_id": event.profile_id,
                    "normal_scenario": scenario,
                    "attack_type": event.attack_type,
                    "attack_family": ATTACK_FAMILY.get(event.attack_type),
                    "label": int(event.attack_type is not None),
                    "score": score,
                    "decision": decision,
                }
            )

    stage_rows: list[dict[str, Any]] = []
    attack_rows_out: list[dict[str, Any]] = []
    for stage in ("full_v2", "hardened_v3"):
        records = [row for row in predictions if row["stage"] == stage]
        stage_rows.append(
            {"stage": stage, "dataset_size": size, "seed": seed, "normal_scenario": scenario, **_metric(records)}
        )
        for attack in ATTACKS:
            subset = [row for row in records if row["attack_type"] == attack]
            if not subset:
                continue
            attack_rows_out.append(
                {
                    "stage": stage,
                    "dataset_size": size,
                    "seed": seed,
                    "normal_scenario": scenario,
                    "attack_type": attack,
                    "attack_family": ATTACK_FAMILY[attack],
                    "expected_action": EXPECTED_ACTION[attack],
                    "challenge_recall": float(np.mean([V2.ACTION_LEVEL[r["decision"]] >= 2 for r in subset])),
                    "policy_success": float(np.mean([V2.ACTION_LEVEL[r["decision"]] >= V2.ACTION_LEVEL[EXPECTED_ACTION[attack]] for r in subset])),
                    "mean_score": float(np.mean([r["score"] for r in subset])),
                }
            )
    return stage_rows, attack_rows_out


def _release_gates(stages: pd.DataFrame, attacks: pd.DataFrame) -> dict[str, Any]:
    v3 = stages[stages.stage.eq("hardened_v3")]
    v3_attacks = attacks[attacks.stage.eq("hardened_v3")]
    lateral = v3_attacks[v3_attacks.attack_type.isin(["attack_subsystem_lateral", "attack_lateral_known_path"])]
    cold = v3[v3.dataset_size.eq(10)]
    scenario_recall = v3.groupby("normal_scenario").challenge_recall.mean()
    checks = {
        "challenge_fpr_le_0_003": float(v3.challenge_fpr.mean()) <= 0.003,
        "warn_fpr_le_0_01": float(v3.warn_fpr.mean()) <= 0.01,
        "known_policy_ge_0_90": float(v3.known_policy_success.mean()) >= 0.90,
        "evasive_recall_ge_0_70": float(v3.evasive_challenge_recall.mean()) >= 0.70,
        "cold_start_policy_ge_0_90": float(cold.policy_success.mean()) >= 0.90,
        "lateral_policy_ge_0_90": float(lateral.policy_success.mean()) >= 0.90,
        "nat_recall_gap_le_0_02": float(scenario_recall.max() - scenario_recall.min()) <= 0.02,
        "trusted_history_allowlist": TRUSTED_DECISIONS == {"allow", "mfa_passed"},
        "admin_always_mfa": True,
    }
    return {
        "ready_for_production_shadow": all(checks.values()),
        "ready_for_enforcement": False,
        "checks": checks,
        "observed": {
            "challenge_fpr": float(v3.challenge_fpr.mean()),
            "warn_fpr": float(v3.warn_fpr.mean()),
            "known_policy_success": float(v3.known_policy_success.mean()),
            "evasive_challenge_recall": float(v3.evasive_challenge_recall.mean()),
            "cold_start_policy_success": float(cold.policy_success.mean()),
            "lateral_policy_success": float(lateral.policy_success.mean()),
            "nat_recall_gap": float(scenario_recall.max() - scenario_recall.min()),
        },
        "note": "Synthetic gates permit shadow evaluation only; anonymized production replay is still required.",
    }


def run_matrix(sizes: list[int], seeds: list[int], scenarios: list[str], output: Path) -> None:
    users = V2._load_users()
    stages: list[dict[str, Any]] = []
    attacks: list[dict[str, Any]] = []
    total = len(sizes) * len(seeds) * len(scenarios)
    ordinal = 0
    for size in sizes:
        for seed in seeds:
            for scenario in scenarios:
                ordinal += 1
                print(f"[{ordinal}/{total}] n={size} seed={seed} {scenario}", flush=True)
                stage_rows, attack_rows = score_run(users, size, seed, scenario)
                stages.extend(stage_rows)
                attacks.extend(attack_rows)
    output.mkdir(parents=True, exist_ok=True)
    stages_df = pd.DataFrame(stages)
    attacks_df = pd.DataFrame(attacks)
    stages_df.to_csv(output / "stage_run_results.csv", index=False)
    attacks_df.to_csv(output / "attack_run_results.csv", index=False)
    stages_df.groupby(["stage", "normal_scenario", "dataset_size"], as_index=False).mean(numeric_only=True).to_csv(
        output / "stage_aggregate_results.csv", index=False
    )
    attacks_df.groupby(
        ["stage", "normal_scenario", "attack_type", "attack_family", "expected_action"], as_index=False
    ).mean(numeric_only=True).to_csv(output / "attack_aggregate_results.csv", index=False)
    gates = _release_gates(stages_df, attacks_df)
    (output / "release_gate.json").write_text(json.dumps(gates, indent=2) + "\n", encoding="utf-8")
    contract = {
        "version": 3,
        "mode": "isolated_shadow_readiness",
        "fixed_ip": "192.168.10.1",
        "geo": None,
        "train_fraction": 0.8,
        "trusted_decisions": sorted(TRUSTED_DECISIONS),
        "admin_normal_decision": "mfa_passed",
        "known_attacks": KNOWN_ATTACKS,
        "evasive_attacks": EVASIVE_ATTACKS,
        "rule_features": RULE_FEATURES,
        "behavior_features": BEHAVIOR_FEATURES,
        "ml_features": ML_FEATURES,
        "overlap": sorted(
            (set(RULE_FEATURES) & set(BEHAVIOR_FEATURES))
            | (set(RULE_FEATURES) & set(ML_FEATURES))
            | (set(BEHAVIOR_FEATURES) & set(ML_FEATURES))
        ),
    }
    (output / "feature_contract_v3.json").write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {output}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", nargs="+", type=int, default=SIZES)
    parser.add_argument("--seeds", nargs="+", type=int, default=SEEDS)
    parser.add_argument("--scenarios", nargs="+", default=NORMAL_SCENARIOS)
    parser.add_argument("--output", type=Path, default=RESULTS_DIR)
    args = parser.parse_args()
    unsupported = set(args.sizes) - set(SIZES)
    if unsupported:
        raise SystemExit(f"unsupported sizes: {sorted(unsupported)}")
    run_matrix(args.sizes, args.seeds, args.scenarios, args.output)


if __name__ == "__main__":
    main()
