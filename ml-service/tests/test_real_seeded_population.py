from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import population_real_seeded_v1 as P  # noqa: E402
import population_real_seeded_v2 as P2  # noqa: E402
import gen_v3 as G3  # noqa: E402


PROTOTYPES = [
    {
        "rows": 50,
        "hour_peaks": [8, 15],
        "hour_spread": 2.0,
        "weekend_rate": 0.1,
        "devices": {"win10_chrome151": 0.8, "iphone_safari": 0.2},
        "drift": 0.1,
        "subsystems": {"HUB": 0.9, "SUB_A": 0.1},
        "sticky": 0.9,
        "dur": (3.0, 1.5),
        "overlap": 0.02,
        "active_sub": 2,
        "methods": {"google": 1.0},
        "passkey": {"count": 1, "age_days": 30, "last_used_days": 2},
        "fail_rate": 0.01,
        "scope": 0.3,
        "perm_age": 100,
        "incidents": 0,
        "mfa_always": False,
    },
    {
        "rows": 80,
        "hour_peaks": [12],
        "hour_spread": 3.0,
        "weekend_rate": 0.3,
        "devices": {"android10_k": 1.0},
        "drift": 0.05,
        "subsystems": {"HUB": 1.0},
        "sticky": 1.0,
        "dur": (2.8, 1.7),
        "overlap": 0.0,
        "active_sub": 1,
        "methods": {"passkey": 1.0},
        "passkey": {"count": 0, "age_days": 0, "last_used_days": 0},
        "fail_rate": 0.0,
        "scope": 0.5,
        "perm_age": 365,
        "incidents": 0,
        "mfa_always": True,
    },
]

for _prototype in PROTOTYPES:
    _prototype["observed_login_rate_per_day"] = 0.5


def test_population_is_deterministic_aliased_and_split_before_holdout():
    one = P.generate_population(PROTOTYPES)
    two = P.generate_population(PROTOTYPES)
    assert one == two
    assert [x["alias"] for x in one] == [f"R{i:02d}" for i in range(1, 49)]
    validation, holdout = P.split_population(one)
    assert len(validation) == 32
    assert len(holdout) == 16
    assert not ({x["alias"] for x in validation} & {x["alias"] for x in holdout})


def test_privacy_scan_rejects_direct_identifiers(tmp_path):
    safe = tmp_path / "safe.json"
    safe.write_text('{"alias":"R01"}', encoding="utf-8")
    assert P.privacy_scan([safe])["passed"]
    unsafe = tmp_path / "unsafe.json"
    unsafe.write_text('{"email":"person@gmail.com"}', encoding="utf-8")
    assert not P.privacy_scan([unsafe])["passed"]


def test_v2_population_adds_only_synthetic_cadence_controls():
    one = P2.generate_population(PROTOTYPES)
    two = P2.generate_population(PROTOTYPES)
    assert one == two
    assert [x["alias"] for x in one] == [f"V{i:02d}" for i in range(1, 49)]
    assert {x["episode_days"] for x in one} == {100}
    assert all(x["episode_age_carry"] is True for x in one)
    assert all("observed_login_rate_per_day" not in x for x in one)
    validation, holdout = P2.split_population(one)
    assert len(validation) == 32
    assert len(holdout) == 16
    assert not ({x["alias"] for x in validation} & {x["alias"] for x in holdout})


def test_episode_cadence_and_age_carry_are_opt_in():
    original = PROTOTYPES[0]
    assert G3._episode_days(original) == G3.EPISODE_DAYS
    unchanged = G3._profile_for_episode(original, ep_index=3, days=100)
    assert unchanged["perm_age"] == original["perm_age"]
    assert unchanged["passkey"]["age_days"] == original["passkey"]["age_days"]

    v2 = {
        **original,
        "episode_days": 100,
        "episode_age_carry": True,
    }
    carried = G3._profile_for_episode(v2, ep_index=2, days=100)
    assert G3._episode_days(v2) == 100
    assert carried["perm_age"] == 300
    assert carried["passkey"]["age_days"] == 230
    assert carried["passkey"]["last_used_days"] == 202
    assert original["passkey"]["age_days"] == 30
