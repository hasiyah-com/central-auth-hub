from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import population_real_seeded_v1 as P  # noqa: E402


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
