"""สถิติของ Expert Label Workflow — เชิงพรรณนาเท่านั้นในรุ่นนี้.

**production FPR ไม่ถูกคำนวณ** — แม้ readiness gate จะผ่านครบ การเริ่มคำนวณต้องเป็น
รอบวิเคราะห์ที่ประกาศล่วงหน้าแยกต่างหาก · ก่อนถึงเกณฑ์ขั้นต่ำ ห้ามอ้าง production FPR

เกณฑ์ขั้นต่ำที่ล็อกไว้ก่อนเริ่มเก็บ (ไม่ปรับตามผลที่ได้)
  ผู้ใช้ที่มี login จากภายนอก     >= 20 คน
  ผู้ใช้คนเดียวครอง login ภายนอก  <= 40%
  alert group ที่มี label ใช้ได้   >= 100 กลุ่ม
  double-review                   >= 30 กลุ่ม
  ผู้ตรวจ                          >= 2 คน
"""

from __future__ import annotations

import random
from collections import Counter, defaultdict

from sqlalchemy.orm import Session

from .provenance import classify
from .vocab import NORMAL_CLASS, SUSPICIOUS_CLASS

MIN_EXTERNAL_USERS = 20
MAX_USER_SHARE = 0.40
MIN_LABELED_GROUPS = 100
MIN_DOUBLE_REVIEWED = 30
MIN_REVIEWERS = 2


def _verdict_class(v: str) -> str:
    if v in NORMAL_CLASS:
        return "normal"
    if v in SUSPICIOUS_CLASS:
        return "suspicious"
    return "insufficient"


def consolidate(verdicts) -> dict:
    """รวม verdict ของผู้ตรวจตามลำดับที่ส่ง (design §5.2).

    * ใครตอบ insufficient_context -> ออกจากชุด FPR แต่ยังนับใน alert yield
    * ต่างกันในกลุ่มเดียวกัน -> ใช้คำตอบที่อ้างน้อยกว่า (`suspicious` แทน
      `confirmed_attack`) เพราะยังไม่มีฉันทามติว่าเป็นการโจมตีจริง
    * ต่างข้ามกลุ่ม -> ต้องมีผู้ตรวจคนที่สาม · คำตอบของคนที่สามเป็นข้อยุติ
    """
    vs = list(verdicts)
    if not vs:
        return {"label": None, "status": "unlabeled", "fpr_eligible": False}
    if "insufficient_context" in vs:
        return {
            "label": "insufficient_context",
            "status": "excluded_insufficient",
            "fpr_eligible": False,
        }
    if len(vs) == 1:
        return {"label": vs[0], "status": "single", "fpr_eligible": True}

    a, b = vs[0], vs[1]
    if a == b:
        return {"label": a, "status": "agreed", "fpr_eligible": True}
    if _verdict_class(a) == _verdict_class(b):
        return {"label": "suspicious", "status": "conservative", "fpr_eligible": True}
    if len(vs) >= 3:
        return {"label": vs[2], "status": "adjudicated", "fpr_eligible": True}
    return {"label": None, "status": "needs_adjudication", "fpr_eligible": False}


def cohen_kappa(pairs) -> float | None:
    pairs = list(pairs)
    n = len(pairs)
    if n == 0:
        return None
    po = sum(1 for a, b in pairs if a == b) / n
    ca = Counter(a for a, _ in pairs)
    cb = Counter(b for _, b in pairs)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    if pe >= 1.0:
        return None
    return (po - pe) / (1.0 - pe)


def kappa_with_ci(pairs, *, n_boot: int = 2000, seed: int = 0, alpha: float = 0.05):
    pairs = list(pairs)
    k = cohen_kappa(pairs)
    out = {"n": len(pairs), "kappa": k, "ci_low": None, "ci_high": None}
    if k is None:
        return out
    rng = random.Random(seed)
    boots = []
    for _ in range(n_boot):
        kb = cohen_kappa(rng.choices(pairs, k=len(pairs)))
        if kb is not None:
            boots.append(kb)
    if boots:
        boots.sort()
        lo = boots[int((alpha / 2) * (len(boots) - 1))]
        hi = boots[int((1 - alpha / 2) * (len(boots) - 1))]
        out["ci_low"], out["ci_high"] = min(lo, k), max(hi, k)
    return out


