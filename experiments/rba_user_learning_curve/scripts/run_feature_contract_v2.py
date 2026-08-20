#!/usr/bin/env python3
"""Feature Contract V2 experiment.

This experiment keeps the original 12 alias-only profiles, shared private IP,
no-Geo constraint, 80:20 chronological split, five seeds, and frozen attacks.
It compares:

* diverse_v1: a production-shaped baseline on more varied normal data;
* disjoint_v2: mutually exclusive scored feature ownership;
* full_v2: disjoint ownership plus grouped aggregation and policy overrides;
* full_v2 ablations: Rule-only, Behavior-only, ML-only, and the full system.

Only aggregate CSV/JSON artifacts are persisted.  No resolved identity is read
or exported.
"""

from __future__ import annotations

import argparse
import json
import math
import random
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.metrics import average_precision_score, roc_auc_score

ROOT = Path(__file__).resolve().parents[1]
USERS_PATH = ROOT / "config" / "users.json"
RESULTS_DIR = ROOT / "results" / "feature_contract_v2"

SIZES = [10, 50, 100, 500, 1000, 5000]
SEEDS = [42, 43, 44, 45, 46]
NORMAL_SCENARIOS = ["normal_staggered", "normal_nat_burst"]
ATTACKS = [
    "attack_new_device",
    "attack_new_ua_family",
    "attack_new_os",
    "attack_off_hours",
    "attack_failed_spike",
    "attack_login_velocity",
    "attack_concurrent_sessions",
    "attack_subsystem_lateral",
    "attack_new_passkey",
    "attack_permission_change",
    "attack_combined_ato",
]
WARN, CHALLENGE, BLOCK = 0.50, 0.70, 0.85

# Expected minimum action for severity-aware evaluation.  Off-hours and OS
# changes are contextual anomalies, so warn is a valid outcome.  Combined ATO
# must block; other attack simulations must challenge or block.
EXPECTED_ACTION = {
    "attack_new_os": "warn",
    "attack_off_hours": "warn",
    "attack_combined_ato": "block",
    **{
        name: "challenge"
        for name in ATTACKS
        if name not in {"attack_new_os", "attack_off_hours", "attack_combined_ato"}
    },
}
ACTION_LEVEL = {"allow": 0, "warn": 1, "challenge": 2, "block": 3}

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
)
BEHAVIOR_FEATURES = (
    "hour_rarity",
    "weekday_rarity",
    "subsystem_rarity",
    "transition_surprise",
    "device_signature_rarity",
    "cadence_tail_probability",
)
ML_FEATURES = (
    "hour_sin_residual",
    "hour_cos_residual",
    "log_minutes_since_last",
    "login_count_7d",
    "session_duration_minutes",
    "device_switch_rate_7d",
    "subsystem_entropy_30",
    "scope_sensitivity",
    "passkey_usage_gap_days",
)


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


@dataclass
class ProfileHistory:
    events: list[Event] = field(default_factory=list)
    device_counts: Counter[str] = field(default_factory=Counter)
    browser_counts: Counter[str] = field(default_factory=Counter)
    signature_counts: Counter[str] = field(default_factory=Counter)
    subsystem_counts: Counter[str] = field(default_factory=Counter)
    transition_counts: Counter[tuple[str | None, str | None]] = field(default_factory=Counter)

    def add(self, event: Event) -> None:
        if self.events:
            self.transition_counts[(self.events[-1].subsystem, event.subsystem)] += 1
        self.events.append(event)
        self.device_counts[event.device_id] += 1
        self.browser_counts[event.browser_family] += 1
        self.signature_counts[f"{event.os_name}/{event.browser_family}"] += 1
        if event.subsystem:
            self.subsystem_counts[event.subsystem] += 1


def _load_users() -> list[dict[str, Any]]:
    value = json.loads(USERS_PATH.read_text(encoding="utf-8"))
    users = value["users"]
    assert len(users) == 12
    return users


def _weighted(items: list[dict[str, Any]], rng: random.Random) -> str:
    draw = rng.random()
    total = 0.0
    for item in items:
        total += float(item["weight"])
        if draw <= total:
            return str(item["key"])
    return str(items[-1]["key"])


