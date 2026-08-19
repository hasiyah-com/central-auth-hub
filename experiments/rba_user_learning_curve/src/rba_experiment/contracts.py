"""Standard-library validation for experiment configuration and contracts.

This module intentionally has no application or ML dependency. It validates the
contract before later phases are allowed to generate events or touch a database.
"""

from __future__ import annotations

import ipaddress
import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
CONTRACT_DIR = ROOT / "contracts"

FEATURE_NAMES = [
    "hour_of_day",
    "day_of_week",
    "hours_from_typical_login_time",
    "is_thailand",
    "is_new_country",
    "country_change_count_30d",
    "is_new_device",
    "is_new_user_agent_family",
    "log_minutes_since_last_login",
    "login_count_24h",
    "failed_logins_24h",
    "passkey_count",
    "passkey_age_days",
    "new_passkey_recently_added",
    "passkey_last_used_days",
    "concurrent_session_count",
    "active_subsystem_count",
    "weekday_usage_score",
    "scope_sensitivity_score",
    "ever_changed_permission",
    "permission_change_age",
    "confirmed_incident_count",
    "impossible_travel_score",
]

SENSITIVE_IDENTITY_KEYS = {
    "email",
    "full_name",
    "google_sub",
    "identifier",
    "line_sub",
    "owner_email",
    "owner_user_id",
    "subsystem_id",
    "user_id",
}


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def load_config(name: str) -> dict[str, Any]:
    return load_json(CONFIG_DIR / f"{name}.json")


