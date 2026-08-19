"""Deterministic, alias-only raw-event generator for the RBA experiment."""

from __future__ import annotations

import hashlib
import json
import random
import re
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from .contracts import (
    CONFIG_DIR,
    CONTRACT_DIR,
    canonical_sha256,
    load_config,
    load_json,
    validate_all,
    validate_local_mapping,
)

LOCAL_TZ = ZoneInfo("Asia/Bangkok")
BASE_DATE = date(2024, 1, 8)
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")

DEVICE_CATALOG: dict[str, dict[str, str]] = {
    "windows_chrome": {
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/151.0.0.0 Safari/537.36"
        ),
        "os_name": "Windows",
        "browser": "Chrome",
        "device_type": "desktop",
    },
    "android_chrome": {
        "user_agent": (
            "Mozilla/5.0 (Linux; Android 15) AppleWebKit/537.36 "
            "Chrome/151.0.0.0 Mobile Safari/537.36"
        ),
        "os_name": "Android",
        "browser": "Chrome",
        "device_type": "mobile",
    },
    "ios_mobile": {
        "user_agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
            "AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1"
        ),
        "os_name": "iOS",
        "browser": "Safari",
        "device_type": "mobile",
    },
    "ios_tablet": {
        "user_agent": (
            "Mozilla/5.0 (iPad; CPU OS 18_0 like Mac OS X) "
            "AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1"
        ),
        "os_name": "iPadOS",
        "browser": "Safari",
        "device_type": "tablet",
    },
}

ATTACK_DEVICES: dict[str, dict[str, str]] = {
    "new_device": {
        "user_agent": (
            "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) "
            "Gecko/20100101 Firefox/140.0"
        ),
        "os_name": "Linux",
        "browser": "Firefox",
        "device_type": "desktop",
    },
    "new_ua_family": {
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) "
            "Gecko/20100101 Firefox/140.0"
        ),
        "os_name": "Windows",
        "browser": "Firefox",
        "device_type": "desktop",
    },
    "new_os": {
        "user_agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "Chrome/151.0.0.0 Safari/537.36"
        ),
        "os_name": "Linux",
        "browser": "Chrome",
        "device_type": "desktop",
    },
}

STAGGERED_LAYOUT = {
    "student_01": (9, 0),
    "student_02": (9, 1),
    "student_03": (9, 2),
    "student_04": (9, 3),
    "student_05": (14, 0),
    "teacher_library_owner": (14, 1),
    "teacher_02": (14, 2),
    "staff_library_only": (14, 3),
    "student_06": (19, 0),
    "staff_dorm_only": (19, 1),
    "admin_dorm_owner": (19, 2),
    "admin_hub_only": (19, 3),
}


