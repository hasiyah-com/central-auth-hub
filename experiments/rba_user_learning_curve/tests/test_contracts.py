from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rba_experiment.contracts import (  # noqa: E402
    FEATURE_NAMES,
    CONFIG_DIR,
    canonical_sha256,
    load_json,
    load_config,
    validate_all,
    validate_experiment,
    validate_local_mapping,
    validate_scenarios,
    validate_schemas,
    validate_users,
)


class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.experiment = load_config("experiment")
        cls.users = load_config("users")
        cls.subsystems = load_config("subsystems")
        cls.scenarios = load_config("scenarios")

    def test_all_contracts(self):
        validate_all()

    def test_experiment_contract(self):
        validate_experiment(self.experiment)
        self.assertEqual(len(FEATURE_NAMES), 23)

    def test_user_and_access_contract(self):
        validate_users(self.users, self.subsystems)

    def test_scenario_contract(self):
        validate_scenarios(self.scenarios)

    def test_json_schema_documents(self):
        validate_schemas()

    def test_chronological_80_20_counts(self):
        expected = {
            10: (8, 2),
            50: (40, 10),
            100: (80, 20),
            500: (400, 100),
            1000: (800, 200),
            5000: (4000, 1000),
        }
        fraction = self.experiment["train_fraction"]
        actual = {
            size: (int(size * fraction), size - int(size * fraction))
            for size in self.experiment["dataset_sizes_per_user"]
        }
        self.assertEqual(actual, expected)

    def test_admin_mfa_and_ownership(self):
        admins = [u for u in self.users["users"] if u["is_hub_admin"]]
        self.assertEqual(
            {u["profile_id"] for u in admins},
            {"admin_dorm_owner", "admin_hub_only"},
        )
        for admin in admins:
            self.assertTrue(admin["mfa_always"])
            self.assertEqual(admin["mfa_preferred_factor"], "passkey")
            self.assertEqual(
                set(admin["allowed_subsystems"]),
                set(admin["owned_subsystems"]),
            )

    def test_git_configs_have_no_resolved_identity_fields(self):
        forbidden = {
            "email",
            "full_name",
            "identifier",
            "owner_email",
            "owner_user_id",
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

        self.assertFalse(forbidden & set(keys(self.users)))
        self.assertFalse(forbidden & set(keys(self.subsystems)))

    def test_local_mapping_preflight_and_stable_hash(self):
        mapping = load_json(CONFIG_DIR / "local_identity_mapping.example.json")
        digest = validate_local_mapping(
            mapping,
            self.users,
            self.subsystems,
            allow_example_values=True,
        )
        self.assertEqual(digest, canonical_sha256(mapping))
        self.assertEqual(len(digest), 64)
        with self.assertRaises(AssertionError):
            validate_local_mapping(mapping, self.users, self.subsystems)

    def test_nat_burst_stays_normal_ground_truth(self):
        burst = self.scenarios["scenarios"]["normal_nat_burst"]
        self.assertEqual(burst["label"], 0)
        self.assertEqual(burst["ground_truth"], "normal")
        self.assertGreaterEqual(burst["min_distinct_users_per_rolling_hour"], 6)


if __name__ == "__main__":
    unittest.main()
