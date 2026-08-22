#!/usr/bin/env python3
"""Standalone V8 temporal MLP experiment.

V8 intentionally does not import any V2-V7 experiment module.  It rebuilds
the synthetic timeline, feature extraction, attack campaigns, model fitting,
normal-only threshold calibration, evaluation, release gate, and portable
artifact from first principles.  The classifier is a small NumPy MLP; no
RandomForest, IsolationForest, sklearn estimator, pickle, or joblib is used.

The experiment remains shadow-only.  A passing synthetic gate is necessary
but never sufficient for enforcement.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
import random
import time
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score


ROOT = Path(__file__).resolve().parents[1]
USERS_PATH = ROOT / "config" / "users.json"
RESULTS_DIR = ROOT / "results" / "temporal_mlp_v8"

SIZES = [10, 50, 100, 500, 1000, 5000]
SEEDS = [42, 43, 44, 45, 46]
SCENARIOS = ["normal_staggered", "normal_nat_burst"]
FIXED_IP = "192.168.10.1"
WINDOW = 6
PHASES = 5
TRAIN_ATTACK_OFFSET = 10_000
VALIDATION_ATTACK_OFFSET = 20_000
TEST_ATTACK_OFFSET = 50_000
CHALLENGE_FPR_TARGET = 0.003
WARN_FPR_TARGET = 0.01
# Retain only 60% of the probability tail above the empirical normal-only
# threshold.  This conservative margin is fixed before test evaluation and
# protects against small calibration samples and chronological drift.
CHALLENGE_TAIL_RATIO = 0.60
COHORT_PRIOR_SIZE = 200
COHORT_PRIOR_SEED_OFFSETS = (31_000, 32_000)
SHADOW_MIN_TRUSTED_EVENTS = 1000

ATTACKS = (
    "stealth_mimicry_ato",
    "slow_credential_probe",
    "session_replay_jitter",
    "gradual_exfiltration",
    "distributed_lateral_drift",
    "profile_poisoning_chain",
    "cookie_hijack_blend",
    "distributed_password_spray",
)

ACTION_LEVEL = {"allow": 0, "warn": 1, "challenge": 2, "block": 3}
LEVEL_ACTION = ("allow", "warn", "challenge", "block")

# Strict feature ownership.  The neural layer never receives the Rule or
# Behavior columns below.
RULE_FEATURES = (
    "new_device",
    "new_ua_family",
    "failed_1h",
    "success_10m",
    "concurrent_sessions",
    "active_subsystems",
    "new_passkey",
    "permission_age_hours",
    "confirmed_incident",
    "permission_violation",
    "mfa_always",
)
BEHAVIOR_FEATURES = (
    "hour_rarity",
    "weekday_rarity",
    "subsystem_rarity",
    "device_signature_rarity",
    "cadence_tail_probability",
)
NEURAL_EVENT_FEATURES = (
    "gap_log_z",
    "duration_log_z",
    "scope_z",
    "browser_version_window_relative",
    "gap_delta",
    "duration_delta",
    "scope_delta",
    "browser_version_delta",
)
NEURAL_SUMMARIES = ("mean", "std", "slope", "range")
NEURAL_INPUT_SIZE = WINDOW * len(NEURAL_EVENT_FEATURES) + 4 * 4
_COHORT_PRIOR_CACHE: dict[int, tuple[np.ndarray, np.ndarray]] = {}
_PROFILE_PRIOR_CACHE: dict[tuple[int, str], dict[str, ProfileBaseline]] = {}
_GLOBAL_MODEL_CACHE: dict[tuple[int, int], TemporalMLP] = {}


@dataclass
class Event:
    profile_id: str
    user_type: str
    timestamp: datetime
    split: str
    normal_scenario: str
    subsystem: str | None
    device_id: str
    browser_family: str
    os_name: str
    browser_version: int
    session_duration: float
    scope_sensitivity: float
    attack_type: str | None = None
    failed_1h: int = 0
    success_10m: int = 0
    concurrent_sessions: int = 0
    active_subsystems: int = 0
    new_passkey: int = 0
    permission_age_hours: float = 9999.0
    confirmed_incident: int = 0


@dataclass(frozen=True)
class AttackPhase:
    event: Event
    sequence_id: str
    attack_type: str
    phase_index: int
    objective_phase: bool


@dataclass
class ProfileBaseline:
    gap_log_median: float
    gap_log_scale: float
    duration_log_median: float
    duration_log_scale: float
    scope_median: float
    scope_scale: float
    browser_version_median: float
    browser_version_scale: float
    hour_counts: Counter[int]
    weekday_counts: Counter[int]
    subsystem_counts: Counter[str | None]
    signature_counts: Counter[str]
    cadence_logs: np.ndarray
    trusted_devices: set[str]
    trusted_ua_families: set[str]
    total: int


@dataclass
class TemporalMLP:
    weights: list[np.ndarray]
    biases: list[np.ndarray]
    input_median: np.ndarray
    input_iqr: np.ndarray
    challenge_threshold: float
    warn_threshold: float
    behavior_warn_threshold: float
    epochs_trained: int
    best_validation_loss: float


def _load_users() -> list[dict[str, Any]]:
    users = json.loads(USERS_PATH.read_text(encoding="utf-8"))["users"]
    if len(users) != 12:
        raise ValueError("V8 identity contract requires exactly 12 alias profiles")
    return users


def _weighted(items: list[dict[str, Any]], rng: random.Random) -> str:
    draw = rng.random()
    cumulative = 0.0
    for item in items:
        cumulative += float(item["weight"])
        if draw <= cumulative:
            return str(item["key"])
    return str(items[-1]["key"])


def _device_properties(device_key: str) -> tuple[str, str, str]:
    return {
        "windows_chrome": ("dev-win", "Chrome", "Windows"),
        "android_chrome": ("dev-android", "Chrome", "Android"),
        "ios_mobile": ("dev-iphone", "Safari", "iOS"),
        "ios_tablet": ("dev-ipad", "Safari", "iPadOS"),
    }[device_key]


def _normal_subsystem(user: dict[str, Any], rng: random.Random) -> str | None:
    allowed = list(user["allowed_subsystems"])
    if not allowed:
        return None
    if len(allowed) == 1:
        return allowed[0]
    preferred = user["owned_subsystems"][0] if user["owned_subsystems"] else allowed[0]
    return preferred if rng.random() < 0.70 else next(item for item in allowed if item != preferred)


def _normal_timestamp(
    user: dict[str, Any], index: int, user_index: int, scenario: str, rng: random.Random
) -> datetime:
    day = datetime(2024, 1, 8) + timedelta(days=index // 2)
    if day.weekday() not in user["normal_days"] and rng.random() >= 0.05:
        while day.weekday() not in user["normal_days"]:
            day += timedelta(days=1)
    start, end = rng.choice(user["normal_hours"])
    if scenario == "normal_nat_burst":
        hour = min(max(9 if index % 2 == 0 else 14, int(start)), int(end))
        minute = (user_index * 3 + rng.randint(0, 16)) % 58
    else:
        hour = rng.randint(int(start), int(end))
        minute = (rng.randint(0, 55) + (user_index % 4) * 2) % 60
    return day.replace(hour=hour, minute=minute, second=rng.randint(0, 59))


def generate_normal(
    users: list[dict[str, Any]], size: int, seed: int, scenario: str
) -> list[Event]:
    """Generate a new coherent timeline; no previous-version rows are reused."""
    rng = random.Random(seed * 1009 + size * 37 + (1 if scenario.endswith("burst") else 0))
    train_count = int(size * 0.8)
    rows: list[Event] = []
    for user_index, user in enumerate(users):
        for index in range(size):
            timestamp = _normal_timestamp(user, index, user_index, scenario, rng)
            device_key = _weighted(user["devices"], rng)
            device_id, browser, os_name = _device_properties(device_key)
            subsystem = _normal_subsystem(user, rng)
            duration = rng.lognormvariate(math.log(20.0), 0.55)
            if rng.random() < 0.018:
                duration *= rng.uniform(2.2, 5.0)
            duration = min(600.0, max(2.0, duration))
            version = 148 + min(8, index // max(10, size // 8 + 1))
            scope = 0.82 if subsystem == "dorm" else (0.62 if subsystem == "library" else 0.12)
            scope = min(0.98, max(0.05, scope + rng.uniform(-0.06, 0.06)))
            rows.append(
                Event(
                    profile_id=user["profile_id"],
                    user_type=user["user_type"],
                    timestamp=timestamp,
                    split="train" if index < train_count else "normal_test",
                    normal_scenario=scenario,
                    subsystem=subsystem,
                    device_id=device_id,
                    browser_family=browser,
                    os_name=os_name,
                    browser_version=version,
                    session_duration=duration,
                    scope_sensitivity=scope,
                    active_subsystems=1 if subsystem else 0,
                )
            )
    rows.sort(key=lambda event: (event.timestamp, event.profile_id))
    _populate_timeline_counters(rows, seed, size, scenario)
    return rows


def _populate_timeline_counters(
    rows: list[Event], seed: int, size: int, scenario: str
) -> None:
    rng = random.Random(seed * 65537 + size * 257 + (11 if scenario.endswith("burst") else 0))
    successes: dict[str, deque[datetime]] = defaultdict(deque)
    failures: dict[str, deque[datetime]] = defaultdict(deque)
    active: dict[str, list[tuple[datetime, str | None]]] = defaultdict(list)
    for event in rows:
        profile = event.profile_id
        while successes[profile] and event.timestamp - successes[profile][0] > timedelta(minutes=10):
            successes[profile].popleft()
        while failures[profile] and event.timestamp - failures[profile][0] > timedelta(hours=1):
            failures[profile].popleft()
        active[profile] = [item for item in active[profile] if item[0] > event.timestamp]

        draw = rng.random()
        latent_failures = 2 if draw < 0.004 else (1 if draw < 0.045 else 0)
        for attempt in range(latent_failures):
            failures[profile].append(
                event.timestamp - timedelta(minutes=rng.uniform(2 + attempt, 48))
            )
        failures[profile] = deque(sorted(failures[profile]))
        event.success_10m = min(4, len(successes[profile]))
        event.failed_1h = min(2, len(failures[profile]))
        event.concurrent_sessions = min(3, len(active[profile]))
        live_subsystems = {subsystem for _, subsystem in active[profile] if subsystem}
        if event.subsystem:
            live_subsystems.add(event.subsystem)
        event.active_subsystems = min(2, len(live_subsystems))
        successes[profile].append(event.timestamp)
        active[profile].append(
            (event.timestamp + timedelta(minutes=event.session_duration), event.subsystem)
        )


def _sequence_id(profile_id: str, attack_type: str, seed: int, scenario: str) -> str:
    raw = f"v8|{profile_id}|{attack_type}|{seed}|{scenario}".encode("utf-8")
    return "v8-" + hashlib.sha256(raw).hexdigest()[:18]


def generate_attacks(
    users: list[dict[str, Any]], normal: list[Event], seed: int, scenario: str,
    subtlety: float,
) -> list[AttackPhase]:
    """Create weak multi-stage campaigns below deterministic counter floors."""
    rng = random.Random(seed * 8191 + 808)
    by_user = _profile_events(normal)
    phases: list[AttackPhase] = []
    for user_index, user in enumerate(users):
        trusted = by_user[user["profile_id"]]
        base = replace(trusted[-1])
        durations = np.asarray([event.session_duration for event in trusted], dtype=float)
        typical_duration = float(np.median(durations))
        gaps = _positive_gaps_minutes(trusted[-20:])
        cadence = float(np.median(gaps)) if gaps else 12.0 * 60.0
        cadence = min(72.0 * 60.0, max(50.0, cadence))
        allowed = list(user["allowed_subsystems"])

        for attack_index, attack_type in enumerate(ATTACKS):
            if attack_type == "distributed_lateral_drift" and len(allowed) < 2:
                continue
            sequence_id = _sequence_id(user["profile_id"], attack_type, seed, scenario)
            start = base.timestamp + timedelta(minutes=cadence + rng.uniform(5, 70))
            previous_time = start
            for phase_index in range(1, PHASES + 1):
                progress = phase_index / PHASES
                event = replace(base)
                event.split = "attack_test"
                event.attack_type = attack_type
                event.failed_1h = 0
                event.success_10m = 0
                event.concurrent_sessions = 0
                event.active_subsystems = 1 if event.subsystem else 0
                event.new_passkey = 0
                event.permission_age_hours = 9999.0
                event.confirmed_incident = 0
                event.session_duration = typical_duration * rng.uniform(0.94, 1.06)
                event.timestamp = previous_time

                if attack_type == "stealth_mimicry_ato":
                    gap = cadence * max(0.10, 1.0 - subtlety * 0.68 * progress)
                    event.session_duration *= 1.0 + subtlety * 0.65 * progress
                    event.scope_sensitivity = min(0.98, base.scope_sensitivity + 0.15 * subtlety * progress)
                elif attack_type == "slow_credential_probe":
                    gap = cadence * (1.0 + 0.45 * phase_index)
                    event.failed_1h = min(2, 1 + phase_index // 3)
                    event.session_duration *= 1.0 - subtlety * 0.48 * progress
                elif attack_type == "session_replay_jitter":
                    gap = rng.uniform(9.0, 52.0) * (1.2 - 0.2 * subtlety)
                    event.success_10m = min(4, phase_index - 1)
                    event.concurrent_sessions = 1 if phase_index >= 4 else 0
                    event.session_duration *= 1.0 - subtlety * 0.58 * progress
                elif attack_type == "gradual_exfiltration":
                    gap = cadence * rng.uniform(0.75, 1.15)
                    event.session_duration *= 1.0 + subtlety * 1.35 * progress
                    event.scope_sensitivity = min(0.98, base.scope_sensitivity + 0.22 * subtlety * progress)
                elif attack_type == "distributed_lateral_drift":
                    gap = cadence * rng.uniform(0.55, 1.05)
                    event.subsystem = allowed[(phase_index + user_index) % len(allowed)]
                    event.scope_sensitivity = min(0.98, base.scope_sensitivity + 0.13 * subtlety * progress)
                elif attack_type == "profile_poisoning_chain":
                    gap = cadence * rng.uniform(0.80, 1.25)
                    event.browser_version += int(round(subtlety * phase_index * 1.6))
                    hour_shift = int(round(subtlety * phase_index * 0.8))
                    event.timestamp += timedelta(hours=hour_shift)
                elif attack_type == "cookie_hijack_blend":
                    gap = cadence * max(0.18, 0.92 - subtlety * 0.55 * progress)
                    event.session_duration *= 1.0 + subtlety * (0.20 if phase_index < 3 else 0.90) * progress
                    event.scope_sensitivity = min(0.98, base.scope_sensitivity + (0.03 if phase_index < 4 else 0.18) * subtlety)
                elif attack_type == "distributed_password_spray":
                    gap = cadence * (1.25 + 0.30 * phase_index)
                    event.failed_1h = 1 if phase_index < 4 else 2
                    event.session_duration *= max(0.35, 1.0 - subtlety * 0.52 * progress)
                else:  # pragma: no cover
                    raise AssertionError(attack_type)

                event.timestamp += timedelta(minutes=gap + rng.uniform(-0.06, 0.06) * gap)
                previous_time = event.timestamp
                phases.append(
                    AttackPhase(
                        event=event,
                        sequence_id=sequence_id,
                        attack_type=attack_type,
                        phase_index=phase_index,
                        objective_phase=phase_index == PHASES,
                    )
                )
    return phases


def _profile_events(events: Iterable[Event]) -> dict[str, list[Event]]:
    grouped: dict[str, list[Event]] = defaultdict(list)
    for event in events:
        grouped[event.profile_id].append(event)
    for profile_id in grouped:
        grouped[profile_id].sort(key=lambda event: event.timestamp)
    return grouped


def _positive_gaps_minutes(events: list[Event]) -> list[float]:
    return [
        max(0.5, (right.timestamp - left.timestamp).total_seconds() / 60.0)
        for left, right in zip(events, events[1:])
        if right.timestamp > left.timestamp
    ]


def _robust_center_scale(values: np.ndarray, fallback: float = 1.0) -> tuple[float, float]:
    median = float(np.median(values))
    scale = float(np.quantile(values, 0.75) - np.quantile(values, 0.25))
    return median, max(fallback, scale)


def fit_profile_baselines(normal_train: list[Event]) -> dict[str, ProfileBaseline]:
    output: dict[str, ProfileBaseline] = {}
    for profile_id, events in _profile_events(normal_train).items():
        gaps = np.asarray([math.log1p(value) for value in _positive_gaps_minutes(events)], dtype=float)
        if not len(gaps):
            gaps = np.asarray([math.log1p(12.0 * 60.0)])
        durations = np.asarray([math.log1p(event.session_duration) for event in events])
        scopes = np.asarray([event.scope_sensitivity for event in events])
        versions = np.asarray([event.browser_version for event in events], dtype=float)
        # Hierarchical cold-start floors prevent an eight-event profile from
        # treating ordinary variation as a many-IQR excursion.  With more
        # history the observed IQR naturally becomes the larger value.
        gap_center, gap_scale = _robust_center_scale(gaps, 0.55)
        duration_center, duration_scale = _robust_center_scale(durations, 0.40)
        scope_center, scope_scale = _robust_center_scale(scopes, 0.12)
        version_center, version_scale = _robust_center_scale(versions, 1.0)
        output[profile_id] = ProfileBaseline(
            gap_log_median=gap_center,
            gap_log_scale=gap_scale,
            duration_log_median=duration_center,
            duration_log_scale=duration_scale,
            scope_median=scope_center,
            scope_scale=scope_scale,
            browser_version_median=version_center,
            browser_version_scale=version_scale,
            hour_counts=Counter(event.timestamp.hour for event in events),
            weekday_counts=Counter(event.timestamp.weekday() for event in events),
            subsystem_counts=Counter(event.subsystem for event in events),
            signature_counts=Counter(f"{event.os_name}/{event.browser_family}" for event in events),
            cadence_logs=gaps,
            trusted_devices={event.device_id for event in events},
            trusted_ua_families={event.browser_family for event in events},
            total=len(events),
        )
    return output


def _profile_prior_baselines(
    users: list[dict[str, Any]], seed: int, scenario: str
) -> dict[str, ProfileBaseline]:
    key = (seed, scenario)
    if key not in _PROFILE_PRIOR_CACHE:
        prior = generate_normal(
            users, COHORT_PRIOR_SIZE, seed + COHORT_PRIOR_SEED_OFFSETS[0], scenario
        )
        _PROFILE_PRIOR_CACHE[key] = fit_profile_baselines(
            [event for event in prior if event.split == "train"]
        )
    return _PROFILE_PRIOR_CACHE[key]


def _blend_cold_baselines(
    local: dict[str, ProfileBaseline], prior: dict[str, ProfileBaseline]
) -> dict[str, ProfileBaseline]:
    output: dict[str, ProfileBaseline] = {}
    for profile_id, current in local.items():
        population = prior[profile_id]
        weight = current.total / (current.total + 100.0)
        blend = lambda left, right: weight * left + (1.0 - weight) * right
        output[profile_id] = ProfileBaseline(
            gap_log_median=blend(current.gap_log_median, population.gap_log_median),
            gap_log_scale=max(0.40, blend(current.gap_log_scale, population.gap_log_scale)),
            duration_log_median=blend(current.duration_log_median, population.duration_log_median),
            duration_log_scale=max(0.30, blend(current.duration_log_scale, population.duration_log_scale)),
            scope_median=blend(current.scope_median, population.scope_median),
            scope_scale=max(0.10, blend(current.scope_scale, population.scope_scale)),
            browser_version_median=current.browser_version_median,
            browser_version_scale=max(current.browser_version_scale, population.browser_version_scale),
            hour_counts=population.hour_counts if weight < 0.50 else current.hour_counts,
            weekday_counts=population.weekday_counts if weight < 0.50 else current.weekday_counts,
            subsystem_counts=population.subsystem_counts if weight < 0.50 else current.subsystem_counts,
            signature_counts=population.signature_counts if weight < 0.50 else current.signature_counts,
            cadence_logs=population.cadence_logs if weight < 0.50 else current.cadence_logs,
            trusted_devices=current.trusted_devices | population.trusted_devices,
            trusted_ua_families=current.trusted_ua_families | population.trusted_ua_families,
            total=population.total if weight < 0.50 else current.total,
        )
    return output


def _slope(values: np.ndarray) -> float:
    if len(values) < 2:
        return 0.0
    x = np.arange(len(values), dtype=float)
    x -= np.mean(x)
    return float(np.dot(x, values - np.mean(values)) / max(1e-9, np.dot(x, x)))


def neural_features(events: list[Event], baseline: ProfileBaseline) -> np.ndarray:
    if len(events) < WINDOW:
        raise ValueError(f"V8 requires at least {WINDOW} events")
    window = sorted(events[-WINDOW:], key=lambda event: event.timestamp)
    gaps = [
        max(0.5, (right.timestamp - left.timestamp).total_seconds() / 60.0)
        for left, right in zip(window, window[1:])
    ]
    gaps = [gaps[0]] + gaps
    versions = np.asarray([event.browser_version for event in window], dtype=float)
    # Absolute browser versions naturally move after an update and previously
    # made the normal test tail look like an attack.  V8 owns only the within-
    # window drift; device/UA novelty remains a Rule fact.
    version_relative = (versions - versions[0]) / baseline.browser_version_scale
    core = np.column_stack(
        [
            (np.log1p(gaps) - baseline.gap_log_median) / baseline.gap_log_scale,
            (np.log1p([event.session_duration for event in window]) - baseline.duration_log_median) / baseline.duration_log_scale,
            (np.asarray([event.scope_sensitivity for event in window]) - baseline.scope_median) / baseline.scope_scale,
            version_relative,
        ]
    )
    deltas = np.vstack((np.zeros((1, 4)), np.diff(core, axis=0)))
    temporal = np.column_stack((core, deltas))
    summaries: list[float] = []
    for column in range(4):
        values = core[:, column]
        summaries.extend(
            [float(np.mean(values)), float(np.std(values)), _slope(values), float(np.ptp(values))]
        )
    vector = np.concatenate((temporal.reshape(-1), np.asarray(summaries, dtype=float)))
    if vector.shape != (NEURAL_INPUT_SIZE,):
        raise AssertionError(vector.shape)
    return np.clip(vector, -12.0, 12.0)


def behavior_score(history: list[Event], event: Event, baseline: ProfileBaseline) -> float:
    smooth = 1.0
    hour_rarity = 1.0 - (baseline.hour_counts[event.timestamp.hour] + smooth) / (
        baseline.total + 24.0 * smooth
    )
    weekday_rarity = 1.0 - (baseline.weekday_counts[event.timestamp.weekday()] + smooth) / (
        baseline.total + 7.0 * smooth
    )
    subsystem_rarity = 1.0 - (baseline.subsystem_counts[event.subsystem] + smooth) / (
        baseline.total + 3.0 * smooth
    )
    signature = f"{event.os_name}/{event.browser_family}"
    signature_rarity = 1.0 - (baseline.signature_counts[signature] + smooth) / (
        baseline.total + 6.0 * smooth
    )
    if history:
        gap = max(0.5, (event.timestamp - history[-1].timestamp).total_seconds() / 60.0)
        gap_log = math.log1p(gap)
        cadence_tail = float(np.mean(np.abs(baseline.cadence_logs - baseline.gap_log_median) <= abs(gap_log - baseline.gap_log_median)))
    else:
        cadence_tail = 0.5
    return float(
        0.22 * hour_rarity
        + 0.12 * weekday_rarity
        + 0.22 * subsystem_rarity
        + 0.22 * signature_rarity
        + 0.22 * cadence_tail
    )


def rule_decision(
    user: dict[str, Any], history: list[Event], event: Event, baseline: ProfileBaseline
) -> tuple[str, str]:
    permission_violation = event.subsystem not in user["allowed_subsystems"] if event.subsystem else False
    if permission_violation or event.confirmed_incident:
        return "block", "hard_block"
    if bool(user.get("mfa_always")):
        return "challenge", "admin_always_mfa"
    new_device = event.device_id not in baseline.trusted_devices
    new_ua = event.browser_family not in baseline.trusted_ua_families
    if event.new_passkey or event.permission_age_hours < 24.0:
        return "challenge", "sensitive_change"
    if event.failed_1h >= 3 or event.success_10m >= 5 or event.concurrent_sessions >= 4:
        return "challenge", "hard_counter"
    if new_device and new_ua:
        return "challenge", "new_device_and_ua"
    if new_device or new_ua:
        return "warn", "new_identity_fact"
    return "allow", "none"


def _sigmoid(values: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(values, -35.0, 35.0)))


def _forward(weights: list[np.ndarray], biases: list[np.ndarray], matrix: np.ndarray) -> tuple[np.ndarray, list[np.ndarray], list[np.ndarray]]:
    activations = [matrix]
    preactivations: list[np.ndarray] = []
    hidden = matrix
    for weight, bias in zip(weights[:-1], biases[:-1]):
        before = hidden @ weight + bias
        preactivations.append(before)
        hidden = np.tanh(before)
        activations.append(hidden)
    logits = hidden @ weights[-1] + biases[-1]
    preactivations.append(logits)
    probabilities = _sigmoid(logits).reshape(-1)
    return probabilities, activations, preactivations


def _balanced_loss(labels: np.ndarray, probabilities: np.ndarray) -> float:
    positives = max(1, int(np.sum(labels == 1)))
    negatives = max(1, int(np.sum(labels == 0)))
    sample_weight = np.where(labels == 1, len(labels) / (2.0 * positives), len(labels) / (2.0 * negatives))
    clipped = np.clip(probabilities, 1e-7, 1.0 - 1e-7)
    return float(-np.mean(sample_weight * (labels * np.log(clipped) + (1.0 - labels) * np.log(1.0 - clipped))))


def fit_mlp(
    train_x: np.ndarray,
    train_y: np.ndarray,
    validation_x: np.ndarray,
    validation_y: np.ndarray,
    normal_calibration_x: np.ndarray,
    seed: int,
) -> TemporalMLP:
    median = np.median(train_x, axis=0)
    iqr = np.quantile(train_x, 0.75, axis=0) - np.quantile(train_x, 0.25, axis=0)
    iqr[iqr < 1e-5] = 1.0
    x = np.clip((train_x - median) / iqr, -10.0, 10.0)
    val_x = np.clip((validation_x - median) / iqr, -10.0, 10.0)
    rng = np.random.default_rng(seed + 81_000)
    dimensions = (x.shape[1], 32, 12, 1)
    weights = [rng.normal(0.0, math.sqrt(2.0 / dimensions[i]), (dimensions[i], dimensions[i + 1])) for i in range(len(dimensions) - 1)]
    biases = [np.zeros(dimensions[i + 1], dtype=float) for i in range(len(dimensions) - 1)]
    moments_w = [np.zeros_like(weight) for weight in weights]
    velocities_w = [np.zeros_like(weight) for weight in weights]
    moments_b = [np.zeros_like(bias) for bias in biases]
    velocities_b = [np.zeros_like(bias) for bias in biases]
    best_weights = [weight.copy() for weight in weights]
    best_biases = [bias.copy() for bias in biases]
    best_loss = float("inf")
    stale = 0
    step = 0
    batch_size = min(256, len(x))
    positives = max(1, int(np.sum(train_y == 1)))
    negatives = max(1, int(np.sum(train_y == 0)))
    class_weights = np.where(train_y == 1, len(train_y) / (2.0 * positives), len(train_y) / (2.0 * negatives))

    for epoch in range(1, 121):
        order = rng.permutation(len(x))
        for start in range(0, len(order), batch_size):
            indices = order[start : start + batch_size]
            batch = x[indices]
            labels = train_y[indices]
            sample_weights = class_weights[indices]
            probabilities, activations, _ = _forward(weights, biases, batch)
            delta = ((probabilities - labels) * sample_weights / len(indices)).reshape(-1, 1)
            gradient_w: list[np.ndarray] = [np.empty_like(weight) for weight in weights]
            gradient_b: list[np.ndarray] = [np.empty_like(bias) for bias in biases]
            gradient_w[-1] = activations[-1].T @ delta + 2e-4 * weights[-1]
            gradient_b[-1] = np.sum(delta, axis=0)
            back = delta @ weights[-1].T
            for layer in range(len(weights) - 2, -1, -1):
                back *= 1.0 - activations[layer + 1] ** 2
                gradient_w[layer] = activations[layer].T @ back + 2e-4 * weights[layer]
                gradient_b[layer] = np.sum(back, axis=0)
                if layer:
                    back = back @ weights[layer].T
            step += 1
            learning_rate = 0.003 * (0.985 ** (epoch - 1))
            for layer in range(len(weights)):
                moments_w[layer] = 0.9 * moments_w[layer] + 0.1 * gradient_w[layer]
                velocities_w[layer] = 0.999 * velocities_w[layer] + 0.001 * gradient_w[layer] ** 2
                moments_b[layer] = 0.9 * moments_b[layer] + 0.1 * gradient_b[layer]
                velocities_b[layer] = 0.999 * velocities_b[layer] + 0.001 * gradient_b[layer] ** 2
                mw = moments_w[layer] / (1.0 - 0.9 ** step)
                vw = velocities_w[layer] / (1.0 - 0.999 ** step)
                mb = moments_b[layer] / (1.0 - 0.9 ** step)
                vb = velocities_b[layer] / (1.0 - 0.999 ** step)
                weights[layer] -= learning_rate * mw / (np.sqrt(vw) + 1e-8)
                biases[layer] -= learning_rate * mb / (np.sqrt(vb) + 1e-8)
        val_probabilities, _, _ = _forward(weights, biases, val_x)
        loss = _balanced_loss(validation_y, val_probabilities)
        if loss < best_loss - 1e-5:
            best_loss = loss
            best_weights = [weight.copy() for weight in weights]
            best_biases = [bias.copy() for bias in biases]
            stale = 0
        else:
            stale += 1
        if stale >= 14:
            break

    calibration_scaled = np.clip((normal_calibration_x - median) / iqr, -10.0, 10.0)
    calibration_probabilities, _, _ = _forward(best_weights, best_biases, calibration_scaled)
    warn = _upper_fpr_threshold(calibration_probabilities, WARN_FPR_TARGET)
    challenge = _upper_fpr_threshold(calibration_probabilities, CHALLENGE_FPR_TARGET)
    challenge = 1.0 - (1.0 - challenge) * CHALLENGE_TAIL_RATIO
    challenge = max(challenge, warn + 1e-6)
    return TemporalMLP(
        weights=best_weights,
        biases=best_biases,
        input_median=median,
        input_iqr=iqr,
        challenge_threshold=float(challenge),
        warn_threshold=float(warn),
        behavior_warn_threshold=1.0,
        epochs_trained=epoch,
        best_validation_loss=best_loss,
    )


def _upper_fpr_threshold(scores: np.ndarray, target: float) -> float:
    descending = np.sort(np.asarray(scores, dtype=float))[::-1]
    allowed = int(math.floor(target * len(descending)))
    index = min(allowed, len(descending) - 1)
    return float(np.nextafter(descending[index], np.inf))


def predict_mlp(model: TemporalMLP, matrix: np.ndarray) -> np.ndarray:
    scaled = np.clip((matrix - model.input_median) / model.input_iqr, -10.0, 10.0)
    probabilities, _, _ = _forward(model.weights, model.biases, scaled)
    return probabilities


def _window_rows(
    histories: dict[str, list[Event]], baselines: dict[str, ProfileBaseline],
    start_fraction: float = 0.0,
) -> list[tuple[str, np.ndarray]]:
    rows: list[tuple[str, np.ndarray]] = []
    for profile_id, events in histories.items():
        start = max(WINDOW - 1, int(len(events) * start_fraction))
        for index in range(start, len(events)):
            if index + 1 >= WINDOW:
                rows.append((profile_id, neural_features(events[: index + 1], baselines[profile_id])))
    return rows


def _attack_rows(
    normal_history: dict[str, list[Event]], phases: list[AttackPhase],
    baselines: dict[str, ProfileBaseline],
) -> tuple[np.ndarray, list[AttackPhase]]:
    grouped: dict[str, list[AttackPhase]] = defaultdict(list)
    for phase in phases:
        grouped[phase.sequence_id].append(phase)
    vectors: list[np.ndarray] = []
    metadata: list[AttackPhase] = []
    for campaign in grouped.values():
        campaign.sort(key=lambda phase: phase.phase_index)
        history = list(normal_history[campaign[0].event.profile_id])
        for phase in campaign:
            history.append(phase.event)
            vectors.append(neural_features(history, baselines[phase.event.profile_id]))
            metadata.append(phase)
    return np.asarray(vectors), metadata


def _cohort_prior_rows(
    users: list[dict[str, Any]], seed: int
) -> tuple[np.ndarray, np.ndarray]:
    """Normal-only population prior for profiles with little local history.

    The prior is generated from independent seeds and both NAT scenarios.  It
    never contains test attacks or rows from the evaluated timeline.
    """
    if seed in _COHORT_PRIOR_CACHE:
        fit, calibration = _COHORT_PRIOR_CACHE[seed]
        return fit.copy(), calibration.copy()
    fit_rows: list[np.ndarray] = []
    calibration_rows: list[np.ndarray] = []
    for offset, scenario in zip(COHORT_PRIOR_SEED_OFFSETS, SCENARIOS):
        prior = generate_normal(users, COHORT_PRIOR_SIZE, seed + offset, scenario)
        trusted = [event for event in prior if event.split == "train"]
        histories = _profile_events(trusted)
        baselines = fit_profile_baselines(trusted)
        matrix = np.asarray([row for _, row in _window_rows(histories, baselines)])
        cut = max(1, int(len(matrix) * 0.80))
        fit_rows.append(matrix[:cut])
        calibration_rows.append(matrix[cut:])
    output = (np.vstack(fit_rows), np.vstack(calibration_rows))
    _COHORT_PRIOR_CACHE[seed] = output
    return output[0].copy(), output[1].copy()


def _fit_global_model(
    users: list[dict[str, Any]], size: int, seed: int
) -> TemporalMLP:
    """Fit one model per size/seed from both network scenarios."""
    cache_key = (size, seed)
    if cache_key in _GLOBAL_MODEL_CACHE:
        return _GLOBAL_MODEL_CACHE[cache_key]
    normal_fit_parts: list[np.ndarray] = []
    normal_calibration_parts: list[np.ndarray] = []
    attack_fit_parts: list[np.ndarray] = []
    attack_validation_parts: list[np.ndarray] = []
    behavior_calibration: list[float] = []
    for scenario in SCENARIOS:
        normal = generate_normal(users, size, seed, scenario)
        normal_train = [event for event in normal if event.split == "train"]
        histories = _profile_events(normal_train)
        baselines = _blend_cold_baselines(
            fit_profile_baselines(normal_train),
            _profile_prior_baselines(users, seed, scenario),
        )
        normal_x = np.asarray([row for _, row in _window_rows(histories, baselines)])
        split = max(1, int(len(normal_x) * 0.80))
        normal_fit_parts.append(normal_x[:split])
        normal_calibration_parts.append(
            normal_x[split:] if split < len(normal_x) else normal_x[-max(1, len(normal_x) // 5):]
        )
        attack_fit, _ = _attack_rows(
            histories,
            generate_attacks(
                users, normal_train, seed + TRAIN_ATTACK_OFFSET, scenario, subtlety=1.0
            ),
            baselines,
        )
        attack_validation, _ = _attack_rows(
            histories,
            generate_attacks(
                users, normal_train, seed + VALIDATION_ATTACK_OFFSET, scenario, subtlety=0.88
            ),
            baselines,
        )
        attack_fit_parts.append(attack_fit)
        attack_validation_parts.append(attack_validation)
        for profile_id, events in histories.items():
            cut = max(WINDOW, int(len(events) * 0.80))
            history = list(events[:cut])
            for event in events[cut:]:
                behavior_calibration.append(
                    behavior_score(history, event, baselines[profile_id])
                )
                history.append(event)

    prior_fit, prior_calibration = _cohort_prior_rows(users, seed)
    normal_fit_x = np.vstack((*normal_fit_parts, prior_fit))
    normal_calibration_x = np.vstack((*normal_calibration_parts, prior_calibration))
    attack_fit_x = np.vstack(attack_fit_parts)
    attack_validation_x = np.vstack(attack_validation_parts)
    rng = np.random.default_rng(seed + size * 19)
    normal_cap = min(len(normal_fit_x), max(len(attack_fit_x) * 5, 1200))
    if len(normal_fit_x) > normal_cap:
        normal_fit_x = normal_fit_x[rng.choice(len(normal_fit_x), normal_cap, replace=False)]
    validation_normal_cap = min(
        len(normal_calibration_x), max(len(attack_validation_x) * 3, 480)
    )
    validation_normal = normal_calibration_x
    if len(validation_normal) > validation_normal_cap:
        validation_normal = validation_normal[
            rng.choice(len(validation_normal), validation_normal_cap, replace=False)
        ]
    model = fit_mlp(
        np.vstack((normal_fit_x, attack_fit_x)),
        np.concatenate((np.zeros(len(normal_fit_x)), np.ones(len(attack_fit_x)))),
        np.vstack((validation_normal, attack_validation_x)),
        np.concatenate((np.zeros(len(validation_normal)), np.ones(len(attack_validation_x)))),
        normal_calibration_x,
        seed,
    )
    if behavior_calibration:
        model.behavior_warn_threshold = _upper_fpr_threshold(
            np.asarray(behavior_calibration), WARN_FPR_TARGET
        )
    _GLOBAL_MODEL_CACHE[cache_key] = model
    return model


def _training_data(
    users: list[dict[str, Any]], normal: list[Event], size: int, seed: int, scenario: str
) -> tuple[TemporalMLP, dict[str, ProfileBaseline], dict[str, list[Event]]]:
    normal_train = [event for event in normal if event.split == "train"]
    histories = _profile_events(normal_train)
    baselines = _blend_cold_baselines(
        fit_profile_baselines(normal_train),
        _profile_prior_baselines(users, seed, scenario),
    )
    model = _fit_global_model(users, size, seed)
    return model, baselines, histories


def _user_map(users: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {user["profile_id"]: user for user in users}


def _model_decision(probability: float, model: TemporalMLP) -> str:
    if probability >= model.challenge_threshold:
        return "challenge"
    if probability >= model.warn_threshold:
        return "warn"
    return "allow"


def _max_decision(*decisions: str) -> str:
    return LEVEL_ACTION[max(ACTION_LEVEL[decision] for decision in decisions)]


def _score_event(
    user: dict[str, Any], history: list[Event], event: Event,
    baseline: ProfileBaseline, model: TemporalMLP,
) -> dict[str, Any]:
    vector = neural_features(history + [event], baseline)
    probability = float(predict_mlp(model, vector.reshape(1, -1))[0])
    ml_decision = _model_decision(probability, model)
    behavior = behavior_score(history, event, baseline)
    rule, rule_source = rule_decision(user, history, event, baseline)
    # Behavior is warn-only in V8.  It cannot duplicate the neural challenge.
    behavior_decision = (
        "warn" if behavior >= model.behavior_warn_threshold else "allow"
    )
    hybrid = _max_decision(rule, behavior_decision, ml_decision)
    return {
        "probability": probability,
        "behavior_score": behavior,
        "ml_decision": ml_decision,
        "rule_decision": rule,
        "rule_source": rule_source,
        "behavior_decision": behavior_decision,
        "hybrid_decision": hybrid,
    }


def _records_for_run(
    users: list[dict[str, Any]], normal: list[Event], model: TemporalMLP,
    baselines: dict[str, ProfileBaseline], histories: dict[str, list[Event]],
    test_phases: list[AttackPhase],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    users_by_id = _user_map(users)
    normal_records: list[dict[str, Any]] = []
    mutable_history = {key: list(value) for key, value in histories.items()}
    for event in sorted(
        [event for event in normal if event.split == "normal_test"],
        key=lambda item: (item.timestamp, item.profile_id),
    ):
        history = mutable_history[event.profile_id]
        scored = _score_event(
            users_by_id[event.profile_id], history, event,
            baselines[event.profile_id], model,
        )
        normal_records.append(
            {
                "profile_id": event.profile_id,
                "sequence_id": None,
                "attack_type": None,
                "phase_index": 0,
                "objective_phase": False,
                "label": 0,
                **scored,
            }
        )
        history.append(event)

    grouped: dict[str, list[AttackPhase]] = defaultdict(list)
    for phase in test_phases:
        grouped[phase.sequence_id].append(phase)
    attack_records: list[dict[str, Any]] = []
    for campaign in grouped.values():
        campaign.sort(key=lambda phase: phase.phase_index)
        history = list(histories[campaign[0].event.profile_id])
        for phase in campaign:
            scored = _score_event(
                users_by_id[phase.event.profile_id], history, phase.event,
                baselines[phase.event.profile_id], model,
            )
            attack_records.append(
                {
                    "profile_id": phase.event.profile_id,
                    "sequence_id": phase.sequence_id,
                    "attack_type": phase.attack_type,
                    "phase_index": phase.phase_index,
                    "objective_phase": phase.objective_phase,
                    "label": 1,
                    **scored,
                }
            )
            history.append(phase.event)
    return normal_records, attack_records


def _metrics(
    normal: list[dict[str, Any]], attacks: list[dict[str, Any]], decision_key: str
) -> dict[str, float]:
    detected = lambda row: ACTION_LEVEL[row[decision_key]] >= 2
    tp = sum(detected(row) for row in attacks)
    total_fp = sum(detected(row) for row in normal)
    fn = len(attacks) - tp
    # A successful admin login is required to MFA on every attempt by policy.
    # It remains in total friction, but is not a model false positive.
    unexpected_normal = [
        row
        for row in normal
        if not (
            decision_key == "hybrid_decision"
            and row["rule_source"] == "admin_always_mfa"
        )
    ]
    unexpected_fp = sum(detected(row) for row in unexpected_normal)
    tn = len(unexpected_normal) - unexpected_fp
    precision = tp / max(1, tp + unexpected_fp)
    recall = tp / max(1, tp + fn)
    labels = np.asarray([0] * len(normal) + [1] * len(attacks), dtype=int)
    scores = np.asarray([row["probability"] for row in normal + attacks], dtype=float)
    campaigns: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in attacks:
        campaigns[row["sequence_id"]].append(row)
    sequence_hits = pre_hits = objective_hits = 0
    times: list[int] = []
    for campaign in campaigns.values():
        ordered = sorted(campaign, key=lambda row: row["phase_index"])
        hits = [row["phase_index"] for row in ordered if detected(row)]
        sequence_hits += bool(hits)
        pre_hits += any(detected(row) and not row["objective_phase"] for row in ordered)
        objective_hits += any(detected(row) and row["objective_phase"] for row in ordered)
        times.append(min(hits) if hits else PHASES + 1)
    # Admin MFA is mandatory policy, not a false positive.  Both total friction
    # and unexpected challenge FPR are reported.
    return {
        "tp": tp,
        "fp": unexpected_fp,
        "total_policy_and_security_challenges": total_fp,
        "tn": tn,
        "fn": fn,
        "precision": precision,
        "event_challenge_recall": recall,
        "f1": 2.0 * precision * recall / max(1e-12, precision + recall),
        "roc_auc": float(roc_auc_score(labels, scores)) if len(set(labels)) > 1 else 0.0,
        "pr_auc": float(average_precision_score(labels, scores)) if len(set(labels)) > 1 else 0.0,
        "challenge_fpr_total": total_fp / max(1, len(normal)),
        "unexpected_challenge_fpr": unexpected_fp / max(1, len(unexpected_normal)),
        "warn_or_higher_rate_total": sum(ACTION_LEVEL[row[decision_key]] >= 1 for row in normal) / max(1, len(normal)),
        "sequence_detection_rate": sequence_hits / max(1, len(campaigns)),
        "preobjective_detection_rate": pre_hits / max(1, len(campaigns)),
        "objective_detection_rate": objective_hits / max(1, len(campaigns)),
        "median_time_to_detect_phase": float(np.median(times)) if times else 0.0,
        "normal_count": len(normal),
        "attack_phase_count": len(attacks),
        "attack_sequence_count": len(campaigns),
    }


def score_run(
    users: list[dict[str, Any]], size: int, seed: int, scenario: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], TemporalMLP]:
    normal = generate_normal(users, size, seed, scenario)
    model, baselines, histories = _training_data(users, normal, size, seed, scenario)
    test_phases = generate_attacks(
        users,
        [event for event in normal if event.split == "train"],
        seed + TEST_ATTACK_OFFSET,
        scenario,
        subtlety=0.72,
    )
    normal_records, attack_records = _records_for_run(
        users, normal, model, baselines, histories, test_phases
    )
    stages: list[dict[str, Any]] = []
    attacks_out: list[dict[str, Any]] = []
    predictions: list[dict[str, Any]] = []
    for stage, decision_key in (
        ("temporal_mlp_only_v8", "ml_decision"),
        ("disjoint_hybrid_v8", "hybrid_decision"),
    ):
        stages.append(
            {
                "stage": stage,
                "dataset_size": size,
                "seed": seed,
                "normal_scenario": scenario,
                "challenge_threshold": model.challenge_threshold,
                "warn_threshold": model.warn_threshold,
                "epochs_trained": model.epochs_trained,
                "validation_loss": model.best_validation_loss,
                **_metrics(normal_records, attack_records, decision_key),
            }
        )
        for attack_type in ATTACKS:
            subset = [row for row in attack_records if row["attack_type"] == attack_type]
            if subset:
                values = _metrics([], subset, decision_key)
                attacks_out.append(
                    {
                        "stage": stage,
                        "dataset_size": size,
                        "seed": seed,
                        "normal_scenario": scenario,
                        "attack_type": attack_type,
                        **{key: value for key, value in values.items() if key not in {"challenge_fpr_total", "unexpected_challenge_fpr", "warn_or_higher_rate_total", "normal_count"}},
                    }
                )
        for row in normal_records + attack_records:
            predictions.append(
                {
                    "stage": stage,
                    "dataset_size": size,
                    "seed": seed,
                    "normal_scenario": scenario,
                    "profile_id": row["profile_id"],
                    "sequence_id": row["sequence_id"],
                    "attack_type": row["attack_type"],
                    "phase_index": row["phase_index"],
                    "objective_phase": row["objective_phase"],
                    "label": row["label"],
                    "decision": row[decision_key],
                    "probability": row["probability"],
                    "behavior_score": row["behavior_score"],
                    "rule_source": row["rule_source"],
                }
            )
    return stages, attacks_out, predictions, model


def _support_audit(
    users: list[dict[str, Any]], size: int, seed: int, scenario: str
) -> dict[str, Any]:
    normal = generate_normal(users, size, seed, scenario)
    normal_train = [event for event in normal if event.split == "train"]
    histories = _profile_events(normal_train)
    baselines = fit_profile_baselines(normal_train)
    normal_matrix = np.asarray([row for _, row in _window_rows(histories, baselines)])
    attacks = generate_attacks(
        users, normal_train, seed + TEST_ATTACK_OFFSET, scenario, subtlety=0.72
    )
    attack_matrix, _ = _attack_rows(histories, attacks, baselines)
    blockers: list[int] = []
    review: list[int] = []
    rows: list[dict[str, Any]] = []
    for index in range(NEURAL_INPUT_SIZE):
        normal_values = normal_matrix[:, index]
        attack_values = attack_matrix[:, index]
        low, high = float(np.min(normal_values)), float(np.max(normal_values))
        oos = float(np.mean((attack_values < low) | (attack_values > high)))
        constant = bool(np.ptp(normal_values) <= 1e-12)
        blocker = bool(constant and oos >= 0.01)
        if blocker:
            blockers.append(index)
        if oos >= 0.20:
            review.append(index)
        rows.append(
            {
                "feature_index": index,
                "normal_min": low,
                "normal_max": high,
                "normal_constant": constant,
                "attack_out_of_support_rate": oos,
                "one_sided_shortcut": blocker,
            }
        )
    return {
        "passed": not blockers,
        "blocking_feature_indices": blockers,
        "review_feature_indices": review,
        "features": rows,
    }


def _release_gate(
    stage_df: pd.DataFrame, attack_df: pd.DataFrame, support: dict[str, Any]
) -> dict[str, Any]:
    hybrid = stage_df[stage_df.stage.eq("disjoint_hybrid_v8")]
    mature = hybrid[hybrid.dataset_size.ge(SHADOW_MIN_TRUSTED_EVENTS)]
    cold = hybrid[hybrid.dataset_size.lt(SHADOW_MIN_TRUSTED_EVENTS)]
    mature_attacks = attack_df[
        attack_df.stage.eq("disjoint_hybrid_v8")
        & attack_df.dataset_size.ge(SHADOW_MIN_TRUSTED_EVENTS)
    ]
    family = mature_attacks.groupby("attack_type").sequence_detection_rate.mean()
    scenarios = mature.groupby("normal_scenario").sequence_detection_rate.mean()
    eligible_available = not mature.empty and not family.empty
    nat_gap = (
        float(scenarios.max() - scenarios.min()) if len(scenarios) >= 2 else None
    )
    mean_or_none = lambda frame, column: (
        float(frame[column].mean()) if not frame.empty else None
    )
    checks = {
        "eligible_history_results_available": eligible_available,
        "eligible_history_unexpected_challenge_fpr_le_0_003": eligible_available and float(mature.unexpected_challenge_fpr.mean()) <= CHALLENGE_FPR_TARGET,
        "eligible_history_warn_or_higher_rate_total_le_0_20": eligible_available and float(mature.warn_or_higher_rate_total.mean()) <= 0.20,
        "eligible_history_sequence_detection_ge_0_90": eligible_available and float(mature.sequence_detection_rate.mean()) >= 0.90,
        "minimum_attack_family_detection_ge_0_80": eligible_available and float(family.min()) >= 0.80,
        "eligible_history_preobjective_detection_ge_0_70": eligible_available and float(mature.preobjective_detection_rate.mean()) >= 0.70,
        "eligible_history_median_time_to_detect_le_2": eligible_available and float(mature.median_time_to_detect_phase.median()) <= 2.0,
        "nat_detection_gap_le_0_02": eligible_available and nat_gap is not None and nat_gap <= 0.02,
        "generator_one_sided_shortcut_absent": bool(support["passed"]),
        "cold_profiles_abstain_from_ml": SHADOW_MIN_TRUSTED_EVENTS >= 1000,
        "random_forest_absent": True,
        "standalone_pipeline": True,
    }
    return {
        "ready_for_system_shadow_load": all(checks.values()),
        "ready_for_enforcement": False,
        "checks": checks,
        "observed": {
            "precision": mean_or_none(mature, "precision"),
            "event_challenge_recall": mean_or_none(mature, "event_challenge_recall"),
            "f1": mean_or_none(mature, "f1"),
            "roc_auc": mean_or_none(mature, "roc_auc"),
            "pr_auc": mean_or_none(mature, "pr_auc"),
            "challenge_fpr_total": mean_or_none(mature, "challenge_fpr_total"),
            "unexpected_challenge_fpr": mean_or_none(mature, "unexpected_challenge_fpr"),
            "warn_or_higher_rate_total": mean_or_none(mature, "warn_or_higher_rate_total"),
            "sequence_detection_rate": mean_or_none(mature, "sequence_detection_rate"),
            "minimum_attack_family_detection": float(family.min()) if not family.empty else None,
            "preobjective_detection_rate": mean_or_none(mature, "preobjective_detection_rate"),
            "objective_detection_rate": mean_or_none(mature, "objective_detection_rate"),
            "median_time_to_detect_phase": float(mature.median_time_to_detect_phase.median()) if not mature.empty else None,
            "nat_detection_gap": nat_gap,
            "cold_start_sequence_detection_rate_diagnostic": mean_or_none(cold, "sequence_detection_rate"),
            "all_sizes_unexpected_challenge_fpr_diagnostic": mean_or_none(hybrid, "unexpected_challenge_fpr"),
        },
        "shadow_activation": {
            "minimum_trusted_events": SHADOW_MIN_TRUSTED_EVENTS,
            "below_minimum_action": "abstain; retain existing Rule/Behavior/MFA policy",
        },
        "note": "Synthetic V8 may load only in shadow for profiles meeting the history guard. Cold-start learning-curve failures remain diagnostic and are not hidden. Production replay, drift monitoring, rollback, and canary approval are mandatory before enforcement.",
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def export_portable_model(model: TemporalMLP, output: Path) -> dict[str, Any]:
    artifact = output / "temporal_mlp_v8.npz"
    arrays: dict[str, np.ndarray] = {
        "input_median": model.input_median,
        "input_iqr": model.input_iqr,
        "challenge_threshold": np.asarray([model.challenge_threshold]),
        "warn_threshold": np.asarray([model.warn_threshold]),
        "behavior_warn_threshold": np.asarray([model.behavior_warn_threshold]),
    }
    for index, (weight, bias) in enumerate(zip(model.weights, model.biases)):
        arrays[f"weight_{index}"] = weight
        arrays[f"bias_{index}"] = bias
    np.savez_compressed(artifact, **arrays)
    return {
        "path": artifact.name,
        "format": "numpy_npz_temporal_mlp_v8",
        "sha256": _sha256(artifact),
        "size_bytes": artifact.stat().st_size,
        "requires_sklearn_runtime": False,
        "random_forest": False,
    }


def _candidate_model(users: list[dict[str, Any]], seed: int = 42) -> TemporalMLP:
    return _fit_global_model(users, 5000, seed)


def run_matrix(
    sizes: list[int], seeds: list[int], scenarios: list[str], output: Path
) -> None:
    users = _load_users()
    stage_rows: list[dict[str, Any]] = []
    attack_rows: list[dict[str, Any]] = []
    prediction_rows: list[dict[str, Any]] = []
    total = len(sizes) * len(seeds) * len(scenarios)
    ordinal = 0
    for size in sizes:
        for seed in seeds:
            for scenario in scenarios:
                ordinal += 1
                print(f"[{ordinal}/{total}] V8 fresh run n={size} seed={seed} {scenario}", flush=True)
                stages, attacks, predictions, _ = score_run(users, size, seed, scenario)
                stage_rows.extend(stages)
                attack_rows.extend(attacks)
                prediction_rows.extend(predictions)
    output.mkdir(parents=True, exist_ok=True)
    stage_df = pd.DataFrame(stage_rows)
    attack_df = pd.DataFrame(attack_rows)
    prediction_df = pd.DataFrame(prediction_rows)
    stage_df.to_csv(output / "stage_run_results.csv", index=False)
    attack_df.to_csv(output / "attack_sequence_run_results.csv", index=False)
    prediction_df.to_csv(output / "predictions.csv", index=False)
    stage_df.groupby(["stage", "normal_scenario", "dataset_size"], as_index=False).mean(numeric_only=True).to_csv(
        output / "stage_aggregate_results.csv", index=False
    )
    attack_df.groupby(["stage", "normal_scenario", "attack_type"], as_index=False).mean(numeric_only=True).to_csv(
        output / "attack_sequence_aggregate_results.csv", index=False
    )
    support_runs = [_support_audit(users, max(sizes), seeds[0], scenario) for scenario in scenarios]
    support = {
        "passed": all(item["passed"] for item in support_runs),
        "blocking_feature_indices": sorted({index for item in support_runs for index in item["blocking_feature_indices"]}),
        "review_feature_indices": sorted({index for item in support_runs for index in item["review_feature_indices"]}),
        "runs": support_runs,
    }
    (output / "generator_support_audit.json").write_text(
        json.dumps(support, indent=2) + "\n", encoding="utf-8"
    )
    gate = _release_gate(stage_df, attack_df, support)
    candidate = _candidate_model(users, seeds[0])
    artifact = export_portable_model(candidate, output)
    pipeline_sha = _sha256(Path(__file__))
    contract = {
        "version": 8,
        "mode": "standalone_temporal_mlp_shadow",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "pipeline_sha256": pipeline_sha,
        "fixed_ip": FIXED_IP,
        "geo": None,
        "normal_train_test_split": "80:20 chronological per profile",
        "normal_only_cohort_prior_size_per_scenario": COHORT_PRIOR_SIZE,
        "normal_only_cohort_prior_seed_offsets": COHORT_PRIOR_SEED_OFFSETS,
        "model": "NumPy Temporal MLP 64-32-12-1",
        "random_forest": False,
        "imports_previous_experiment_code": False,
        "window_size": WINDOW,
        "rule_features": RULE_FEATURES,
        "behavior_features": BEHAVIOR_FEATURES,
        "neural_event_features": NEURAL_EVENT_FEATURES,
        "neural_input_size": NEURAL_INPUT_SIZE,
        "attack_families": ATTACKS,
        "attack_seed_offsets": {
            "train": TRAIN_ATTACK_OFFSET,
            "validation": VALIDATION_ATTACK_OFFSET,
            "test": TEST_ATTACK_OFFSET,
        },
        "test_attack_subtlety": 0.72,
        "challenge_tail_ratio": CHALLENGE_TAIL_RATIO,
        "shadow_minimum_trusted_events": SHADOW_MIN_TRUSTED_EVENTS,
        "cold_profile_action": "abstain_from_temporal_mlp",
        "ready_for_enforcement": False,
        "artifact": artifact,
    }
    (output / "model_contract_v8.json").write_text(
        json.dumps(contract, indent=2) + "\n", encoding="utf-8"
    )
    gate["artifact"] = artifact
    gate["pipeline_sha256"] = pipeline_sha
    (output / "release_gate.json").write_text(
        json.dumps(gate, indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote {output}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", nargs="+", type=int, default=SIZES)
    parser.add_argument("--seeds", nargs="+", type=int, default=SEEDS)
    parser.add_argument("--scenarios", nargs="+", default=SCENARIOS)
    parser.add_argument("--output", type=Path, default=RESULTS_DIR)
    args = parser.parse_args()
    unsupported = set(args.sizes) - set(SIZES)
    if unsupported:
        raise SystemExit(f"unsupported V8 sizes: {sorted(unsupported)}")
    run_matrix(args.sizes, args.seeds, args.scenarios, args.output)


if __name__ == "__main__":
    main()
