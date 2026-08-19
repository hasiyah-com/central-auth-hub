from __future__ import annotations

import sys
import unittest
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rba_experiment.contracts import CONTRACT_DIR, load_config, load_json  # noqa: E402
from rba_experiment.generator import generate_run  # noqa: E402

GIT_SHA = "a" * 40
LOCAL_TZ = ZoneInfo("Asia/Bangkok")


class GeneratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.users_config = load_config("users")
        cls.users = cls.users_config["users"]
        cls.by_profile = {user["profile_id"]: user for user in cls.users}
        cls.staggered, cls.staggered_manifest = generate_run(
            dataset_size=10,
            seed=42,
            normal_scenario="normal_staggered",
            git_commit_sha=GIT_SHA,
        )
        cls.burst, cls.burst_manifest = generate_run(
            dataset_size=10,
            seed=42,
            normal_scenario="normal_nat_burst",
            git_commit_sha=GIT_SHA,
        )

    def normal_events(self, events):
        return [event for event in events if event["ground_truth"] == "normal"]

    def attack_events(self, events):
        return [event for event in events if event["ground_truth"] == "attack"]

    def test_counts_and_split_per_profile(self):
        for events in (self.staggered, self.burst):
            normal = self.normal_events(events)
            attack = self.attack_events(events)
            self.assertEqual(len(normal), 12 * 10)
            self.assertEqual(len(attack), 12 * 20)

            by_profile = defaultdict(list)
            for event in normal:
                by_profile[event["profile_id"]].append(event)
            self.assertEqual(set(by_profile), set(self.by_profile))
            for profile_events in by_profile.values():
                profile_events.sort(key=lambda event: event["created_at"])
                self.assertEqual(
                    [event["split"] for event in profile_events],
                    ["train"] * 8 + ["normal_test"] * 2,
                )

    def test_all_outputs_are_alias_only(self):
        forbidden = {
            "email",
            "full_name",
            "identifier",
            "subsystem_id",
            "user_id",
        }

        def keys(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    yield key
                    yield from keys(child)
            elif isinstance(value, list):
                for child in value:
                    yield from keys(child)

        for events in (self.staggered, self.burst):
            self.assertFalse(forbidden & set(keys(events)))
            for event in events:
                self.assertEqual(event["ip"], "192.168.10.1")

    def test_generated_rows_match_contract_keys(self):
        event_schema = load_json(CONTRACT_DIR / "login_event.schema.json")
        manifest_schema = load_json(CONTRACT_DIR / "run_manifest.schema.json")
        event_keys = set(event_schema["properties"])
        event_required = set(event_schema["required"])
        manifest_keys = set(manifest_schema["properties"])
        manifest_required = set(manifest_schema["required"])

        for event in self.staggered + self.burst:
            self.assertEqual(set(event), event_keys)
            self.assertTrue(event_required <= set(event))
        for manifest in (self.staggered_manifest, self.burst_manifest):
            self.assertEqual(set(manifest), manifest_keys)
            self.assertTrue(manifest_required <= set(manifest))

    def test_normal_access_and_admin_mfa(self):
        for event in self.normal_events(self.staggered):
            user = self.by_profile[event["profile_id"]]
            self.assertIn(event["subsystem_key"], user["allowed_subsystems"] + [None])
            if event["subsystem_key"] is None:
                self.assertFalse(user["allowed_subsystems"])
            if user["is_hub_admin"]:
                self.assertTrue(event["mfa_required"])
                self.assertTrue(event["mfa_passed"])
                self.assertEqual(event["login_method"], "passkey")

    def test_normal_events_stay_in_profile_hours(self):
        for events in (self.staggered, self.burst):
            for event in self.normal_events(events):
                local = datetime.fromisoformat(
                    event["created_at"].replace("Z", "+00:00")
                ).astimezone(LOCAL_TZ)
                ranges = self.by_profile[event["profile_id"]]["normal_hours"]
                self.assertTrue(
                    any(start <= local.hour <= end for start, end in ranges),
                    (event["profile_id"], local.isoformat()),
                )

    def test_staggered_has_at_most_five_distinct_users_per_rolling_hour(self):
        rows = sorted(
            (
                datetime.fromisoformat(event["created_at"].replace("Z", "+00:00")),
                event["profile_id"],
            )
            for event in self.normal_events(self.staggered)
        )
        counts = Counter()
        left = 0
        max_distinct = 0
        for right, (timestamp, profile_id) in enumerate(rows):
            counts[profile_id] += 1
            while timestamp - rows[left][0] >= timedelta(hours=1):
                old_profile = rows[left][1]
                counts[old_profile] -= 1
                if counts[old_profile] == 0:
                    del counts[old_profile]
                left += 1
            max_distinct = max(max_distinct, len(counts))
        self.assertLessEqual(max_distinct, 5)

    def test_nat_burst_has_at_least_six_distinct_users_in_an_hour(self):
        hourly_profiles = defaultdict(set)
        for event in self.normal_events(self.burst):
            local = datetime.fromisoformat(
                event["created_at"].replace("Z", "+00:00")
            ).astimezone(LOCAL_TZ)
            hourly_profiles[(local.date(), local.hour)].add(event["profile_id"])
        self.assertGreaterEqual(max(map(len, hourly_profiles.values())), 6)
        self.assertIn(12, map(len, hourly_profiles.values()))

    def test_attacks_use_frozen_normal_snapshot(self):
        attacks = self.attack_events(self.staggered)
        self.assertTrue(attacks)
        for event in attacks:
            self.assertEqual(event["split"], "attack_test")
            self.assertEqual(event["history_mode"], "frozen_normal_snapshot")
            self.assertEqual(event["label"], 1)
            self.assertEqual(event["attack_type"], event["scenario"])

        combined = [
            event for event in attacks if event["scenario"] == "attack_combined_ato"
        ]
        action_names = {item["action"] for item in combined[0]["setup_actions"]}
        self.assertEqual(
            action_names,
            {
                "failed_login",
                "successful_login",
                "open_session",
                "add_passkey",
                "change_permission",
                "confirm_incident",
            },
        )

    def test_event_ids_and_sequence_are_unique_and_stable(self):
        event_ids = [event["event_id"] for event in self.staggered]
        self.assertEqual(len(event_ids), len(set(event_ids)))
        self.assertEqual(
            [event["sequence_no"] for event in self.staggered],
            list(range(len(self.staggered))),
        )
        repeated, repeated_manifest = generate_run(
            dataset_size=10,
            seed=42,
            normal_scenario="normal_staggered",
            git_commit_sha=GIT_SHA,
        )
        self.assertEqual(repeated, self.staggered)
        self.assertEqual(repeated_manifest, self.staggered_manifest)

    def test_manifests_separate_normal_scenarios(self):
        self.assertEqual(
            self.staggered_manifest["normal_scenario"],
            "normal_staggered",
        )
        self.assertEqual(
            self.burst_manifest["normal_scenario"],
            "normal_nat_burst",
        )
        self.assertNotEqual(
            self.staggered_manifest["run_id"],
            self.burst_manifest["run_id"],
        )
        self.assertEqual(len(self.staggered_manifest["local_mapping_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