def readiness(
    *,
    n_external_users: int,
    max_user_share: float | None,
    n_labeled_groups: int,
    n_double_reviewed: int,
    n_reviewers: int,
) -> dict:
    unmet = []
    if n_external_users < MIN_EXTERNAL_USERS:
        unmet.append("external_users")
    if max_user_share is None or max_user_share > MAX_USER_SHARE:
        unmet.append("user_concentration")
    if n_labeled_groups < MIN_LABELED_GROUPS:
        unmet.append("labeled_groups")
    if n_double_reviewed < MIN_DOUBLE_REVIEWED:
        unmet.append("double_reviewed")
    if n_reviewers < MIN_REVIEWERS:
        unmet.append("reviewers")
    return {"ready": not unmet, "unmet": unmet}


def summarize(db: Session) -> dict:
    from app.models import ExpertAlertGroup, ExpertReview, LoginSession

    from .reviews import round1_by_reviewer

    groups = db.query(ExpertAlertGroup).all()
    excluded: Counter = Counter()
    eligible = []
    for g in groups:
        if g.eligible_for_production_metrics:
            eligible.append(g)
        elif g.provenance == "external":
            excluded["external_without_config"] += 1
        else:
            excluded[g.provenance] += 1

    by_group = defaultdict(list)
    ids = [g.id for g in eligible]
    if ids:
        for r in db.query(ExpertReview).filter(ExpertReview.group_id.in_(ids)).all():
            by_group[r.group_id].append(r)

    statuses: Counter = Counter()
    labels: Counter = Counter()
    pairs = []
    reviewers = set()
    n_labeled = 0
    for g in eligible:
        ordered = round1_by_reviewer(by_group[g.id])
        reviewers |= {r.reviewer_id for r in ordered}
        c = consolidate([r.verdict for r in ordered])
        statuses[c["status"]] += 1
        if c["label"]:
            labels[c["label"]] += 1
        if c["fpr_eligible"]:
            n_labeled += 1
        if len(ordered) >= 2:
            pairs.append((ordered[0].verdict, ordered[1].verdict))

    per_user: Counter = Counter()
    for uid, ip, ua in db.query(
        LoginSession.user_id, LoginSession.ip, LoginSession.user_agent
    ):
        if uid and classify(str(ip) if ip else None, ua) == "external":
            per_user[uid] += 1
    external_logins = sum(per_user.values())
    max_share = max(per_user.values()) / external_logins if external_logins else None

    gate = readiness(
        n_external_users=len(per_user),
        max_user_share=max_share,
        n_labeled_groups=n_labeled,
        n_double_reviewed=len(pairs),
        n_reviewers=len(reviewers),
    )
    agreement = kappa_with_ci(pairs)
    agreement["status"] = (
        "ok" if len(pairs) >= MIN_DOUBLE_REVIEWED else "insufficient_sample"
    )

    return {
        "groups_total": len(groups),
        "groups_eligible": len(eligible),
        "excluded_by_provenance": dict(sorted(excluded.items())),
        "external_logins": external_logins,
        "external_users": len(per_user),
        "max_user_share": round(max_share, 4) if max_share is not None else None,
        "alert_yield_per_1000_external_logins": (
            round(len(eligible) / external_logins * 1000, 3)
            if external_logins
            else None
        ),
        "consolidation_status": dict(sorted(statuses.items())),
        "consolidated_labels": dict(sorted(labels.items())),
        "double_reviewed_groups": len(pairs),
        "reviewers": len(reviewers),
        "agreement": agreement,
        "readiness": gate,
        "production_fpr": None,
        "production_fpr_status": "not_computed",
        "legacy_feedback_included": False,
        "note": (
            "รายงานเชิงพรรณนาเท่านั้น — production FPR ไม่ถูกคำนวณในรุ่นนี้ "
            "และห้ามอ้างจนกว่าจะผ่านเกณฑ์ขั้นต่ำและมีรอบวิเคราะห์ที่ประกาศล่วงหน้า"
        ),
    }
