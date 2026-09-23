"""เทียบ schema ของ PostgreSQL สองฐานทีละรายการจาก catalog — ไม่เทียบข้อความของ pg_dump.

ใช้ยืนยัน baseline migration: ฐานข้อมูลว่าง → `alembic upgrade head` ต้องได้ schema เดียวกับ
`tests/support/schema/hub_schema.sql` (ฐานที่โหลด snapshot)

เทียบ: extension, ตาราง, คอลัมน์ (ชนิด / NOT NULL / server default), index, constraint, trigger,
ฟังก์ชัน, sequence, enum, view · **ไม่เทียบลำดับคอลัมน์** — ฐานที่สร้างด้วย create_all แล้ว ALTER
ทีหลังกับฐานที่ migration สร้างใหม่มีลำดับทางกายภาพต่างกันได้โดยไม่มีผลต่อแอป

    python -m scripts.schema_catalog <database_url_a> <database_url_b>   # exit 1 ถ้าต่างกัน
"""

from __future__ import annotations

import json
import re
import sys

QUERIES = {
    "extensions": "SELECT extname FROM pg_extension WHERE extname <> 'plpgsql'",
    "tables": (
        "SELECT tablename FROM pg_tables "
        "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
    ),
    "columns": (
        "SELECT c.relname, a.attname, format_type(a.atttypid, a.atttypmod), "
        "a.attnotnull, pg_get_expr(d.adbin, d.adrelid) "
        "FROM pg_attribute a "
        "JOIN pg_class c ON c.oid = a.attrelid "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum "
        "WHERE n.nspname = 'public' AND c.relkind = 'r' AND a.attnum > 0 "
        "AND NOT a.attisdropped AND c.relname <> 'alembic_version'"
    ),
    "indexes": (
        "SELECT tablename, indexname, indexdef FROM pg_indexes "
        "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
    ),
    "constraints": (
        "SELECT cl.relname, co.conname, co.contype, pg_get_constraintdef(co.oid) "
        "FROM pg_constraint co JOIN pg_class cl ON cl.oid = co.conrelid "
        "JOIN pg_namespace n ON n.oid = co.connamespace "
        "WHERE n.nspname = 'public' AND cl.relname <> 'alembic_version'"
    ),
    "triggers": (
        "SELECT c.relname, t.tgname, pg_get_triggerdef(t.oid) "
        "FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
        "WHERE NOT t.tgisinternal"
    ),
    "functions": (
        "SELECT p.proname, pg_get_functiondef(p.oid) FROM pg_proc p "
        "JOIN pg_namespace n ON n.oid = p.pronamespace "
        "WHERE n.nspname = 'public' AND p.prokind IN ('f', 'p')"
    ),
    "sequences": (
        "SELECT sequencename, data_type::text, start_value, increment_by "
        "FROM pg_sequences WHERE schemaname = 'public'"
    ),
    "enums": (
        "SELECT t.typname, string_agg(e.enumlabel, ',' ORDER BY e.enumsortorder) "
        "FROM pg_type t JOIN pg_enum e ON e.enumtypid = t.oid "
        "JOIN pg_namespace n ON n.oid = t.typnamespace "
        "WHERE n.nspname = 'public' GROUP BY t.typname"
    ),
    "views": ("SELECT viewname, definition FROM pg_views WHERE schemaname = 'public'"),
}

_PUBLIC = re.compile(r"\bpublic\.")
_SPACE = re.compile(r"\s+")


def normalize(value):
    """ตัด `public.` และช่องว่างซ้ำ — pg_dump/catalog ใส่ schema ต่างกันตาม search_path."""
    if isinstance(value, str):
        return _SPACE.sub(" ", _PUBLIC.sub("", value)).strip()
    return value


def normalize_rows(rows) -> list[tuple]:
    return sorted(tuple(normalize(v) for v in row) for row in rows)


def diff_catalogs(a: dict, b: dict) -> dict:
    """คืนเฉพาะหมวดที่ต่าง: {หมวด: {"only_a": [...], "only_b": [...]}}."""
    out = {}
    for key in sorted(set(a) | set(b)):
        sa = {tuple(r) for r in a.get(key, [])}
        sb = {tuple(r) for r in b.get(key, [])}
        if sa != sb:
            out[key] = {
                "only_a": sorted(sa - sb, key=repr),
                "only_b": sorted(sb - sa, key=repr),
            }
    return out


def catalog(url: str) -> dict:
    from sqlalchemy import create_engine, text

    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            conn.execute(text("SET search_path TO public"))
            return {
                key: normalize_rows(conn.execute(text(sql)).all())
                for key, sql in QUERIES.items()
            }
    finally:
        engine.dispose()


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        print(
            "usage: python -m scripts.schema_catalog <url_a> <url_b>", file=sys.stderr
        )
        return 2
    a, b = catalog(argv[0]), catalog(argv[1])
    d = diff_catalogs(a, b)
    counts = {k: len(v) for k, v in a.items()}
    if not d:
        print(json.dumps({"equal": True, "counts": counts}, ensure_ascii=False))
        return 0
    print(
        json.dumps(
            {"equal": False, "diff": d}, ensure_ascii=False, indent=2, default=str
        )
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
