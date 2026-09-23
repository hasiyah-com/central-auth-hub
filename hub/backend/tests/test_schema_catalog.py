"""ตัวเทียบ schema ทีละรายการ (scripts/schema_catalog.py) — ส่วนที่ไม่ต้องใช้ฐานข้อมูล.

ใช้เป็นเกณฑ์ยืนยัน baseline migration: DB ว่าง → upgrade head ต้องตรงกับ hub_schema.sql
การเทียบกับฐานจริงอยู่ใน scripts/test/verify_migrations.sh
"""

from __future__ import annotations

from scripts import schema_catalog as SC


def test_every_category_the_acceptance_needs_is_queried():
    need = {
        "extensions",
        "tables",
        "columns",
        "indexes",
        "constraints",
        "triggers",
        "functions",
        "sequences",
        "enums",
        "views",
    }
    assert need <= set(SC.QUERIES)


def test_normalize_drops_schema_prefix_and_extra_spaces():
    assert (
        SC.normalize("CREATE INDEX ix ON public.users  USING btree (email)")
        == "CREATE INDEX ix ON users USING btree (email)"
    )
    assert SC.normalize(5) == 5
    assert SC.normalize(None) is None


def test_row_order_does_not_matter():
    a = SC.normalize_rows([("users", "b", "text"), ("users", "a", "text")])
    b = SC.normalize_rows([("users", "a", "text"), ("users", "b", "text")])
    assert a == b


def test_identical_catalogs_have_no_diff():
    c = {"tables": [("users",)], "columns": [("users", "id", "uuid", True, None)]}
    assert SC.diff_catalogs(c, c) == {}


def test_a_missing_default_is_reported_on_the_right_side():
    a = {"columns": [("users", "status", "text", True, "'active'::text")]}
    b = {"columns": [("users", "status", "text", True, None)]}
    d = SC.diff_catalogs(a, b)
    assert d["columns"]["only_a"] == [
        ("users", "status", "text", True, "'active'::text")
    ]
    assert d["columns"]["only_b"] == [("users", "status", "text", True, None)]


def test_a_category_present_on_one_side_only_is_a_diff():
    d = SC.diff_catalogs({"triggers": [("t", "trg", "CREATE TRIGGER ...")]}, {})
    assert d["triggers"]["only_a"] and d["triggers"]["only_b"] == []
