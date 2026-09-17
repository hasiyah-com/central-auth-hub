"""Guard แบบ fail-closed — ชุดเทสต้องไม่รันบนฐานข้อมูลหรือ Redis ของ dev.

ที่มา: ชุดเทสเคยรันบน `hub_db` โดยตรง fixture ของ `test_user_lifecycle` คืนสถานะ
ไม่สำเร็จ ทำให้นักศึกษา 56 คนค้างสถานะ graduated/resigned ถาวร เทสที่ต้องใช้
นักศึกษาเลยถูก skip ทั้งหมด และผล "0 failed" กลายเป็นไม่มีความหมาย

กติกา
  * ฐานข้อมูลต้องชื่อ `hub_test` หรือลงท้าย `_test`
  * Redis DB ต้องไม่ใช่ของ dev (ตั้ง `DEV_REDIS_DB` ได้ ค่าเริ่มต้น 0)
  * ต้องตั้ง `TEST_ENVIRONMENT=1`
  * URL ที่อ่านไม่ได้ถือว่า **ไม่ผ่าน** และไม่มี flag ยกเว้นแบบเงียบ
"""

from __future__ import annotations

from urllib.parse import urlparse

DEFAULT_DEV_REDIS_DB = 0
TEST_DB_SUFFIX = "_test"
REQUIRED_ENV = "TEST_ENVIRONMENT"


def database_name(url: str) -> str:
    """ชื่อฐานข้อมูลจาก SQLAlchemy URL — คืน "" ถ้าอ่านไม่ได้."""
    try:
        parsed = urlparse(url or "")
    except ValueError:
        return ""
    if not parsed.scheme.startswith(("postgres", "postgresql")):
        return ""
    return parsed.path.lstrip("/").strip()


def redis_db_index(url: str) -> int | None:
    """หมายเลข DB ของ Redis — คืน None ถ้าอ่านไม่ได้ (ไม่เดาเป็น 0)."""
    try:
        parsed = urlparse(url or "")
    except ValueError:
        return None
    if not parsed.scheme.startswith("redis"):
        return None
    path = parsed.path.lstrip("/").strip()
    if not path:
        return 0
    try:
        return int(path)
    except ValueError:
        return None


def _dev_redis_db(env) -> int:
    try:
        return int(env.get("DEV_REDIS_DB", DEFAULT_DEV_REDIS_DB))
    except (TypeError, ValueError):
        return DEFAULT_DEV_REDIS_DB


def check_test_environment(*, database_url: str, redis_url: str, env) -> list[str]:
    """คืนรายการข้อที่ไม่ผ่านทั้งหมด — ลิสต์ว่างแปลว่าผ่าน."""
    violations: list[str] = []

    if env.get(REQUIRED_ENV) != "1":
        violations.append(f"{REQUIRED_ENV} ต้องเป็น '1' — ได้ {env.get(REQUIRED_ENV)!r}")

    name = database_name(database_url)
    if not name:
        violations.append(f"อ่านชื่อ database จาก URL ไม่ได้: {database_url!r}")
    elif name != "hub_test" and not name.endswith(TEST_DB_SUFFIX):
        violations.append(
            f"database ต้องชื่อ 'hub_test' หรือลงท้าย '{TEST_DB_SUFFIX}' — ได้ {name!r}"
        )

    index = redis_db_index(redis_url)
    dev_index = _dev_redis_db(env)
    if index is None:
        violations.append(f"อ่าน redis DB จาก URL ไม่ได้: {redis_url!r}")
    elif index == dev_index:
        violations.append(f"redis DB {index} เป็นของ dev — ต้องใช้ DB อื่นสำหรับเทส")

    return violations


def assert_test_environment(*, database_url: str, redis_url: str, env) -> None:
    """หยุดทันทีถ้าไม่ผ่าน — ไม่มีทางข้าม."""
    violations = check_test_environment(
        database_url=database_url, redis_url=redis_url, env=env
    )
    if violations:
        lines = "\n".join(f"  - {v}" for v in violations)
        raise RuntimeError(
            "ปฏิเสธการรันเทส: สภาพแวดล้อมไม่ใช่ของเทส\n"
            f"{lines}\n"
            "  วิธีแก้: ตั้ง TEST_ENVIRONMENT=1, DATABASE_URL ไปที่ hub_test "
            "และ REDIS_URL ไปที่ DB ของเทส"
        )