def _device_properties(device_key: str, version: int) -> tuple[str, str, str]:
    mapping = {
        "windows_chrome": ("dev-win", "Chrome", "Windows"),
        "android_chrome": ("dev-android", "Chrome", "Android"),
        "ios_mobile": ("dev-iphone", "Safari", "iOS"),
        "ios_tablet": ("dev-ipad", "Safari", "iPadOS"),
    }
    device_id, browser, os_name = mapping[device_key]
    return device_id, browser, os_name


def _normal_subsystem(user: dict[str, Any], rng: random.Random) -> str | None:
    allowed = list(user["allowed_subsystems"])
    if not allowed:
        return None
    if len(allowed) == 1:
        return allowed[0]
    preferred = user["owned_subsystems"][0] if user["owned_subsystems"] else allowed[0]
    return preferred if rng.random() < 0.72 else next(x for x in allowed if x != preferred)


def _normal_timestamp(
    user: dict[str, Any], index: int, user_index: int, scenario: str, rng: random.Random
) -> datetime:
    """Create varied, policy-valid timing without hiding NAT overlap."""
    base = datetime(2024, 1, 8)
    day_index = index // 2
    day = base + timedelta(days=day_index)
    # Staff/teachers remain weekday-oriented but occasional weekend use (4%) is
    # included as benign variability rather than impossible normal behavior.
    if day.weekday() not in user["normal_days"] and rng.random() >= 0.04:
        while day.weekday() not in user["normal_days"]:
            day += timedelta(days=1)
    interval = rng.choice(user["normal_hours"])
    start, end = int(interval[0]), int(interval[1])
    if scenario == "normal_nat_burst":
        # Everyone shares a true one-hour burst, but minute/second are not fixed.
        burst_hour = 9 if index % 2 == 0 else 14
        hour = min(max(burst_hour, start), end)
        minute = (user_index * 3 + rng.randint(0, 14)) % 55
    else:
        # Stagger by cohort and sample naturally inside the user's valid windows.
        cohort_offset = (user_index % 4) * 3
        hour = rng.randint(start, end)
        minute = (rng.randint(0, 49) + cohort_offset) % 60
    second = rng.randint(0, 59)
    return day.replace(hour=hour, minute=minute, second=second)


def generate_normal(users: list[dict[str, Any]], size: int, seed: int, scenario: str) -> list[Event]:
    rng = random.Random(seed * 101 + size)
    train_count = int(size * 0.8)
    rows: list[Event] = []
    for user_index, user in enumerate(users):
        previous_device = None
        for index in range(size):
            timestamp = _normal_timestamp(user, index, user_index, scenario, rng)
            device_key = _weighted(user["devices"], rng)
            device_id, browser, os_name = _device_properties(device_key, 150)
            # Browser-version drift is normal.  It changes a continuous residual
            # but not the stable device/browser-family identity.
            version = 149 + min(4, index // max(12, size // 4 + 1))
            subsystem = _normal_subsystem(user, rng)
            # Realistic benign diversity: duration, occasional retry, and a rare
            # overlapping session.  Values remain below security rule cutoffs.
            duration = max(3.0, rng.lognormvariate(math.log(18), 0.42))
            failed = 1 if rng.random() < 0.035 else 0
            concurrent = 1 if rng.random() < 0.025 else 0
            active_subsystems = 1 if subsystem else 0
            if concurrent and len(user["allowed_subsystems"]) > 1 and rng.random() < 0.2:
                active_subsystems = 2
            scope = 0.8 if subsystem == "dorm" else (0.6 if subsystem == "library" else 0.1)
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
                    failed_1h=failed,
                    concurrent_sessions=concurrent,
                    active_subsystems=active_subsystems,
                )
            )
            previous_device = device_id
    return sorted(rows, key=lambda x: (x.timestamp, x.profile_id))