def _utc_iso(local_value: datetime) -> str:
    return (
        local_value.astimezone(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _local_datetime(day: date, hour: int, minute: int) -> datetime:
    return datetime.combine(day, time(hour=hour, minute=minute), tzinfo=LOCAL_TZ)


def _weighted_device(user: dict[str, Any], rng: random.Random) -> dict[str, str]:
    draw = rng.random()
    running = 0.0
    for option in user["devices"]:
        running += option["weight"]
        if draw <= running:
            return dict(DEVICE_CATALOG[option["key"]])
    return dict(DEVICE_CATALOG[user["devices"][-1]["key"]])


def _normal_subsystem(user: dict[str, Any], rng: random.Random) -> str | None:
    allowed = user["allowed_subsystems"]
    if not allowed:
        return None
    if len(allowed) == 1:
        return allowed[0]
    preferred = user["owned_subsystems"][0] if user["owned_subsystems"] else allowed[0]
    alternatives = [key for key in allowed if key != preferred]
    return preferred if rng.random() < 0.8 else rng.choice(alternatives)


def _lateral_subsystem(user: dict[str, Any]) -> str:
    allowed = set(user["allowed_subsystems"])
    for key in ("library", "dorm"):
        if key not in allowed:
            return key
    preferred = user["owned_subsystems"][0] if user["owned_subsystems"] else "dorm"
    return "library" if preferred == "dorm" else "dorm"


def _base_event(
    *,
    experiment_id: str,
    run_id: str,
    seed: int,
    dataset_size: int,
    profile_id: str,
    user_type: str,
    created_at: datetime,
    split: str,
    scenario: str,
    subsystem_key: str | None,
    device: dict[str, str],
    login_method: str,
    login_successful: bool,
    mfa_required: bool,
    mfa_passed: bool,
    ground_truth: str,
    label: int,
    attack_type: str | None,
    history_mode: str,
    setup_actions: list[dict[str, Any]],
    identity_name: str,
) -> dict[str, Any]:
    return {
        "experiment_id": experiment_id,
        "run_id": run_id,
        "seed": seed,
        "dataset_size": dataset_size,
        "event_id": str(uuid5(NAMESPACE_URL, identity_name)),
        "sequence_no": 0,
        "profile_id": profile_id,
        "user_type": user_type,
        "created_at": _utc_iso(created_at),
        "local_timezone": "Asia/Bangkok",
        "split": split,
        "scenario": scenario,
        "subsystem_key": subsystem_key,
        "ip": "192.168.10.1",
        **device,
        "login_method": login_method,
        "login_successful": login_successful,
        "mfa_required": mfa_required,
        "mfa_passed": mfa_passed,
        "ground_truth": ground_truth,
        "label": label,
        "attack_type": attack_type,
        "history_mode": history_mode,
        "setup_actions": setup_actions,
    }


def _normal_events(
    *,
    experiment: dict[str, Any],
    users: list[dict[str, Any]],
    dataset_size: int,
    seed: int,
    normal_scenario: str,
    run_id: str,
) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    train_count = int(dataset_size * experiment["train_fraction"])
    profile_order = {user["profile_id"]: index for index, user in enumerate(users)}
    events: list[dict[str, Any]] = []

    for user in users:
        profile_id = user["profile_id"]
        for index in range(dataset_size):
            day = BASE_DATE + timedelta(days=index // 2)
            slot = index % 2
            if normal_scenario == "normal_staggered":
                hour, member_index = STAGGERED_LAYOUT[profile_id]
                minute = member_index * 3 + slot * 25
            else:
                hour = 9
                minute = profile_order[profile_id] * 2 + slot * 25

            created_at = _local_datetime(day, hour, minute)
            split = "train" if index < train_count else "normal_test"
            device = _weighted_device(user, rng)
            subsystem_key = _normal_subsystem(user, rng)
            is_admin = user["is_hub_admin"]
            events.append(
                _base_event(
                    experiment_id=experiment["experiment_id"],
                    run_id=run_id,
                    seed=seed,
                    dataset_size=dataset_size,
                    profile_id=profile_id,
                    user_type=user["user_type"],
                    created_at=created_at,
                    split=split,
                    scenario=normal_scenario,
                    subsystem_key=subsystem_key,
                    device=device,
                    login_method="passkey" if is_admin else "google",
                    login_successful=True,
                    mfa_required=is_admin,
                    mfa_passed=is_admin,
                    ground_truth="normal",
                    label=0,
                    attack_type=None,
                    history_mode="sequential",
                    setup_actions=[],
                    identity_name=(
                        f"{run_id}:{profile_id}:normal:{index}:{normal_scenario}"
                    ),
                )
            )
    return events


def _setup_actions(
    scenario: str, subsystem_key: str | None
) -> list[dict[str, Any]]:
    if scenario == "attack_subsystem_lateral":
        return [
            {
                "action": "open_session",
                "count": 1,
                "offset_minutes": 30,
                "subsystem_key": "dorm",
            },
            {
                "action": "open_session",
                "count": 1,
                "offset_minutes": 20,
                "subsystem_key": "library",
            },
        ]

    action_map: dict[str, list[tuple[str, int, int]]] = {
        "attack_failed_spike": [("failed_login", 5, 60)],
        "attack_login_velocity": [("successful_login", 5, 10)],
        "attack_concurrent_sessions": [("open_session", 4, 15)],
        "attack_new_passkey": [("add_passkey", 1, 30)],
        "attack_permission_change": [("change_permission", 1, 120)],
        "attack_combined_ato": [
            ("failed_login", 6, 60),
            ("successful_login", 4, 10),
            ("open_session", 4, 15),
            ("add_passkey", 1, 30),
            ("change_permission", 1, 120),
            ("confirm_incident", 1, 2880),
        ],
    }
    actions = [
        {
            "action": action,
            "count": count,
            "offset_minutes": offset,
            "subsystem_key": subsystem_key,
        }
        for action, count, offset in action_map.get(scenario, [])
    ]
    if scenario == "attack_combined_ato":
        for action in actions:
            if action["action"] == "open_session":
                action["count"] = 2
                action["subsystem_key"] = "dorm"
                actions.append(
                    {
                        "action": "open_session",
                        "count": 2,
                        "offset_minutes": 12,
                        "subsystem_key": "library",
                    }
                )
                break
    return actions


def _attack_events(
    *,
    experiment: dict[str, Any],
    scenarios: dict[str, Any],
    users: list[dict[str, Any]],
    dataset_size: int,
    seed: int,
    run_id: str,
) -> list[dict[str, Any]]:
    rng = random.Random(seed + 10_000)
    attack_names = [name for name in scenarios["scenarios"] if name.startswith("attack_")]
    attack_count = experiment["attack_rows_per_user"]
    last_normal_day = BASE_DATE + timedelta(days=(dataset_size - 1) // 2)
    attack_start = last_normal_day + timedelta(days=7)
    events: list[dict[str, Any]] = []

    for user in users:
        profile_id = user["profile_id"]
        for index in range(attack_count):
            scenario = attack_names[index % len(attack_names)]
            subsystem_key = _normal_subsystem(user, rng)
            if scenario == "attack_subsystem_lateral":
                subsystem_key = _lateral_subsystem(user)

            normal_start, normal_end = user["normal_hours"][0]
            hour = (normal_start + normal_end) // 2
            minute = (index * 7) % 50
            if scenario in {"attack_off_hours", "attack_combined_ato"}:
                hour, minute = 2, 15
            created_at = _local_datetime(
                attack_start + timedelta(days=index),
                hour,
                minute,
            )

            device = _weighted_device(user, rng)
            if scenario == "attack_new_device" or scenario == "attack_combined_ato":
                device = dict(ATTACK_DEVICES["new_device"])
            elif scenario == "attack_new_ua_family":
                device = dict(ATTACK_DEVICES["new_ua_family"])
            elif scenario == "attack_new_os":
                device = dict(ATTACK_DEVICES["new_os"])

            is_admin = user["is_hub_admin"]
            events.append(
                _base_event(
                    experiment_id=experiment["experiment_id"],
                    run_id=run_id,
                    seed=seed,
                    dataset_size=dataset_size,
                    profile_id=profile_id,
                    user_type=user["user_type"],
                    created_at=created_at,
                    split="attack_test",
                    scenario=scenario,
                    subsystem_key=subsystem_key,
                    device=device,
                    login_method=(
                        "passkey"
                        if is_admin or scenario == "attack_new_passkey"
                        else "google"
                    ),
                    login_successful=not is_admin,
                    mfa_required=is_admin,
                    mfa_passed=False,
                    ground_truth="attack",
                    label=1,
                    attack_type=scenario,
                    history_mode="frozen_normal_snapshot",
                    setup_actions=_setup_actions(scenario, subsystem_key),
                    identity_name=f"{run_id}:{profile_id}:attack:{index}:{scenario}",
                )
            )
    return events


def _configuration_hash() -> str:
    return canonical_sha256(
        {
            "experiment": load_config("experiment"),
            "users": load_config("users"),
            "subsystems": load_config("subsystems"),
            "scenarios": load_config("scenarios"),
        }
    )


def generate_run(
    *,
    dataset_size: int,
    seed: int,
    normal_scenario: str,
    git_commit_sha: str,
    mapping_path: Path | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    validate_all()
    experiment = load_config("experiment")
    users_config = load_config("users")
    subsystems = load_config("subsystems")
    scenarios = load_config("scenarios")

    if dataset_size not in experiment["dataset_sizes_per_user"]:
        raise ValueError(f"unsupported dataset size: {dataset_size}")
    if seed not in experiment["seeds"]:
        raise ValueError(f"unsupported seed: {seed}")
    if normal_scenario not in experiment["normal_scenarios"]:
        raise ValueError(f"unsupported normal scenario: {normal_scenario}")
    if not SHA_PATTERN.fullmatch(git_commit_sha):
        raise ValueError("git_commit_sha must be 40 lowercase hexadecimal characters")

    mapping_file = mapping_path or CONFIG_DIR / "local_identity_mapping.json"
    mapping = load_json(mapping_file)
    mapping_hash = validate_local_mapping(mapping, users_config, subsystems)

    run_id = (
        f"{experiment['experiment_id']}-{normal_scenario}-"
        f"n{dataset_size}-s{seed}"
    )
    users = users_config["users"]
    events = _normal_events(
        experiment=experiment,
        users=users,
        dataset_size=dataset_size,
        seed=seed,
        normal_scenario=normal_scenario,
        run_id=run_id,
    )
    events.extend(
        _attack_events(
            experiment=experiment,
            scenarios=scenarios,
            users=users,
            dataset_size=dataset_size,
            seed=seed,
            run_id=run_id,
        )
    )
    events.sort(key=lambda event: (event["created_at"], event["profile_id"], event["event_id"]))
    for sequence_no, event in enumerate(events):
        event["sequence_no"] = sequence_no

    feature_contract_hash = hashlib.sha256(
        (CONTRACT_DIR / "feature_snapshot.schema.json").read_bytes()
    ).hexdigest()
    manifest = {
        "experiment_id": experiment["experiment_id"],
        "run_id": run_id,
        "git_commit_sha": git_commit_sha,
        "configuration_sha256": _configuration_hash(),
        "feature_contract_sha256": feature_contract_hash,
        "local_mapping_sha256": mapping_hash,
        "normal_scenario": normal_scenario,
        "dataset_size": dataset_size,
        "seed": seed,
        "thresholds": experiment["final_thresholds"],
        "model": experiment["model"],
    }
    return events, manifest


def write_run(
    events: list[dict[str, Any]],
    manifest: dict[str, Any],
    output_root: Path,
) -> tuple[Path, Path]:
    run_dir = output_root / manifest["run_id"]
    run_dir.mkdir(parents=True, exist_ok=True)
    events_path = run_dir / "events.jsonl"
    manifest_path = run_dir / "manifest.json"

    with events_path.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
    with manifest_path.open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    return events_path, manifest_path
