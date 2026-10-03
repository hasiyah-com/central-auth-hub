"""Controlled synthetic scenarios, NOT measured real attacks or deployment evidence."""
from datetime import datetime, timedelta
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import random
import uuid

from app.services.l3_auth_context import CONTRACT, FEATURE_NAMES, build_context
from app.services.feature_time import FEATURE_CONTRACT
from app.security.rule_engine import FEAT, evaluate_rules
from app.security.behavior_profiling import evaluate_behavior
from app.security.risk_aggregator import aggregate
from app.security.iforest_scorer import monitoring_only

BASE_NAMES = [name for name, _ in sorted(FEAT.items(), key=lambda p: p[1])]
FAMILIES = ["recovery_takeover", "method_departure", "new_authenticator",
            "language_change", "combined_context", "foreign", "new_device", "burst"]


def generate(source, output, seed=42, users=300):
    provenance = json.loads(source.with_suffix(source.suffix+".meta.json").read_text())
    if (provenance.get("feature_contract") != FEATURE_CONTRACT
        or provenance.get("timezone") != "Asia/Bangkok"
        or provenance.get("dataset_sha256") != hashlib.sha256(source.read_bytes()).hexdigest()):
        raise ValueError("base dataset checksum/Bangkok feature contract mismatch")
    with source.open() as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != BASE_NAMES + ["label"]:
            raise ValueError("expected existing 23-feature synthetic CSV")
        base_normals = [[float(row[n]) for n in BASE_NAMES] for row in reader if row["label"] == "0"]
    rng = random.Random(seed)
    rows = []
    now = datetime(2026, 10, 3, 9)
    for user in range(users):
        cold = rng.random() < .2
        passkey_rate = rng.choice([.1, .7, .9])
        old_guid = str(uuid.UUID(int=user+1))
        new_guid = str(uuid.UUID(int=10000+user))
        old_language = rng.choice(["th-th", "en-us", "en-gb"])
        other_language = "ja-jp" if old_language != "ja-jp" else "de-de"
        prior = (["passkey"]*round(passkey_rate*50) + ["google"]*(50-round(passkey_rate*50))) if not cold else []
        for event in range(48):
            family = "normal" if event < 40 else FAMILIES[event-40]
            attack = family != "normal"
            base = rng.choice(base_normals).copy()
            if cold:
                base[FEAT["hours_from_typical_login_time"]] = 0
                base[FEAT["weekday_usage_score"]] = 0
            method = "passkey" if rng.random() < passkey_rate else "google"
            recovery = now-timedelta(hours=rng.uniform(.1, 24) if rng.random() < .15 else rng.uniform(24, 8760)) if rng.random() < .4 else None
            reset = now-timedelta(hours=rng.uniform(.1, 24) if rng.random() < .15 else rng.uniform(24, 8760)) if rng.random() < .3 else None
            guid = new_guid if rng.random() < .05 else old_guid
            language = other_language if rng.random() < .08 else old_language
            if family in {"recovery_takeover", "combined_context"}:
                recovery = now-timedelta(hours=rng.uniform(.1, 3))
                reset = now-timedelta(hours=rng.uniform(.1, 3))
            if family in {"method_departure", "combined_context"}:
                method = "google"
            if family == "new_authenticator":
                method, guid = "passkey", new_guid
            if family == "language_change":
                language = other_language
            if family == "foreign":
                base[FEAT["is_thailand"]], base[FEAT["is_new_country"]] = 0, 1
            if family == "new_device":
                base[FEAT["is_new_device"]], base[FEAT["is_new_user_agent_family"]] = 1, 1
            if family == "burst":
                base[FEAT["login_count_24h"]], base[FEAT["log_minutes_since_last_login"]] = 60, 0
            context = build_context(now=now, method=method, recovery_at=recovery, reset_at=reset,
                prior_methods=prior, aaguid=guid if method == "passkey" else None,
                prior_aaguids=[old_guid]*20 if not cold else [], language=language,
                prior_languages=[old_language]*50 if not cold else [])
            # Actual feature-only current L1/L2 code, with explicit simulated profile.
            # No DB IP blacklist, cross-system propagation or failed-login provenance.
            profile = None if cold else {"session_count": 50, "total": 50,
                "typical_weekend": int(base[FEAT["day_of_week"]] >= 5),
                "hour_counts": {int(base[FEAT["hour_of_day"]]): 35},
                "scope_history": [base[FEAT["scope_sensitivity_score"]]]*50}
            rule = evaluate_rules(base, None, str(user), None, None)
            behavior = evaluate_behavior(base, profile)
            decision = aggregate(rule, behavior, monitoring_only())
            rows.append({"subject": f"sim-user-{user}", "session": f"sim-{user}-{event}",
                "captured_at": now.isoformat()+"Z", "user_type": ["admin", "staff", "teacher", "student"][user%4],
                "history_group": "cold_start" if cold else "established", "attack_family": family,
                "label": int(attack), "l1_l2_decision": decision.decision,
                "features": {**dict(zip(BASE_NAMES, base)), **context["features"]}})
    text = "".join(json.dumps(r, sort_keys=True)+"\n" for r in rows)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text)
    meta = {"contract": CONTRACT, "base_feature_contract": FEATURE_CONTRACT,
        "feature_names": BASE_NAMES+FEATURE_NAMES, "dataset_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "source": "controlled_synthetic_only", "base_data_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "seed": seed, "users": users, "normal": users*40, "attack": users*8,
        "benign_change_rates": {"new_aaguid_when_passkey": .05, "new_language": .08,
                               "recent_recovery_when_observed": .15, "recent_reset_when_observed": .15},
        "limitations": ["attack labels defined by scenario injection, not real evidence",
            "new-context attacks intentionally share legacy normal feature distributions",
            "some weak scenarios overlap benign behavior; scenario names do not imply observable attack proof",
            "L1/L2 is actual feature-only code on a simulated profile, not the full DB production path",
            "prevalence is synthetic; PR-AUC must not be interpreted as production precision"]}
    output.with_suffix(output.suffix+".meta.json").write_text(json.dumps(meta, indent=2))
    return meta


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    print(json.dumps(generate(args.base_data, args.output, args.seed), indent=2))
