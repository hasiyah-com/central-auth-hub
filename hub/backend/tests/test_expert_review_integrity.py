"""Expert Label Workflow — ข้อตรวจความถูกต้องระดับฐานข้อมูลก่อน commit.

  * downgrade ลบ trigger ก่อนตาราง · trigger มีชื่อเดียวต่อตาราง
  * supersedes_id ชี้ข้าม alert group / ผู้ตรวจ / รอบ ไม่ได้ — บังคับที่ฐานข้อมูล
  * ผู้ตรวจคนเดิมมี label ต้นทางได้แถวเดียวต่อกลุ่มต่อรอบ แม้ INSERT ตรง
  * timestamp เป็น UTC ทั้งจาก ORM และ server default แม้ session ตั้ง timezone อื่น
  * ลบผู้ใช้หรือ login session ไม่ทำลายหลักฐานแบบ cascade
  * โค้ดของ workflow ไม่มีเส้นทาง UPDATE ตารางหลักฐาน

รัน:
  docker compose exec hub-backend pytest tests/test_expert_review_integrity.py -v
"""

from __future__ import annotations

import ast
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.models import ExpertAlertGroup, ExpertReview, SystemDisposition
from app.services.expert_review import reviews as R
from tests.test_expert_review_db import (  # noqa: F401 — ใช้ fixture `world` ร่วมกัน
    _group,
    _post_review,
    _review_body,
    world,
)

BACKEND = Path(__file__).resolve().parent.parent
MIGRATION = BACKEND / "alembic" / "versions" / "e5f6a7b8c9d0_expert_label_workflow.py"
EVIDENCE_TABLES = ("expert_alert_groups", "system_dispositions", "expert_reviews")


@pytest.fixture
def ctx(world):  # noqa: F811 — fixture `world` มาจาก test_expert_review_db
    return world


def _extra_group(ctx) -> ExpertAlertGroup:
    """กลุ่มที่สองของผู้ใช้เดียวกัน — ใช้ทดสอบการอ้างข้ามกลุ่ม."""
    db = ctx["db"]
    at = ctx["now"] - timedelta(hours=5)
    g = ExpertAlertGroup(
        group_key=f"test-extra-{uuid.uuid4()}",
        user_id=ctx["subject"].id,
        primary_signal="behavior:hours_diff",
        window_start=at.replace(minute=0, second=0, microsecond=0),
        session_ids=[],
        n_events=0,
        first_seen_at=at,
        last_seen_at=at,
        provenance="test",
        eligible_for_production_metrics=False,
        double_review=False,
    )
    db.add(g)
    db.commit()
    return g


def _insert_review(db, *, group_id, reviewer_id, round_=1, supersedes_id=None):
    """INSERT ตรงโดยไม่ผ่าน service — พิสูจน์ว่าฐานข้อมูลบังคับเอง."""
    new_id = uuid.uuid4()
    db.execute(
        text(
            "INSERT INTO expert_reviews (id, group_id, reviewer_id, round, "
            "model_output_visible, verdict, confidence, reason_codes, supersedes_id) "
            "VALUES (CAST(:id AS uuid), CAST(:g AS uuid), CAST(:r AS uuid), :rnd, "
            ":vis, 'benign', 'low', CAST(:codes AS json), CAST(:sup AS uuid))"
        ),
        {
            "id": str(new_id),
            "g": str(group_id),
            "r": str(reviewer_id),
            "rnd": round_,
            "vis": round_ == 2,
            "codes": '["no_user_history"]',
            "sup": str(supersedes_id) if supersedes_id else None,
        },
    )
    db.flush()
    return new_id


# ─────────────────────────────────────────────────────────────
# Migration และ trigger
# ─────────────────────────────────────────────────────────────


def test_downgrade_drops_triggers_before_tables():
    src = MIGRATION.read_text(encoding="utf-8")
    down = src[src.index("def downgrade") :]
    first_drop_table = min(down.index(f'drop_table("{t}")') for t in EVIDENCE_TABLES)
    assert down.index("DROP TRIGGER") < first_drop_table
    assert down.index("DROP FUNCTION") < first_drop_table


