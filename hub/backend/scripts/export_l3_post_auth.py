"""Export completed account windows for separate review/labeling, never login labels.

python -m scripts.export_l3_post_auth --output /tmp/post-auth.jsonl --days 7
Add independently reviewed label 0/1 per window before offline training.
"""
import argparse
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path

from app.services.l3_post_auth import CONTRACT, FEATURE_NAMES, WINDOW_SECONDS, summarize


def export(path, days=7):
    from app.database import SessionLocal
    from app.models import RequestLog
    from app.services.l3_post_auth import NOISE
    from sqlalchemy import or_
    now = datetime.utcnow()
    end = now.replace(minute=now.minute//5*5, second=0, microsecond=0)
    start = end-timedelta(days=days)
    groups = {}
    with SessionLocal() as db:
        query = db.query(RequestLog).filter(RequestLog.user_id.isnot(None),
            RequestLog.created_at >= start, RequestLog.created_at < end,
            *[~or_(RequestLog.path == prefix, RequestLog.path.like(prefix+"/%")) for prefix in NOISE])
        for row in query.order_by(RequestLog.created_at).yield_per(1000):
            at = row.created_at.replace(minute=row.created_at.minute//5*5, second=0, microsecond=0)
            key = (str(row.user_id), at)
            bucket = groups.setdefault(key, [])
            if len(bucket) <= 10000:
                bucket.append(row)
    payload = []
    for (user, at), rows in groups.items():
        window = summarize(rows, at, at+timedelta(seconds=WINDOW_SECONDS))
        if window["truncated"] or not window["request_count"]:
            continue
        payload.append({"subject": hashlib.sha256(user.encode()).hexdigest(),
            "window": hashlib.sha256((user+at.isoformat()).encode()).hexdigest(),
            "from": window["from"], "to": window["to"], "features": window["features"],
            "label": None})
    text = "".join(json.dumps(r, sort_keys=True)+"\n" for r in payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    meta = {"contract": CONTRACT, "feature_names": FEATURE_NAMES, "rows": len(payload),
            "dataset_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "source": "verified_user_hub_requests; not subsystem or session attribution",
            "labeling": "independent window labels required; recompute checksum after review"}
    path.with_suffix(path.suffix+".meta.json").write_text(json.dumps(meta, indent=2))
    return meta


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--days", type=int, default=7, choices=range(1, 31))
    args = parser.parse_args()
    print(json.dumps(export(args.output, args.days), indent=2))