def generate_attacks(
    users: list[dict[str, Any]], normal: list[Event], size: int, seed: int, scenario: str
) -> list[Event]:
    rng = random.Random(seed + 10_000)
    by_user: dict[str, list[Event]] = defaultdict(list)
    for row in normal:
        by_user[row.profile_id].append(row)
    last_day = max(row.timestamp for row in normal) + timedelta(days=7)
    output: list[Event] = []
    for user in users:
        base_event = by_user[user["profile_id"]][-1]
        for index in range(20):
            attack = ATTACKS[index % len(ATTACKS)]
            row = replace(base_event)
            row.split = "attack_test"
            row.attack_type = attack
            row.timestamp = last_day + timedelta(days=index, minutes=rng.randint(0, 45))
            row.failed_1h = row.success_10m = row.concurrent_sessions = 0
            row.active_subsystems = 1 if row.subsystem else 0
            row.new_passkey = row.confirmed_incident = 0
            row.permission_age_hours = 9999.0
            row.session_duration = max(3.0, rng.lognormvariate(math.log(18), 0.42))
            if attack == "attack_new_device":
                row.device_id, row.browser_family, row.os_name = "dev-linux-new", "Firefox", "Linux"
            elif attack == "attack_new_ua_family":
                row.browser_family = "Firefox"
            elif attack == "attack_new_os":
                row.os_name = "Linux"
            elif attack == "attack_off_hours":
                row.timestamp = row.timestamp.replace(hour=2, minute=15)
            elif attack == "attack_failed_spike":
                row.failed_1h = 5
            elif attack == "attack_login_velocity":
                row.success_10m = 5
            elif attack == "attack_concurrent_sessions":
                row.concurrent_sessions = 4
            elif attack == "attack_subsystem_lateral":
                row.active_subsystems = 2
                allowed = set(user["allowed_subsystems"])
                row.subsystem = "library" if "library" not in allowed else "dorm"
            elif attack == "attack_new_passkey":
                row.new_passkey = 1
            elif attack == "attack_permission_change":
                row.permission_age_hours = 2.0
            elif attack == "attack_combined_ato":
                row.timestamp = row.timestamp.replace(hour=2, minute=15)
                row.device_id, row.browser_family, row.os_name = "dev-linux-new", "Firefox", "Linux"
                row.failed_1h = 6
                row.success_10m = 5
                row.concurrent_sessions = 4
                row.active_subsystems = 2
                row.new_passkey = 1
                row.permission_age_hours = 2.0
                row.confirmed_incident = 1
                row.session_duration = 2.0
            output.append(row)
    return output


def _rate(count: int, total: int, smoothing: float = 1.0, categories: int = 2) -> float:
    return (count + smoothing) / (total + smoothing * categories) if total else 0.5


def _entropy(counts: Counter[str]) -> float:
    total = sum(counts.values())
    if total <= 1:
        return 0.0
    return -sum((n / total) * math.log(n / total + 1e-12) for n in counts.values())


