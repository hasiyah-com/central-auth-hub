"""V4 synthetic corrections; V3 generator and its frozen results stay reproducible.

Repairs attack snapshot time, passkey flags/state, campaign rolling context, and
exposes campaign-like legitimate logins as normal validation examples.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path

import features_v2 as FE
import gen_v3 as V3
import build_profiles_v2 as BP


def _before(row: dict, now: str) -> bool:
    return row["created_at"] < now


def _as_of_state(row: dict, previous: dict | None) -> dict:
    """Age existing credentials from prior normal state; preserve a new passkey."""
    current = dict(row)
    newly_added = current["new_passkey_recently_added"] in (True, "True")
    if previous is not None and not newly_added and int(previous["passkey_count"]) == 0:
        current["passkey_age_days"] = 0
        current["passkey_last_used_days"] = 0
    elif previous is not None and not newly_added:
        days = max(
            0,
            (
                datetime.strptime(current["created_at"], FE.TS)
                - datetime.strptime(previous["created_at"], FE.TS)
            ).days,
        )
        current["passkey_age_days"] = min(
            3650, int(previous["passkey_age_days"]) + days
        )
        current["passkey_last_used_days"] = min(
            3650, int(previous["passkey_last_used_days"]) + days
        )
    # FE.compute expects CSV strings whereas the in-memory generator uses booleans.
    current["new_passkey_recently_added"] = "True" if newly_added else "False"
    return current


def _recompute(rows: list[dict], normals: list[dict], last_episode: int) -> list:
    normals = sorted(normals, key=lambda row: row["created_at"])
    out = []
    previous_by_family: dict[str, list[dict]] = defaultdict(list)
    for row in sorted(rows, key=lambda item: item["created_at"]):
        now = row["created_at"]
        family = row.get("scenario", "")
        if row["row_kind"] == "context":
            previous_by_family[family].append(row)
            continue
        earlier = [r for r in normals if _before(r, now)]
        previous = earlier[-1] if earlier else None
        # Keep all previously seen device signatures without scanning 5,000 rows.
        signatures = {r["device_signature"]: r for r in earlier[:-50]}
        trusted = sorted(
            list(signatures.values()) + earlier[-50:], key=lambda r: r["created_at"]
        )
        prior = previous_by_family[family]
        observed = sorted(
            [r for r in earlier if r.get("episode") == last_episode]
            + prior,
            key=lambda r: r["created_at"],
        )
        current = _as_of_state(row, previous)
        vector = FE.compute(current, trusted, observed)
        out.append((row, vector))
        prior.append(current)
    return out


def build_seed(users_xlsx: Path, seed: int, spec: list[dict], roster: dict) -> dict:
    BP.SEED = seed
    rng = BP.random.Random(seed)
    ids = BP.load_identities(users_xlsx)
    users = {}
    for profile in spec:
        p = dict(profile)
        p["email"] = roster[p["alias"]]
        ident = ids[p["email"]]
        total = V3.TRAIN_POOL + V3.VAL_N + V3.TEST_N
        episodes = V3.gen_normal_episodes(p, ident, rng, total)
        feat_episodes, _ = V3.features_by_episode(episodes)
        all_normal = [r for episode in episodes for r in episode]
        all_features = [f for episode in feat_episodes for f in episode]
        features = [[float(f[col]) for col in FE.FEATURES] for f in all_features]
        train_end, val_end = V3.TRAIN_POOL, V3.TRAIN_POOL + V3.VAL_N
        last_index = len(episodes) - 1
        users[p["alias"]] = {
            "train_raw": all_normal[:train_end],
            "train_ft": features[:train_end],
            "train_episodes": [len(episode) for episode in episodes],
            "val_ft": features[train_end:val_end],
            "test": list(zip(all_normal[val_end:], features[val_end:])),
            "dev_attacks": _recompute(
                V3.gen_attack_pack(p, ident, rng, V3.DEV, last_index),
                all_normal,
                last_index,
            ),
            "final_attacks": _recompute(
                V3.gen_attack_pack(p, ident, rng, V3.FINAL, last_index),
                all_normal,
                last_index,
            ),
            "camp_like": _recompute(
                V3._camp_like_in_window(p, ident, rng, last_index),
                all_normal,
                last_index,
            ),
            "episode_of": [index for index, ep in enumerate(episodes) for _ in ep],
        }
    return users


def validation_split(user: dict, size: int) -> tuple[list, list, list, list]:
    """Normal-only train/calibration and labeled tuning with campaign-like normal."""
    train = user["train_ft"][:size]
    calibration = user["val_ft"][:500]
    tuning_normal = user["val_ft"][500:] + [v for _, v in user["camp_like"]]
    tuning_attack = user["dev_attacks"]
    assert all(row["label"] == 0 for row, _ in user["camp_like"])
    return train, calibration, tuning_normal, tuning_attack