def test_exactly_one_trigger_per_evidence_table(db):
    rows = db.execute(
        text(
            "SELECT c.relname, t.tgname FROM pg_trigger t "
            "JOIN pg_class c ON c.oid = t.tgrelid "
            "WHERE NOT t.tgisinternal AND c.relname IN "
            "('expert_alert_groups', 'system_dispositions', 'expert_reviews') "
            "ORDER BY c.relname, t.tgname"
        )
    ).all()
    assert [tuple(r) for r in rows] == [
        ("expert_reviews", "expert_reviews_no_update"),
        ("system_dispositions", "system_dispositions_no_update"),
    ]
    n_fn = db.execute(
        text(
            "SELECT count(*) FROM pg_proc WHERE proname = 'expert_review_forbid_update'"
        )
    ).scalar()
    assert n_fn == 1


def test_foreign_keys_never_cascade(db):
    """ลบแถวต้นทางต้องถูกปฏิเสธ — ไม่ cascade ไม่ set null ไม่ set default.

    ยอมรับทั้ง RESTRICT (`r`) และ NO ACTION (`a`) · FK ที่อ้างตาราง expert_reviews เอง
    ต้องเป็น NO ACTION เพราะ RESTRICT ตรวจทีละแถวทันที ทำให้ลบทั้งสายการแก้ใน
    statement เดียวไม่ได้
    """
    rows = db.execute(
        text(
            "SELECT conrelid::regclass::text, conname, confdeltype FROM pg_constraint "
            "WHERE contype = 'f' AND conrelid::regclass::text IN "
            "('expert_alert_groups', 'system_dispositions', 'expert_reviews')"
        )
    ).all()
    assert len(rows) >= 5
    assert {r[2] for r in rows} <= {"a", "r"}, rows


# ─────────────────────────────────────────────────────────────
# supersedes_id — ห้ามข้ามกลุ่ม / ผู้ตรวจ / รอบ
# ─────────────────────────────────────────────────────────────


def test_service_rejects_supersede_across_group(ctx, client):
    g1, g2 = _group(ctx), _extra_group(ctx)
    a = ctx["reviewers"][0]
    first = _post_review(client, g1, a).json()
    r = _post_review(client, g2, a, supersedes_id=first["id"])
    assert r.status_code == 404


def test_db_rejects_supersede_across_group(ctx):
    db = ctx["db"]
    g1, g2 = _group(ctx), _extra_group(ctx)
    a = ctx["reviewers"][0]
    rv = R.submit_review(db, group_id=g1.id, reviewer=a, body=_review_body(), ip=None)
    with pytest.raises(IntegrityError):
        _insert_review(db, group_id=g2.id, reviewer_id=a.id, supersedes_id=rv.id)
    db.rollback()


def test_db_rejects_supersede_across_reviewer(ctx):
    db = ctx["db"]
    g = _group(ctx)
    a, b = ctx["reviewers"][:2]
    rv = R.submit_review(db, group_id=g.id, reviewer=a, body=_review_body(), ip=None)
    with pytest.raises(IntegrityError):
        _insert_review(db, group_id=g.id, reviewer_id=b.id, supersedes_id=rv.id)
    db.rollback()


def test_db_rejects_supersede_across_round(ctx):
    db = ctx["db"]
    g = _group(ctx)
    a = ctx["reviewers"][0]
    rv = R.submit_review(db, group_id=g.id, reviewer=a, body=_review_body(), ip=None)
    with pytest.raises(IntegrityError):
        _insert_review(
            db, group_id=g.id, reviewer_id=a.id, round_=2, supersedes_id=rv.id
        )
    db.rollback()


def test_db_rejects_second_root_round1(ctx):
    """กันการสร้าง label รอบ 1 ซ้ำโดยเลี่ยง service (หรือ request ชนกัน)."""
    db = ctx["db"]
    g = _group(ctx)
    a = ctx["reviewers"][0]
    R.submit_review(db, group_id=g.id, reviewer=a, body=_review_body(), ip=None)
    with pytest.raises(IntegrityError):
        _insert_review(db, group_id=g.id, reviewer_id=a.id, round_=1)
    db.rollback()


def test_db_allows_linear_supersede_chain(ctx):
    db = ctx["db"]
    g = _group(ctx)
    a = ctx["reviewers"][0]
    rv = R.submit_review(db, group_id=g.id, reviewer=a, body=_review_body(), ip=None)
    second = _insert_review(db, group_id=g.id, reviewer_id=a.id, supersedes_id=rv.id)
    _insert_review(db, group_id=g.id, reviewer_id=a.id, supersedes_id=second)
    db.commit()
    rows = db.query(ExpertReview).filter(ExpertReview.group_id == g.id).all()
    assert len(R.effective(rows)) == 1


# ─────────────────────────────────────────────────────────────
# UTC
# ─────────────────────────────────────────────────────────────