def extract_owned_features(event: Event, history: ProfileHistory) -> dict[str, float]:
    past = history.events
    total = len(past)
    last = past[-1] if past else None
    signature = f"{event.os_name}/{event.browser_family}"
    hour_bucket = event.timestamp.hour
    hour_count = sum(item.timestamp.hour == hour_bucket for item in past[-200:])
    weekday_count = sum(item.timestamp.weekday() == event.timestamp.weekday() for item in past[-200:])
    subsystem_count = history.subsystem_counts[event.subsystem] if event.subsystem else total
    transition = (last.subsystem if last else None, event.subsystem)
    transition_count = history.transition_counts[transition]
    minutes_since_last = (
        max(0.5, (event.timestamp - last.timestamp).total_seconds() / 60.0)
        if last
        else 24.0 * 60.0
    )
    cadence = [
        max(0.5, (b.timestamp - a.timestamp).total_seconds() / 60.0)
        for a, b in zip(past[-101:-1], past[-100:])
        if b.timestamp > a.timestamp
    ]
    if len(cadence) >= 5:
        tail = sum(value <= minutes_since_last for value in cadence) / len(cadence)
        cadence_tail = min(tail, 1.0 - tail) * 2.0
        cadence_tail_probability = 1.0 - cadence_tail
    else:
        cadence_tail_probability = 0.0

    # The generator produces at most about two normal events/day/profile, so a
    # bounded 40-event tail safely covers seven days while keeping the 5,000-row
    # learning-curve cells linear rather than quadratic.
    recent_7d = [
        item for item in past[-40:]
        if item.timestamp >= event.timestamp - timedelta(days=7)
    ]
    device_switches = sum(
        a.device_id != b.device_id for a, b in zip(recent_7d, recent_7d[1:])
    )
    subsystem_counts_30 = Counter(item.subsystem for item in past[-30:] if item.subsystem)

    return {
        # Rule-owned features
        "new_device": float(bool(total) and event.device_id not in history.device_counts),
        "new_ua_family": float(bool(total) and event.browser_family not in history.browser_counts),
        "failed_1h": float(event.failed_1h),
        "success_10m": float(event.success_10m),
        "concurrent_sessions": float(event.concurrent_sessions),
        "active_subsystems": float(event.active_subsystems),
        "new_passkey": float(event.new_passkey),
        "permission_age_hours": float(event.permission_age_hours),
        "confirmed_incident": float(event.confirmed_incident),
        # Behavior-owned, user-relative features
        "hour_rarity": 1.0 - _rate(hour_count, min(total, 200), categories=24),
        "weekday_rarity": 1.0 - _rate(weekday_count, min(total, 200), categories=7),
        "subsystem_rarity": 1.0 - _rate(subsystem_count, total, categories=2),
        "transition_surprise": 1.0 - _rate(transition_count, max(0, total - 1), categories=4),
        "device_signature_rarity": 1.0 - _rate(history.signature_counts[signature], total, categories=6),
        "cadence_tail_probability": cadence_tail_probability,
        # ML-owned continuous/residual features
        "hour_sin_residual": math.sin(2.0 * math.pi * event.timestamp.hour / 24.0),
        "hour_cos_residual": math.cos(2.0 * math.pi * event.timestamp.hour / 24.0),
        "log_minutes_since_last": math.log1p(minutes_since_last),
        "login_count_7d": float(len(recent_7d)),
        "session_duration_minutes": float(event.session_duration),
        "device_switch_rate_7d": device_switches / max(1, len(recent_7d) - 1),
        "subsystem_entropy_30": _entropy(subsystem_counts_30),
        "scope_sensitivity": float(event.scope_sensitivity),
        "passkey_usage_gap_days": 1.0 if event.user_type == "admin" else 30.0,
    }