def canonical_sha256(value: dict[str, Any]) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def assert_no_resolved_identities(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        forbidden = SENSITIVE_IDENTITY_KEYS & set(value)
        assert not forbidden, f"{path} contains resolved identity keys: {sorted(forbidden)}"
        for key, child in value.items():
            assert_no_resolved_identities(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            assert_no_resolved_identities(child, f"{path}[{index}]")


def validate_experiment(config: dict[str, Any]) -> None:
    assert config["timezone"] == "Asia/Bangkok"
    assert config["storage_timezone"] == "UTC"
    assert ipaddress.ip_address(config["fixed_ip"]).is_private
    assert config["fixed_ip"] == "192.168.10.1"
    assert config["geo_country"] is None
    assert config["geo_city"] is None
    assert config["dataset_sizes_per_user"] == [10, 50, 100, 500, 1000, 5000]
    assert config["train_fraction"] == 0.8
    assert len(config["seeds"]) >= 5
    assert len(config["seeds"]) == len(set(config["seeds"]))
    assert config["trusted_decisions"] == ["allow", "mfa_passed"]
    assert config["model"]["type"] == "IsolationForest"
    assert config["model"]["scope"] == "global"
    assert config["feature_names"] == FEATURE_NAMES
    assert len(config["feature_names"]) == 23
    assert config["no_geo_expected_features"] == {
        "is_thailand": 1.0,
        "is_new_country": 0.0,
        "country_change_count_30d": 0.0,
        "impossible_travel_score": 0.0,
    }


def validate_users(
    users_config: dict[str, Any], subsystems_config: dict[str, Any]
) -> None:
    assert users_config["identity_mode"] == "profile_alias"
    assert subsystems_config["identity_mode"] == "profile_alias"
    assert_no_resolved_identities(users_config)
    assert_no_resolved_identities(subsystems_config)

    users = users_config["users"]
    subsystems = subsystems_config["subsystems"]
    subsystem_keys = set(subsystems)

    assert len(users) == 12
    profile_ids = [user["profile_id"] for user in users]
    assert len(profile_ids) == len(set(profile_ids)), "duplicate profile_id"
    by_profile = {user["profile_id"]: user for user in users}

    for user in users:
        assert set(user["allowed_subsystems"]) <= subsystem_keys
        assert set(user["owned_subsystems"]) <= subsystem_keys
        assert set(user["owned_subsystems"]) <= set(user["allowed_subsystems"])
        assert user["devices"]
        assert abs(sum(device["weight"] for device in user["devices"]) - 1.0) < 1e-9
        assert all(0 <= day <= 6 for day in user["normal_days"])
        assert all(0 <= start <= end <= 23 for start, end in user["normal_hours"])

        if user["user_type"] == "student":
            assert set(user["allowed_subsystems"]) == subsystem_keys

        if user["is_hub_admin"]:
            assert user["user_type"] == "admin"
            assert user["mfa_always"] is True
            assert user["mfa_preferred_factor"] == "passkey"
            assert set(user["allowed_subsystems"]) == set(user["owned_subsystems"])

    assert by_profile["staff_library_only"]["allowed_subsystems"] == ["library"]
    assert by_profile["staff_dorm_only"]["allowed_subsystems"] == ["dorm"]

    hub_only_admin = by_profile["admin_hub_only"]
    assert hub_only_admin["allowed_subsystems"] == []
    assert hub_only_admin["owned_subsystems"] == []

    for key, subsystem in subsystems.items():
        assert subsystem["scope"]
        assert len(subsystem["scope"]) == len(set(subsystem["scope"]))
        owner = by_profile[subsystem["owner_profile_id"]]
        assert key in owner["owned_subsystems"]


def validate_local_mapping(
    mapping: dict[str, Any],
    users_config: dict[str, Any],
    subsystems_config: dict[str, Any],
    *,
    allow_example_values: bool = False,
) -> str:
    assert mapping["version"] == 1
    expected_profiles = {user["profile_id"] for user in users_config["users"]}
    expected_subsystems = set(subsystems_config["subsystems"])
    assert set(mapping["profiles"]) == expected_profiles
    assert set(mapping["subsystems"]) == expected_subsystems

    user_ids: list[str] = []
    emails: list[str] = []
    for profile_id, resolved in mapping["profiles"].items():
        assert set(resolved) == {"user_id", "email"}, profile_id
        UUID(resolved["user_id"])
        email = resolved["email"].strip().lower()
        assert "@" in email and not email.startswith("@") and not email.endswith("@")
        if not allow_example_values:
            assert not email.endswith(".invalid"), f"{profile_id} still uses example email"
            assert not resolved["user_id"].startswith("00000000-0000-0000-0000-")
        user_ids.append(resolved["user_id"])
        emails.append(email)

    subsystem_ids: list[str] = []
    for subsystem_key, resolved in mapping["subsystems"].items():
        assert set(resolved) == {"subsystem_id"}, subsystem_key
        UUID(resolved["subsystem_id"])
        if not allow_example_values:
            assert not resolved["subsystem_id"].startswith(
                "00000000-0000-0000-0000-"
            )
        subsystem_ids.append(resolved["subsystem_id"])

    assert len(user_ids) == len(set(user_ids)), "duplicate mapped user_id"
    assert len(emails) == len(set(emails)), "duplicate mapped email"
    assert len(subsystem_ids) == len(set(subsystem_ids)), "duplicate subsystem_id"
    return canonical_sha256(mapping)


def validate_scenarios(config: dict[str, Any]) -> None:
    scenarios = config["scenarios"]
    staggered = scenarios["normal_staggered"]
    burst = scenarios["normal_nat_burst"]

    assert staggered["ground_truth"] == "normal" and staggered["label"] == 0
    assert staggered["max_distinct_users_per_rolling_hour"] == 5
    assert burst["ground_truth"] == "normal" and burst["label"] == 0
    assert burst["min_distinct_users_per_rolling_hour"] >= 6
    assert burst["expected_rule"] == "multi_account_ip"

    forbidden_geo_terms = ("country", "foreign", "travel", "geo")
    for name, scenario in scenarios.items():
        assert not any(term in name for term in forbidden_geo_terms)
        if name.startswith("attack_"):
            assert scenario["ground_truth"] == "attack"
            assert scenario["label"] == 1


def validate_schemas() -> None:
    expected = {
        "combined_run_result.schema.json",
        "local_identity_mapping.schema.json",
        "login_event.schema.json",
        "feature_snapshot.schema.json",
        "prediction.schema.json",
        "metrics.schema.json",
        "run_manifest.schema.json",
    }
    actual = {path.name for path in CONTRACT_DIR.glob("*.schema.json")}
    assert actual == expected

    for path in sorted(CONTRACT_DIR.glob("*.schema.json")):
        schema = load_json(path)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        assert schema["required"]
        assert schema["properties"]
        assert set(schema["required"]) <= set(schema["properties"])

    feature_schema = load_json(CONTRACT_DIR / "feature_snapshot.schema.json")
    required = set(feature_schema["required"])
    assert set(FEATURE_NAMES) <= required
    assert "profile_id" in required and "user_id" not in required

    login_schema = load_json(CONTRACT_DIR / "login_event.schema.json")
    assert "profile_id" in login_schema["required"]
    assert "user_id" not in login_schema["properties"]
    assert "email" not in login_schema["properties"]
    assert {"history_mode", "setup_actions"} <= set(login_schema["required"])

    prediction_schema = load_json(CONTRACT_DIR / "prediction.schema.json")
    assert "profile_id" in prediction_schema["required"]
    assert "user_id" not in prediction_schema["properties"]

    manifest_schema = load_json(CONTRACT_DIR / "run_manifest.schema.json")
    assert "local_mapping_sha256" in manifest_schema["required"]
    assert "normal_scenario" in manifest_schema["required"]


def validate_all() -> None:
    experiment = load_config("experiment")
    users = load_config("users")
    subsystems = load_config("subsystems")
    scenarios = load_config("scenarios")
    validate_experiment(experiment)
    validate_users(users, subsystems)
    validate_scenarios(scenarios)
    validate_schemas()
    example_mapping = load_json(CONFIG_DIR / "local_identity_mapping.example.json")
    validate_local_mapping(
        example_mapping,
        users,
        subsystems,
        allow_example_values=True,
    )
