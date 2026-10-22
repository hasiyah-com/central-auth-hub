"""C3 + PG-E diagnostic only: never returns or changes an access decision."""
import math
import time
from datetime import datetime
from types import MappingProxyType

from app.security.iforest_scorer import monitoring_only
from app.security.risk_aggregator import aggregate
from app.security.rule_engine import FEAT, evaluate_rules
from app.services.c3_pge_evidence import collect

VERSION = "c3-pge-shadow-v1"
RANK = {"allow": 0, "warn": 1, "challenge": 2, "block": 3}
ACTIONS = tuple(RANK)


def unavailable(status):
    return {"version": VERSION, "mode": "shadow", "status": status, "applied_to_access": False}


def build(*, db, user_id, subsystem_id, features, ip, geo_country, context,
          baseline_rule, behavior, baseline, observations, contextual_trial=False):
    if contextual_trial:
        return unavailable("incompatible_contextual_trial")
    if baseline_rule.blocked:
        return {**unavailable("hard_block_preserved"), "would_decision": "would_block"}
    if len(features) != 23 or not all(math.isfinite(float(v)) for v in features):
        return unavailable("invalid_feature_contract")
    started = time.perf_counter()
    now = datetime.utcnow()
    pk = features[FEAT["new_passkey_recently_added"]] >= 1
    grant = (features[FEAT["ever_changed_permission"]] >= 1
             and features[FEAT["permission_change_age"]] <= 1)
    facts = collect(db, user_id, subsystem_id, now, recent_passkey=pk, recent_permission=grant)
    count = facts["trusted_history_count_capped_at5"]
    if type(count) is not int or not 0 <= count <= 5:
        return unavailable("invalid_history_count")
    # Reuse exactly the baseline event's DB observations (including auth failure counts).
    # A missing read is an error, never an additional query against a newer snapshot.
    common = dict(subsystem_id=subsystem_id, context=context,
                  shadow_c3_history_count=count, _observations=MappingProxyType(observations))
    c2 = evaluate_rules(features, db, user_id, ip, geo_country, shadow_deduplicate=False, **common)
    c3 = evaluate_rules(features, db, user_id, ip, geo_country, **common)
    c2_decision = aggregate(c2, behavior, monitoring_only()).decision
    c3_decision = aggregate(c3, behavior, monitoring_only()).decision
    threshold = facts.get("count24h_warn_threshold")
    count_warn = threshold is not None and features[FEAT["login_count_24h"]] >= threshold
    # The research pipeline also warns on recent enrollment/count deviations.
    # Add these only to the counterfactual, never the baseline access result.
    rank = max(RANK[c3_decision], int(RANK[c2_decision] >= 1 or pk or count_warn))
    pge_reasons = []
    if pk and not facts["registration_verified"]:
        rank = max(rank, 2)
        pge_reasons.append("recent_registration_evidence_unknown")
    if grant and not facts["grant_provenance_recorded"]:
        rank = max(rank, 2)
        pge_reasons.append("recent_permission_provenance_unknown")
    return {
        "version": VERSION, "mode": "shadow", "status": "evaluated",
        "applied_to_access": False, "l3_included": False,
        "baseline_l1_l2_decision": baseline.decision.removeprefix("would_"),
        "candidate_decision": ACTIONS[rank], "would_decision": "would_" + ACTIONS[rank],
        "candidate_score_before_pge": aggregate(c3, behavior, monitoring_only()).total_score,
        "candidate_rule_reasons": list(c3.reasons), "pge_reasons": pge_reasons,
        "evidence": facts, "observed_at": now.isoformat() + "Z",
        "latency_ms": round((time.perf_counter() - started) * 1000, 3),
        "research_equivalence": "runtime_provenance_partial_legacy_links_unknown",
    }