def _close_to_utc_now(ts: datetime) -> bool:
    return abs(ts - datetime.utcnow()) < timedelta(minutes=2)


def test_review_created_at_is_utc(ctx):
    db = ctx["db"]
    g = _group(ctx)
    rv = R.submit_review(
        db, group_id=g.id, reviewer=ctx["reviewers"][0], body=_review_body(), ip=None
    )
    assert _close_to_utc_now(rv.created_at)
    assert _close_to_utc_now(g.created_at)


def test_server_default_is_utc_even_when_session_timezone_differs(ctx):
    """INSERT ตรงที่ไม่ส่ง created_at ต้องได้ UTC ไม่ขึ้นกับ timezone ของ session."""
    db = ctx["db"]
    g = _group(ctx)
    a = ctx["reviewers"][0]
    db.execute(text("SET LOCAL TIME ZONE 'Asia/Bangkok'"))
    rid = _insert_review(db, group_id=g.id, reviewer_id=a.id)
    created = db.execute(
        text("SELECT created_at FROM expert_reviews WHERE id = CAST(:i AS uuid)"),
        {"i": str(rid)},
    ).scalar()
    db.rollback()
    assert _close_to_utc_now(created), created


# ─────────────────────────────────────────────────────────────
# การลบไม่ทำลายหลักฐาน
# ─────────────────────────────────────────────────────────────


def test_deleting_reviewer_does_not_cascade_reviews(ctx):
    db = ctx["db"]
    g = _group(ctx)
    a = ctx["reviewers"][0]
    rv = R.submit_review(db, group_id=g.id, reviewer=a, body=_review_body(), ip=None)
    with pytest.raises(IntegrityError):
        db.execute(
            text("DELETE FROM users WHERE id = CAST(:u AS uuid)"), {"u": str(a.id)}
        )
        db.flush()
    db.rollback()
    assert db.query(ExpertReview).filter(ExpertReview.id == rv.id).count() == 1


def test_deleting_subject_user_does_not_cascade_groups(ctx):
    db = ctx["db"]
    g = _group(ctx)
    uid = str(ctx["subject"].id)
    # ลบ login ของผู้ใช้ก่อนใน transaction เดียวกัน เพื่อให้เหลือเฉพาะ FK ของกลุ่มที่ขวางอยู่
    db.execute(
        text("DELETE FROM login_sessions WHERE user_id = CAST(:u AS uuid)"), {"u": uid}
    )
    with pytest.raises(IntegrityError):
        db.execute(text("DELETE FROM users WHERE id = CAST(:u AS uuid)"), {"u": uid})
        db.flush()
    db.rollback()
    assert db.query(ExpertAlertGroup).filter(ExpertAlertGroup.id == g.id).count() == 1


def test_deleting_login_session_keeps_group_evidence(ctx):
    db = ctx["db"]
    g = _group(ctx)
    gone = g.session_ids[0]
    db.execute(
        text("DELETE FROM login_sessions WHERE id = CAST(:s AS uuid)"), {"s": gone}
    )
    db.commit()
    db.expire_all()
    g2 = db.query(ExpertAlertGroup).filter(ExpertAlertGroup.id == g.id).one()
    assert g2.n_events == 3 and gone in g2.session_ids
    d = db.query(SystemDisposition).filter(SystemDisposition.group_id == g.id).one()
    assert gone in {row["session_id"] for row in d.model_output}


# ─────────────────────────────────────────────────────────────
# โค้ดของ workflow ไม่มีเส้นทาง UPDATE
# ─────────────────────────────────────────────────────────────


def _update_paths(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "update"
        ):
            found.append(f"{path.name}:{node.lineno} .update(...)")
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "text":
            for arg in node.args:
                if isinstance(arg, ast.Constant) and "UPDATE" in str(arg.value).upper():
                    found.append(f"{path.name}:{node.lineno} text(UPDATE ...)")
        if isinstance(node, (ast.Assign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if isinstance(t, ast.Attribute) and not (
                    isinstance(t.value, ast.Name) and t.value.id == "self"
                ):
                    found.append(f"{path.name}:{node.lineno} assign .{t.attr}")
    return found


def test_workflow_code_has_no_update_path():
    files = [
        BACKEND / "app" / "routers" / "expert_review.py",
        *(BACKEND / "app" / "services" / "expert_review").glob("*.py"),
    ]
    hits = [h for f in files for h in _update_paths(f)]
    assert hits == []
