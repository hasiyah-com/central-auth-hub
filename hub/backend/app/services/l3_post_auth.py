"""L3 post-auth observations from verified-user Hub request logs, not login inputs."""
from __future__ import annotations
from datetime import datetime, timedelta
import math
import re

from app.services.feature_time import as_utc_naive

CONTRACT = "l3-post-auth-v1"
WINDOW_SECONDS = 300
MAX_ROWS = 10000
FEATURE_NAMES = ["post_requests_observed", "post_request_count_log1p",
                 "post_route_diversity_log1p", "post_write_fraction",
                 "post_error_fraction", "post_interval_log1p_mean"]
NOISE = ("/auth/heartbeat", "/auth/refresh", "/admin/ml", "/docs", "/redoc",
         "/health", "/_next", "/auth/activity")


def business_path(path):
    return bool(path) and not any(path == p or path.startswith(p + "/") for p in NOISE)


def summarize(rows, start, end):
    start, end = as_utc_naive(start), as_utc_naive(end)
    selected = [r for r in rows if start <= as_utc_naive(r.created_at) < end
                and r.user_id is not None and business_path(r.path)]
    selected.sort(key=lambda r: as_utc_naive(r.created_at))
    truncated = len(selected) > MAX_ROWS
    selected = selected[:MAX_ROWS]
    families = set()
    for row in selected:
        parts = row.path.split("/")[1:3]
        parts = [":id" if re.fullmatch(r"[0-9]+|[0-9a-fA-F-]{32,36}", part) else part
                 for part in parts]
        families.add("/" + "/".join(parts))
    count = len(selected)
    gaps = [(as_utc_naive(b.created_at)-as_utc_naive(a.created_at)).total_seconds()
            for a, b in zip(selected, selected[1:])]
    values = [float(bool(count)), math.log1p(count), math.log1p(len(families)),
              sum((r.method or "").upper() in {"POST", "PUT", "PATCH", "DELETE"} for r in selected)/count if count else 0,
              sum((r.status_code or 0) >= 400 for r in selected)/count if count else 0,
              sum(math.log1p(gap) for gap in gaps)/len(gaps) if gaps else 0]
    return {"contract": CONTRACT, "status": "collection_only", "scope": "verified_user_hub_requests",
            "from": start.isoformat()+"Z", "to": end.isoformat()+"Z",
            "request_count": count, "truncated": truncated,
            "features": dict(zip(FEATURE_NAMES, values))}


def latest_completed_window(db, user_id, now=None):
    from app.models import RequestLog
    from sqlalchemy import or_
    now = as_utc_naive(now or datetime.utcnow())
    end = now.replace(minute=now.minute//5*5, second=0, microsecond=0)
    start = end-timedelta(seconds=WINDOW_SECONDS)
    rows = db.query(RequestLog).filter(RequestLog.user_id == user_id,
        RequestLog.created_at >= start, RequestLog.created_at < end,
        *[~or_(RequestLog.path == prefix, RequestLog.path.like(prefix + "/%")) for prefix in NOISE],
    ).order_by(RequestLog.created_at).limit(MAX_ROWS+1).all()
    return summarize(rows, start, end)