def build_features(normal: list[Event], attacks: list[Event]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    histories: dict[str, ProfileHistory] = defaultdict(ProfileHistory)
    normal_rows: list[dict[str, Any]] = []
    for event in normal:
        row = {"event": event, **extract_owned_features(event, histories[event.profile_id])}
        normal_rows.append(row)
        histories[event.profile_id].add(event)
    # Frozen snapshot: every attack for a user sees only normal history.
    attack_rows = [
        {"event": event, **extract_owned_features(event, histories[event.profile_id])}
        for event in attacks
    ]
    return normal_rows, attack_rows


def _fit_iforest(train: list[dict[str, Any]], seed: int, features: Iterable[str]) -> tuple[IsolationForest, np.ndarray, np.ndarray]:
    names = list(features)
    matrix = np.asarray([[row[name] for name in names] for row in train], dtype=float)
    median = np.median(matrix, axis=0)
    iqr = np.quantile(matrix, 0.75, axis=0) - np.quantile(matrix, 0.25, axis=0)
    iqr[iqr < 1e-6] = 1.0
    scaled = (matrix - median) / iqr
    model = IsolationForest(
        n_estimators=120,
        contamination=0.02,
        max_samples=min(256, len(train)),
        random_state=seed,
        n_jobs=-1,
    ).fit(scaled)
    return model, median, iqr


def _raw_ml(model: IsolationForest, median: np.ndarray, iqr: np.ndarray, rows: list[dict[str, Any]], names: Iterable[str]) -> np.ndarray:
    feature_names = list(names)
    matrix = np.asarray([[row[name] for name in feature_names] for row in rows], dtype=float)
    decisions = model.decision_function((matrix - median) / iqr)
    return 1.0 / (1.0 + np.exp(decisions * 5.0))


def _v1_rule(row: dict[str, Any], distinct_profiles: int) -> tuple[float, bool]:
    if row["failed_1h"] >= 10 or row["success_10m"] >= 50:
        return 1.0, True
    score = 0.30 * row["new_device"] + 0.20 * row["new_ua_family"]
    if row["failed_1h"] >= 3:
        score += 0.20
    if distinct_profiles > 5:
        score += 0.25
    return min(1.0, score), False


def _v1_behavior(row: dict[str, Any], history_count: int) -> float:
    if history_count < 5:
        return 0.20
    # Convert rarity to the old median-hour behavior approximately.
    score = 0.0
    if row["hour_rarity"] >= 0.97:
        score += 0.40
    elif row["hour_rarity"] >= 0.90:
        score += 0.20
    if row["weekday_rarity"] >= 0.86:
        score += 0.10
    return min(1.0, score)


def _rule_v2(row: dict[str, Any]) -> tuple[float, bool, list[str], set[str]]:
    reasons: list[str] = []
    groups: set[str] = set()
    score = 0.0
    hard = False
    if row["confirmed_incident"] >= 1:
        score, hard = 1.0, True
        reasons.append("confirmed_incident_block")
        groups.add("incident")
    if row["new_device"]:
        score += 0.30; reasons.append("new_device"); groups.add("novelty")
    if row["new_ua_family"]:
        score += 0.20; reasons.append("new_ua_family"); groups.add("novelty")
    if row["failed_1h"] >= 10:
        return 1.0, True, reasons + ["failed_10_block"], groups | {"velocity"}
    if row["failed_1h"] >= 3:
        score += 0.30; reasons.append("failed_spike"); groups.add("velocity")
    if row["success_10m"] >= 5:
        score += 0.30; reasons.append("login_velocity"); groups.add("velocity")
    if row["concurrent_sessions"] >= 4:
        score += 0.25; reasons.append("concurrent_sessions"); groups.add("session")
    if row["active_subsystems"] >= 2:
        score += 0.25; reasons.append("multi_subsystem_session"); groups.add("session")
    if row["new_passkey"]:
        score += 0.35; reasons.append("new_passkey"); groups.add("credential")
    if row["permission_age_hours"] <= 24:
        score += 0.35; reasons.append("recent_permission_change"); groups.add("privilege")
    return min(1.0, score), hard, reasons, groups


def _behavior_v2(row: dict[str, Any], history_count: int) -> tuple[float, list[str], set[str]]:
    if history_count < 5:
        return 0.0, ["behavior_low_confidence"], set()
    score = 0.0
    reasons: list[str] = []
    groups: set[str] = set()
    checks = (
        ("hour_rarity", 0.94, 0.18, "rare_hour", "time"),
        ("weekday_rarity", 0.86, 0.08, "rare_weekday", "time"),
        ("subsystem_rarity", 0.70, 0.12, "rare_subsystem", "resource"),
        ("transition_surprise", 0.78, 0.12, "rare_transition", "resource"),
        ("device_signature_rarity", 0.82, 0.22, "rare_device_signature", "platform"),
        ("cadence_tail_probability", 0.94, 0.10, "rare_cadence", "cadence"),
    )
    for name, threshold, weight, reason, group in checks:
        if row[name] >= threshold:
            score += weight; reasons.append(reason); groups.add(group)
    return min(0.40, score), reasons, groups


def _ml_contribution(raw: float) -> float:
    if raw >= 0.72:
        return 0.25
    if raw >= 0.58:
        return 0.15
    if raw >= 0.48:
        return 0.07
    return 0.0


def _decision(score: float, hard: bool, override: str | None = None) -> str:
    level = 3 if hard or score >= BLOCK else 2 if score >= CHALLENGE else 1 if score >= WARN else 0
    if override:
        level = max(level, ACTION_LEVEL[override])
    return ("allow", "warn", "challenge", "block")[level]


def _metrics(records: list[dict[str, Any]]) -> dict[str, float]:
    labels = np.asarray([r["label"] for r in records], dtype=int)
    scores = np.asarray([r["score"] for r in records], dtype=float)
    detected = np.asarray([ACTION_LEVEL[r["decision"]] >= 2 for r in records])
    attack = labels == 1
    normal = labels == 0
    tp, fp = int(np.sum(detected & attack)), int(np.sum(detected & normal))
    fn, tn = int(np.sum(~detected & attack)), int(np.sum(~detected & normal))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    policy_hits = [
        ACTION_LEVEL[r["decision"]] >= ACTION_LEVEL[EXPECTED_ACTION[r["attack_type"]]]
        for r in records if r["label"] == 1
    ]
    warn_fp = sum(r["label"] == 0 and ACTION_LEVEL[r["decision"]] >= 1 for r in records)
    block_fp = sum(r["label"] == 0 and ACTION_LEVEL[r["decision"]] >= 3 for r in records)
    return {
        "precision": precision,
        "challenge_recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        "challenge_fpr": fp / max(1, int(np.sum(normal))),
        "warn_fpr": warn_fp / max(1, int(np.sum(normal))),
        "block_fpr": block_fp / max(1, int(np.sum(normal))),
        "policy_success": float(np.mean(policy_hits)),
        "roc_auc": float(roc_auc_score(labels, scores)),
        "pr_auc": float(average_precision_score(labels, scores)),
        "normal_count": int(np.sum(normal)),
        "attack_count": int(np.sum(attack)),
    }


def score_run(users: list[dict[str, Any]], size: int, seed: int, scenario: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    normal = generate_normal(users, size, seed, scenario)
    attacks = generate_attacks(users, normal, size, seed, scenario)
    normal_rows, attack_rows = build_features(normal, attacks)
    train = [r for r in normal_rows if r["event"].split == "train"]
    evaluation = [r for r in normal_rows if r["event"].split == "normal_test"] + attack_rows
    assert train and evaluation and all(r["event"].attack_type is None for r in train)

    # Diverse-V1 deliberately exposes all owned features to IF, matching the
    # old overlap pattern.  V2 IF sees only ML_FEATURES.
    v1_all = list(RULE_FEATURES + BEHAVIOR_FEATURES + ML_FEATURES)
    v1_model, v1_med, v1_iqr = _fit_iforest(train, seed, v1_all)
    v2_model, v2_med, v2_iqr = _fit_iforest(train, seed, ML_FEATURES)
    v1_raw = _raw_ml(v1_model, v1_med, v1_iqr, evaluation, v1_all)
    v2_raw = _raw_ml(v2_model, v2_med, v2_iqr, evaluation, ML_FEATURES)

    train_counts = Counter(r["event"].profile_id for r in train)
    # NAT rule is evaluated point-in-time for normal tests.  Frozen attacks do
    # not inject artificial cross-user history.
    ip_window: deque[tuple[datetime, str]] = deque()
    ip_counts: Counter[str] = Counter()
    ordered_normal_test = sorted(
        [r for r in evaluation if r["event"].split == "normal_test"],
        key=lambda r: (r["event"].timestamp, r["event"].profile_id),
    )
    nat_distinct: dict[int, int] = {}
    for row in ordered_normal_test:
        now = row["event"].timestamp
        while ip_window and ip_window[0][0] < now - timedelta(hours=1):
            _, pid = ip_window.popleft(); ip_counts[pid] -= 1
            if not ip_counts[pid]: del ip_counts[pid]
        nat_distinct[id(row)] = len(ip_counts)
        ip_window.append((now, row["event"].profile_id)); ip_counts[row["event"].profile_id] += 1

    predictions: list[dict[str, Any]] = []
    for index, row in enumerate(evaluation):
        event = row["event"]
        label = 1 if event.attack_type else 0
        distinct = nat_distinct.get(id(row), 0)
        v1_rule, v1_hard = _v1_rule(row, distinct)
        v1_behavior = _v1_behavior(row, train_counts[event.profile_id])
        v1_ml = 0.4 if v1_raw[index] >= 0.7 else 0.2 if v1_raw[index] >= 0.5 else 0.1 if v1_raw[index] >= 0.3 else 0.0
        v1_score = min(1.0, v1_rule + v1_behavior + v1_ml)
        predictions.append({
            "stage": "diverse_v1", "profile_id": event.profile_id, "normal_scenario": scenario,
            "attack_type": event.attack_type, "label": label, "score": v1_score,
            "decision": _decision(v1_score, v1_hard), "rule": v1_rule,
            "behavior": v1_behavior, "ml": v1_ml,
        })

        rule, hard, _, rule_groups = _rule_v2(row)
        behavior, _, behavior_groups = _behavior_v2(row, train_counts[event.profile_id])
        ml = _ml_contribution(float(v2_raw[index]))
        disjoint_score = min(1.0, rule + behavior + ml)
        predictions.append({
            "stage": "disjoint_v2", "profile_id": event.profile_id, "normal_scenario": scenario,
            "attack_type": event.attack_type, "label": label, "score": disjoint_score,
            "decision": _decision(disjoint_score, hard), "rule": rule,
            "behavior": behavior, "ml": ml,
        })

        # Grouped full V2 prevents several variants of one cause from stacking
        # without bound.  An independent second signal group enables a 0.62
        # conditional challenge.  Security actions have explicit step-up floors.
        group_count = len(rule_groups | behavior_groups | ({"ml_residual"} if ml >= 0.15 else set()))
        novelty_cap = min(rule, 0.55) if "novelty" in rule_groups else rule
        full_score = min(1.0, novelty_cap + behavior + ml)
        override = None
        if row["new_passkey"] or row["permission_age_hours"] <= 24:
            override = "challenge"
        if row["confirmed_incident"]:
            override = "block"
        # Directly actionable security counters are deterministic controls, not
        # ML guesses.  They receive an action floor while their numeric weight
        # still participates in the auditable score.
        if (
            row["failed_1h"] >= 3
            or row["success_10m"] >= 5
            or row["concurrent_sessions"] >= 4
        ):
            override = "challenge"
        # Lateral movement needs two independent facts: simultaneous access to
        # multiple systems (Rule) and an unusual transition for this user
        # (Behavior).  This avoids treating every benign NAT overlap as attack.
        if row["active_subsystems"] >= 2 and row["transition_surprise"] >= 0.72:
            override = "challenge"
        # A rare hour or platform is contextual rather than conclusive: warn is
        # the minimum, and the aggregator may escalate when another group agrees.
        if override is None and (
            row["hour_rarity"] >= 0.985 or row["device_signature_rarity"] >= 0.97
        ):
            override = "warn"
        if group_count >= 2 and full_score >= 0.58 and full_score < CHALLENGE:
            override = "challenge"
        full_decision = _decision(full_score, hard, override)
        predictions.append({
            "stage": "full_v2", "profile_id": event.profile_id, "normal_scenario": scenario,
            "attack_type": event.attack_type, "label": label, "score": full_score,
            "decision": full_decision, "rule": rule, "behavior": behavior, "ml": ml,
        })

        for ablation, parts in {
            "rule_only": (rule, 0.0, 0.0),
            "behavior_only": (0.0, behavior, 0.0),
            # Use the raw anomaly score for a standalone ML ablation.  The
            # capped contribution is an aggregator input and cannot reach a
            # final decision threshold by itself.
            "ml_only": (0.0, 0.0, float(v2_raw[index])),
        }.items():
            a_rule, a_behavior, a_ml = parts
            a_score = min(1.0, a_rule + a_behavior + a_ml)
            if ablation == "rule_only":
                a_override = (
                    "challenge"
                    if (
                        row["failed_1h"] >= 3
                        or row["success_10m"] >= 5
                        or row["concurrent_sessions"] >= 4
                        or row["new_passkey"]
                        or row["permission_age_hours"] <= 24
                    )
                    else ("block" if row["confirmed_incident"] else None)
                )
                a_decision = _decision(a_score, hard, a_override)
            elif ablation == "behavior_only":
                # Component-specific operating point: Behavior can warn on
                # contextual deviation but cannot block by itself.
                a_decision = "warn" if behavior >= 0.18 else "allow"
            else:
                # IsolationForest's decision boundary maps to raw risk 0.50.
                # Use that native boundary for the standalone ablation; Full V2
                # remains more conservative because ML is only one contributor.
                a_decision = "challenge" if a_ml >= 0.50 else "warn" if a_ml >= 0.48 else "allow"
            predictions.append({
                "stage": ablation, "profile_id": event.profile_id, "normal_scenario": scenario,
                "attack_type": event.attack_type, "label": label, "score": a_score,
                "decision": a_decision,
                "rule": a_rule, "behavior": a_behavior, "ml": a_ml,
            })

    stage_rows: list[dict[str, Any]] = []
    attack_detail: list[dict[str, Any]] = []
    for stage in ("diverse_v1", "disjoint_v2", "full_v2", "rule_only", "behavior_only", "ml_only"):
        records = [r for r in predictions if r["stage"] == stage]
        stage_rows.append({"stage": stage, "dataset_size": size, "seed": seed, "normal_scenario": scenario, **_metrics(records)})
        for attack in ATTACKS:
            subset = [r for r in records if r["attack_type"] == attack]
            if not subset:
                continue
            challenge = np.mean([ACTION_LEVEL[r["decision"]] >= 2 for r in subset])
            success = np.mean([ACTION_LEVEL[r["decision"]] >= ACTION_LEVEL[EXPECTED_ACTION[attack]] for r in subset])
            attack_detail.append({
                "stage": stage, "dataset_size": size, "seed": seed, "normal_scenario": scenario,
                "attack_type": attack, "expected_action": EXPECTED_ACTION[attack],
                "challenge_recall": challenge, "policy_success": success,
                "mean_score": float(np.mean([r["score"] for r in subset])),
            })
    return stage_rows, attack_detail


def run_matrix(sizes: list[int], seeds: list[int], scenarios: list[str], output: Path) -> None:
    users = _load_users()
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
                stages.extend(stage_rows); attacks.extend(attack_rows)
    output.mkdir(parents=True, exist_ok=True)
    stages_df = pd.DataFrame(stages)
    attacks_df = pd.DataFrame(attacks)
    stages_df.to_csv(output / "stage_run_results.csv", index=False)
    attacks_df.to_csv(output / "attack_run_results.csv", index=False)
    aggregate = (
        stages_df.groupby(["stage", "normal_scenario", "dataset_size"], as_index=False)
        .agg(
            precision=("precision", "mean"), challenge_recall=("challenge_recall", "mean"),
            f1=("f1", "mean"), f1_sd=("f1", "std"), challenge_fpr=("challenge_fpr", "mean"),
            warn_fpr=("warn_fpr", "mean"), block_fpr=("block_fpr", "mean"),
            policy_success=("policy_success", "mean"), roc_auc=("roc_auc", "mean"),
            pr_auc=("pr_auc", "mean"), runs=("seed", "count"),
        )
    )
    aggregate.to_csv(output / "stage_aggregate_results.csv", index=False)
    attack_aggregate = (
        attacks_df.groupby(["stage", "normal_scenario", "attack_type", "expected_action"], as_index=False)
        .agg(challenge_recall=("challenge_recall", "mean"), policy_success=("policy_success", "mean"), mean_score=("mean_score", "mean"), observations=("challenge_recall", "count"))
    )
    attack_aggregate.to_csv(output / "attack_aggregate_results.csv", index=False)
    contract = {
        "version": 2,
        "fixed_ip": "192.168.10.1",
        "geo": None,
        "train_fraction": 0.8,
        "train_labels": [0],
        "profiles": len(users),
        "dataset_sizes_per_user": sizes,
        "seeds": seeds,
        "normal_scenarios": scenarios,
        "rule_features": RULE_FEATURES,
        "behavior_features": BEHAVIOR_FEATURES,
        "ml_features": ML_FEATURES,
        "overlap": sorted((set(RULE_FEATURES) & set(BEHAVIOR_FEATURES)) | (set(RULE_FEATURES) & set(ML_FEATURES)) | (set(BEHAVIOR_FEATURES) & set(ML_FEATURES))),
        "expected_action": EXPECTED_ACTION,
    }
    (output / "feature_contract_v2.json").write_text(json.dumps(contract, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {output}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", nargs="+", type=int, default=SIZES)
    parser.add_argument("--seeds", nargs="+", type=int, default=SEEDS)
    parser.add_argument("--scenarios", nargs="+", default=NORMAL_SCENARIOS)
    parser.add_argument("--output", type=Path, default=RESULTS_DIR)
    args = parser.parse_args()
    unknown_sizes = set(args.sizes) - set(SIZES)
    if unknown_sizes:
        raise SystemExit(f"unsupported sizes: {sorted(unknown_sizes)}")
    run_matrix(args.sizes, args.seeds, args.scenarios, args.output)


if __name__ == "__main__":
    main()
