"""Export labeled captured L3 candidates; never reconstruct missing historical inputs.

python -m scripts.export_l3_auth_candidates --output /tmp/l3-auth.jsonl
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

from app.services.l3_auth_context import CONTRACT, FEATURE_NAMES
from app.services.feature_time import FEATURE_CONTRACT
from app.security.rule_engine import FEAT

LABELS = {"true_positive": 1, "normal_confirmed": 0, "false_positive": 0}
BASE_NAMES = [name for name, _ in sorted(FEAT.items(), key=lambda x: x[1])]


def candidate_row(session, label):
    candidate = (session.risk_breakdown or {}).get("l3_auth_candidate") or {}
    if (candidate.get("status") != "collection_only" or
        candidate.get("contract") != CONTRACT or
        candidate.get("base_feature_contract") != FEATURE_CONTRACT or
        not session.jti or session.decision == "block" or session.user_id is None):
        return None
    base, context = candidate.get("base_features", {}), candidate.get("features", {})
    if set(base) != set(BASE_NAMES) or set(context) != set(FEATURE_NAMES):
        return None
    if not context["auth_method_known"]:
        return None
    return {"subject": hashlib.sha256(str(session.user_id).encode()).hexdigest(),
            "session": hashlib.sha256(str(session.id).encode()).hexdigest(),
            "captured_at": candidate["captured_at"],
            "user_type": candidate.get("user_type"),
            "features": {**base, **context}, "label": label}


def export(output):
    from app.database import SessionLocal
    from app.models import LoginSession, MLFeedback
    rows, skipped = [], 0
    with SessionLocal() as db:
        pairs = db.query(LoginSession, MLFeedback).join(
            MLFeedback, MLFeedback.session_id == LoginSession.id
        ).filter(MLFeedback.label.in_(list(LABELS))).all()
        for session, feedback in pairs:
            row = candidate_row(session, LABELS[feedback.label])
            if row is None:
                skipped += 1
            else:
                rows.append(row)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
    output.write_text(payload, encoding="utf-8")
    meta = {"contract": CONTRACT, "base_feature_contract": FEATURE_CONTRACT,
            "feature_names": BASE_NAMES + FEATURE_NAMES,
            "dataset_sha256": hashlib.sha256(payload.encode()).hexdigest(),
            "rows": len(rows), "skipped": skipped, "source": "captured_labeled_real_sessions",
            "activation": "offline_only; no production model replacement"}
    output.with_suffix(output.suffix + ".meta.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8")
    return meta


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    print(json.dumps(export(parser.parse_args().output), indent=2))
