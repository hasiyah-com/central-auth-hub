"""Alias-only isolated SQLite loader and point-in-time feature builder."""

from __future__ import annotations

import json
import math
import sqlite3
import statistics
from bisect import bisect_left
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .contracts import FEATURE_NAMES, load_config

MIN_HISTORY_FOR_PERSONALIZATION = 5
SESSION_DURATION_MINUTES = 15
SCOPE_WEIGHTS = {
    "email": 0.1,
    "name": 0.1,
    "faculty": 0.3,
    "major": 0.3,
    "student_id": 0.6,
    "employee_id": 0.6,
}
FORBIDDEN_EXPORT_KEYS = {
    "email",
    "full_name",
    "identifier",
    "subsystem_id",
    "user_id",
}


@dataclass
class SessionRecord:
    created_at: datetime
    logout_at: datetime
    user_agent: str
    browser: str
    subsystem_key: str | None
    login_method: str


@dataclass
class PasskeyRecord:
    created_at: datetime
    last_used_at: datetime | None


@dataclass
class ProfileState:
    sessions: list[SessionRecord] = field(default_factory=list)
    session_times: list[datetime] = field(default_factory=list)
    seen_user_agents: set[str] = field(default_factory=set)
    seen_families: set[str] = field(default_factory=set)
    passkeys: list[PasskeyRecord] = field(default_factory=list)


def parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _assert_alias_only(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        forbidden = FORBIDDEN_EXPORT_KEYS & set(value)
        if forbidden:
            raise ValueError(f"{path} contains resolved identity keys: {sorted(forbidden)}")
        for key, child in value.items():
            _assert_alias_only(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_alias_only(child, f"{path}[{index}]")


def _initial_states(
    users: list[dict[str, Any]], first_event_at: datetime
) -> dict[str, ProfileState]:
    states: dict[str, ProfileState] = {}
    for user in users:
        state = ProfileState()
        if user["is_hub_admin"]:
            state.passkeys.append(
                PasskeyRecord(
                    created_at=first_event_at - timedelta(days=90),
                    last_used_at=None,
                )
            )
        states[user["profile_id"]] = state
    return states


def _setup_counts(
    event: dict[str, Any], now: datetime
) -> tuple[list[datetime], int, list[tuple[str | None, int]]]:
    virtual_logins: list[datetime] = []
    failed_count = 0
    active_sessions: list[tuple[str | None, int]] = []
    for action in event["setup_actions"]:
        action_name = action["action"]
        count = int(action["count"])
        action_time = now - timedelta(minutes=int(action["offset_minutes"]))
        if action_name in {"failed_login", "successful_login", "open_session"}:
            virtual_logins.extend(
                action_time + timedelta(seconds=index) for index in range(count)
            )
        if action_name == "failed_login":
            failed_count += count
        if action_name == "open_session":
            active_sessions.append((action.get("subsystem_key"), count))
    return virtual_logins, failed_count, active_sessions


def _passkey_features(
    state: ProfileState,
    event: dict[str, Any],
    now: datetime,
) -> tuple[float, float, float, float]:
    passkeys = [
        PasskeyRecord(created_at=item.created_at, last_used_at=item.last_used_at)
        for item in state.passkeys
        if item.created_at < now
    ]
    for action in event["setup_actions"]:
        if action["action"] == "add_passkey":
            created_at = now - timedelta(minutes=int(action["offset_minutes"]))
            for _ in range(int(action["count"])):
                passkeys.append(PasskeyRecord(created_at=created_at, last_used_at=None))

    if not passkeys:
        return 0.0, 0.0, 0.0, 0.0

    oldest = min(item.created_at for item in passkeys)
    newest = max(item.created_at for item in passkeys)
    age_days = max(0.0, (now - oldest).total_seconds() / 86400.0)
    recently_added = 1.0 if (now - newest).total_seconds() < 3600 else 0.0
    used = [
        item.last_used_at
        for item in passkeys
        if item.last_used_at is not None and item.last_used_at < now
    ]
    if used:
        last_used_days = max(0.0, (now - max(used)).total_seconds() / 86400.0)
    else:
        last_used_days = age_days
    return float(len(passkeys)), age_days, recently_added, last_used_days


def extract_features(
    event: dict[str, Any],
    state: ProfileState,
    subsystem_config: dict[str, Any],
) -> list[float]:
    """Mirror the production 23-feature contract at the event timestamp."""
    now = parse_timestamp(event["created_at"])
    past = state.sessions
    last_50 = past[-50:]

    hour = float(now.hour)
    day = float(now.weekday())
    if len(last_50) >= MIN_HISTORY_FOR_PERSONALIZATION:
        typical = statistics.median(item.created_at.hour for item in last_50)
        raw_diff = abs(hour - typical)
        hours_from_typical = float(min(raw_diff, 24 - raw_diff))
        same_weekday = sum(
            item.created_at.weekday() == now.weekday() for item in last_50
        )
        weekday_usage = 1.0 - (same_weekday / len(last_50))
    else:
        hours_from_typical = 0.0
        weekday_usage = 0.0

    current_ua = event["user_agent"]
    current_family = event["browser"]
    is_new_device = (
        1.0
        if state.seen_user_agents and current_ua not in state.seen_user_agents
        else 0.0
    )
    is_new_family = (
        1.0
        if state.seen_families and current_family not in state.seen_families
        else 0.0
    )

    virtual_logins, failed_count, setup_active = _setup_counts(event, now)
    recent_start = bisect_left(state.session_times, now - timedelta(hours=24))
    recent_session_times = state.session_times[recent_start:]
    all_recent_times = recent_session_times + virtual_logins
    if all_recent_times:
        delta_minutes = (now - max(all_recent_times)).total_seconds() / 60.0
        log_minutes_since_last = math.log(max(delta_minutes, 0.5))
    else:
        log_minutes_since_last = 6.0
    login_count_24h = float(len(all_recent_times))

    passkey_count, passkey_age, new_passkey, passkey_last_used = _passkey_features(
        state,
        event,
        now,
    )

    concurrent_cutoff = now - timedelta(minutes=60)
    active_normal: list[SessionRecord] = []
    for item in reversed(past):
        if item.created_at < concurrent_cutoff:
            break
        if item.logout_at > now:
            active_normal.append(item)
    concurrent_count = float(
        min(50, len(active_normal) + sum(count for _, count in setup_active))
    )
    active_subsystems = {
        item.subsystem_key for item in active_normal if item.subsystem_key is not None
    }
    for subsystem_key, count in setup_active:
        if count and subsystem_key is not None:
            active_subsystems.add(subsystem_key)

    subsystem_key = event["subsystem_key"]
    scope_sensitivity = 0.0
    if subsystem_key is not None:
        scope = subsystem_config["subsystems"][subsystem_key].get("scope", [])
        scope_sensitivity = min(
            1.0,
            sum(SCOPE_WEIGHTS.get(item, 0.1) for item in scope),
        )

    permission_offsets = [
        int(action["offset_minutes"])
        for action in event["setup_actions"]
        if action["action"] == "change_permission"
    ]
    if permission_offsets:
        ever_changed_permission = 1.0
        permission_change_age = min(permission_offsets) / 1440.0
    else:
        ever_changed_permission = 0.0
        permission_change_age = 365.0

    confirmed_incidents = float(
        sum(
            int(action["count"])
            for action in event["setup_actions"]
            if action["action"] == "confirm_incident"
        )
    )

    return [
        hour,
        day,
        hours_from_typical,
        1.0,
        0.0,
        0.0,
        is_new_device,
        is_new_family,
        float(log_minutes_since_last),
        login_count_24h,
        float(failed_count),
        passkey_count,
        passkey_age,
        new_passkey,
        passkey_last_used,
        concurrent_count,
        float(len(active_subsystems)),
        float(weekday_usage),
        float(scope_sensitivity),
        ever_changed_permission,
        float(permission_change_age),
        confirmed_incidents,
        0.0,
    ]


def build_feature_snapshots(
    events: list[dict[str, Any]],
    users_config: dict[str, Any] | None = None,
    subsystem_config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    users_config = users_config or load_config("users")
    subsystem_config = subsystem_config or load_config("subsystems")
    users = users_config["users"]
    if not events:
        return []
    _assert_alias_only(events)
    first_event_at = min(parse_timestamp(event["created_at"]) for event in events)
    states = _initial_states(users, first_event_at)
    snapshots: list[dict[str, Any]] = []

    normal_events = sorted(
        (event for event in events if event["history_mode"] == "sequential"),
        key=lambda item: (item["created_at"], item["sequence_no"]),
    )
    attack_events = sorted(
        (event for event in events if event["history_mode"] == "frozen_normal_snapshot"),
        key=lambda item: (item["created_at"], item["sequence_no"]),
    )

    for event in normal_events + attack_events:
        state = states[event["profile_id"]]
        values = extract_features(event, state, subsystem_config)
        snapshot = {
            "run_id": event["run_id"],
            "event_id": event["event_id"],
            "profile_id": event["profile_id"],
            "created_at": event["created_at"],
            "split": event["split"],
            "scenario": event["scenario"],
            "ground_truth": event["ground_truth"],
            "label": event["label"],
            **dict(zip(FEATURE_NAMES, values, strict=True)),
        }
        snapshots.append(snapshot)

        if event["history_mode"] == "sequential":
            now = parse_timestamp(event["created_at"])
            state.sessions.append(
                SessionRecord(
                    created_at=now,
                    logout_at=now + timedelta(minutes=SESSION_DURATION_MINUTES),
                    user_agent=event["user_agent"],
                    browser=event["browser"],
                    subsystem_key=event["subsystem_key"],
                    login_method=event["login_method"],
                )
            )
            state.session_times.append(now)
            if event["user_agent"]:
                state.seen_user_agents.add(event["user_agent"])
            if event["browser"]:
                state.seen_families.add(event["browser"])
            if event["login_method"] == "passkey" and state.passkeys:
                state.passkeys[-1].last_used_at = now

    snapshots.sort(key=lambda item: (item["created_at"], item["event_id"]))
    return snapshots


def _create_schema(connection: sqlite3.Connection) -> None:
    feature_columns = ",\n".join(f'"{name}" REAL NOT NULL' for name in FEATURE_NAMES)
    connection.executescript(
        f"""
        CREATE TABLE metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE profiles (
            profile_id TEXT PRIMARY KEY,
            user_type TEXT NOT NULL,
            policy_json TEXT NOT NULL
        );
        CREATE TABLE subsystems (
            subsystem_key TEXT PRIMARY KEY,
            policy_json TEXT NOT NULL
        );
        CREATE TABLE raw_events (
            event_id TEXT PRIMARY KEY,
            sequence_no INTEGER NOT NULL,
            profile_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            split TEXT NOT NULL,
            scenario TEXT NOT NULL,
            ground_truth TEXT NOT NULL,
            label INTEGER NOT NULL,
            history_mode TEXT NOT NULL,
            payload_json TEXT NOT NULL
        );
        CREATE TABLE setup_actions (
            event_id TEXT NOT NULL,
            ordinal INTEGER NOT NULL,
            action TEXT NOT NULL,
            count INTEGER NOT NULL,
            offset_minutes INTEGER NOT NULL,
            subsystem_key TEXT,
            PRIMARY KEY (event_id, ordinal)
        );
        CREATE TABLE feature_snapshots (
            event_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            profile_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            split TEXT NOT NULL,
            scenario TEXT NOT NULL,
            ground_truth TEXT NOT NULL,
            label INTEGER NOT NULL,
            {feature_columns}
        );
        CREATE INDEX idx_raw_events_profile_time
            ON raw_events(profile_id, created_at);
        CREATE INDEX idx_features_split
            ON feature_snapshots(split, profile_id);
        """
    )


def load_run_store(run_dir: Path) -> dict[str, Any]:
    """Build a fresh per-run SQLite store and feature JSONL atomically."""
    manifest_path = run_dir / "manifest.json"
    events_path = run_dir / "events.jsonl"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    events = [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    _assert_alias_only(manifest)
    _assert_alias_only(events)
    if any(event["run_id"] != manifest["run_id"] for event in events):
        raise ValueError("event run_id does not match manifest")

    users_config = load_config("users")
    subsystem_config = load_config("subsystems")
    snapshots = build_feature_snapshots(events, users_config, subsystem_config)

    database_path = run_dir / "experiment.sqlite3"
    temporary_database = run_dir / "experiment.sqlite3.tmp"
    if temporary_database.exists():
        temporary_database.unlink()
    connection = sqlite3.connect(temporary_database)
    try:
        _create_schema(connection)
        connection.executemany(
            "INSERT INTO metadata(key, value) VALUES (?, ?)",
            [
                ("manifest", json.dumps(manifest, ensure_ascii=False, sort_keys=True)),
                ("feature_count", str(len(FEATURE_NAMES))),
            ],
        )
        connection.executemany(
            "INSERT INTO profiles(profile_id, user_type, policy_json) VALUES (?, ?, ?)",
            [
                (
                    user["profile_id"],
                    user["user_type"],
                    json.dumps(user, ensure_ascii=False, sort_keys=True),
                )
                for user in users_config["users"]
            ],
        )
        connection.executemany(
            "INSERT INTO subsystems(subsystem_key, policy_json) VALUES (?, ?)",
            [
                (key, json.dumps(value, ensure_ascii=False, sort_keys=True))
                for key, value in subsystem_config["subsystems"].items()
            ],
        )
        connection.executemany(
            """
            INSERT INTO raw_events(
                event_id, sequence_no, profile_id, created_at, split, scenario,
                ground_truth, label, history_mode, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    event["event_id"],
                    event["sequence_no"],
                    event["profile_id"],
                    event["created_at"],
                    event["split"],
                    event["scenario"],
                    event["ground_truth"],
                    event["label"],
                    event["history_mode"],
                    json.dumps(event, ensure_ascii=False, sort_keys=True),
                )
                for event in events
            ],
        )
        connection.executemany(
            """
            INSERT INTO setup_actions(
                event_id, ordinal, action, count, offset_minutes, subsystem_key
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    event["event_id"],
                    ordinal,
                    action["action"],
                    action["count"],
                    action["offset_minutes"],
                    action.get("subsystem_key"),
                )
                for event in events
                for ordinal, action in enumerate(event["setup_actions"])
            ],
        )
        feature_names_sql = ", ".join(f'"{name}"' for name in FEATURE_NAMES)
        placeholders = ", ".join("?" for _ in range(8 + len(FEATURE_NAMES)))
        insert_sql = f"""
            INSERT INTO feature_snapshots(
                event_id, run_id, profile_id, created_at, split, scenario,
                ground_truth, label, {feature_names_sql}
            ) VALUES ({placeholders})
        """
        connection.executemany(
            insert_sql,
            [
                (
                    snapshot["event_id"],
                    snapshot["run_id"],
                    snapshot["profile_id"],
                    snapshot["created_at"],
                    snapshot["split"],
                    snapshot["scenario"],
                    snapshot["ground_truth"],
                    snapshot["label"],
                    *(snapshot[name] for name in FEATURE_NAMES),
                )
                for snapshot in snapshots
            ],
        )
        connection.commit()
    finally:
        connection.close()
    temporary_database.replace(database_path)

    feature_path = run_dir / "feature_snapshots.jsonl"
    temporary_features = run_dir / "feature_snapshots.jsonl.tmp"
    with temporary_features.open("w", encoding="utf-8") as handle:
        for snapshot in snapshots:
            handle.write(json.dumps(snapshot, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
    temporary_features.replace(feature_path)

    counts = {
        "train_count": sum(item["split"] == "train" for item in snapshots),
        "normal_test_count": sum(
            item["split"] == "normal_test" for item in snapshots
        ),
        "attack_count": sum(item["split"] == "attack_test" for item in snapshots),
    }
    return {
        "manifest": manifest,
        "database_path": database_path,
        "feature_path": feature_path,
        "snapshot_count": len(snapshots),
        **counts,
    }
