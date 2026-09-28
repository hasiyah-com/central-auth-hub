"""V5 synthetic generator with production-compatible device signatures."""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "hub" / "backend"))

import build_profiles_v2 as BP
import features_v2 as FE
import gen_v3 as V3
import gen_v4_behavior as V4
from app.services.feature_extraction import _device_signature


def canonicalize(rows: list[dict]) -> None:
    """Mutate synthetic rows before feature extraction; use service parser."""
    for row in rows:
        row["device_signature"] = _device_signature(row.get("user_agent"))


def build_seed(users_xlsx: Path, seed: int, spec: list[dict], roster: dict) -> dict:
    BP.SEED = seed
    rng = BP.random.Random(seed)
    ids = BP.load_identities(users_xlsx)
    users = {}
    for spec_item in spec:
        profile = dict(spec_item)
        profile["email"] = roster[profile["alias"]]
        ident = ids[profile["email"]]
        total = V3.TRAIN_POOL + V3.VAL_N + V3.TEST_N
        episodes = V3.gen_normal_episodes(profile, ident, rng, total)
        for episode in episodes:
            canonicalize(episode)
        feature_episodes, _ = V3.features_by_episode(episodes)
        normal = [row for episode in episodes for row in episode]
        feature_rows = [feat for episode in feature_episodes for feat in episode]
        vectors = [[float(row[name]) for name in FE.FEATURES] for row in feature_rows]
        train_end, val_end = V3.TRAIN_POOL, V3.TRAIN_POOL + V3.VAL_N
        last = len(episodes) - 1

        dev_rows = V3.gen_attack_pack(profile, ident, rng, V3.DEV, last)
        canonicalize(dev_rows)
        dev = V4._recompute(dev_rows, normal, last)
        final_rows = V3.gen_attack_pack(profile, ident, rng, V3.FINAL, last)
        canonicalize(final_rows)
        final = V4._recompute(final_rows, normal, last)
        camp_like_rows = V3._camp_like_in_window(profile, ident, rng, last)
        canonicalize(camp_like_rows)
        campaign_like = V4._recompute(camp_like_rows, normal, last)
        users[profile["alias"]] = {
            "train_raw": normal[:train_end],
            "train_ft": vectors[:train_end],
            "train_episodes": [len(episode) for episode in episodes],
            "val_ft": vectors[train_end:val_end],
            "test": list(zip(normal[val_end:], vectors[val_end:])),
            "dev_attacks": dev,
            "final_attacks": final,
            "camp_like": campaign_like,
            "episode_of": [i for i, episode in enumerate(episodes) for _ in episode],
        }
    return users
