"""Test-environment guard + Redis namespace — logic ล้วน ไม่ import โค้ดแอป.

เหตุผลที่ต้องมี: ชุดเทสเคยรันบน `hub_db` ของ dev โดยตรง ทำให้ข้อมูล seed เพี้ยนถาวร
(นักศึกษา 56 คนค้างสถานะ graduated/resigned จน fixture ที่ต้องใช้ student ถูก skip
ทั้งหมด และผล "0 failed" กลายเป็นไม่มีความหมาย)

กติกาที่ตกลงไว้
  * ฐานข้อมูลต้องชื่อ `hub_test` หรือลงท้าย `_test`
  * Redis ต้องไม่ใช่ DB ของ dev
  * ต้องตั้ง `TEST_ENVIRONMENT=1`
  * ถ้าไม่ครบให้หยุดก่อน collect tests — **ไม่มี flag ยกเว้นแบบเงียบ**
  * key ของ Redis ต่อรอบใช้ namespace `test:{run_id}:` เพื่อวัดการรั่วและลบเฉพาะรอบนั้น
    โดยไม่ใช้ FLUSHDB

รัน (ไม่ต้องใช้ Docker):
  cd hub/backend && python -m pytest tests/test_env_guard.py --noconftest -q
"""

from __future__ import annotations

import pytest

from tests.support import env_guard as G
from tests.support import redis_namespace as NS
from tests.support import run_lock as LOCK

DEV_DB = "postgresql+psycopg2://postgres:5432/hub_db"
TEST_DB = "postgresql+psycopg2://postgres:5432/hub_test"
DEV_REDIS = "redis://redis:6379/0"
TEST_REDIS = "redis://redis:6379/15"
OK_ENV = {"TEST_ENVIRONMENT": "1"}


# ─────────────────────────────────────────────────────────────
# การอ่านค่า
# ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url, expected",
    [
        (DEV_DB, "hub_db"),
        (TEST_DB, "hub_test"),
        ("postgresql://h:5432/hub_test?sslmode=require", "hub_test"),
        ("postgresql://h:5432/", ""),
    ],
)
def test_database_name(url, expected):
    assert G.database_name(url) == expected


@pytest.mark.parametrize(
    "url, expected",
    [
        (DEV_REDIS, 0),
        (TEST_REDIS, 15),
        ("redis://redis:6379", 0),
        ("redis://redis:6379/3?decode_responses=true", 3),
    ],
)
def test_redis_db_index(url, expected):
    assert G.redis_db_index(url) == expected


def test_unparsable_urls_do_not_pass_silently():
    assert G.database_name("not-a-url") == ""
    assert G.redis_db_index("not-a-url") is None
    v = G.check_test_environment(
        database_url="not-a-url", redis_url="not-a-url", env=OK_ENV
    )
    assert v, "URL ที่อ่านไม่ได้ต้องถือว่าไม่ผ่าน"


# ─────────────────────────────────────────────────────────────
# เกณฑ์ผ่าน / ไม่ผ่าน
# ─────────────────────────────────────────────────────────────


def test_clean_test_environment_passes():
    assert (
        G.check_test_environment(database_url=TEST_DB, redis_url=TEST_REDIS, env=OK_ENV)
        == []
    )


def test_database_suffix_test_is_allowed():
    url = "postgresql+psycopg2://postgres:5432/hub_ci_test"
    assert (
        G.check_test_environment(database_url=url, redis_url=TEST_REDIS, env=OK_ENV)
        == []
    )


@pytest.mark.parametrize(
    "kwargs, reason",
    [
        ({"database_url": DEV_DB}, "database"),
        ({"redis_url": DEV_REDIS}, "redis"),
        ({"env": {}}, "TEST_ENVIRONMENT"),
        ({"env": {"TEST_ENVIRONMENT": "0"}}, "TEST_ENVIRONMENT"),
        ({"env": {"TEST_ENVIRONMENT": "true"}}, "TEST_ENVIRONMENT"),
    ],
)
def test_each_violation_is_reported(kwargs, reason):
    args = {"database_url": TEST_DB, "redis_url": TEST_REDIS, "env": OK_ENV}
    args.update(kwargs)
    violations = G.check_test_environment(**args)
    assert violations, f"ต้องรายงานว่าไม่ผ่านเมื่อ {reason}"
    assert any(reason.lower() in v.lower() for v in violations), violations


def test_all_violations_reported_together():
    v = G.check_test_environment(database_url=DEV_DB, redis_url=DEV_REDIS, env={})
    assert len(v) == 3


def test_dev_redis_index_is_configurable():
    """ถ้า dev ใช้ DB 2 ก็ต้องกัน DB 2 และยอม DB 0."""
    env = {**OK_ENV, "DEV_REDIS_DB": "2"}
    assert G.check_test_environment(
        database_url=TEST_DB, redis_url="redis://redis:6379/2", env=env
    )
    assert (
        G.check_test_environment(
            database_url=TEST_DB, redis_url="redis://redis:6379/0", env=env
        )
        == []
    )


def test_assert_raises_and_lists_every_violation():
    with pytest.raises(RuntimeError) as ei:
        G.assert_test_environment(database_url=DEV_DB, redis_url=DEV_REDIS, env={})
    msg = str(ei.value)
    assert "hub_db" in msg and "TEST_ENVIRONMENT" in msg


def test_assert_passes_on_clean_environment():
    G.assert_test_environment(database_url=TEST_DB, redis_url=TEST_REDIS, env=OK_ENV)


def test_no_bypass_flag_exists():
    """ห้ามมีทางยกเว้นแบบเงียบ — ไม่ว่า env จะตั้งอะไรก็ข้ามไม่ได้."""
    for name in ("SKIP", "FORCE", "ALLOW", "BYPASS", "IGNORE", "OVERRIDE", "YES"):
        env = {f"{name}_TEST_ENV_GUARD": "1", f"TEST_GUARD_{name}": "1"}
        assert G.check_test_environment(
            database_url=DEV_DB, redis_url=DEV_REDIS, env=env
        )


# ─────────────────────────────────────────────────────────────
# Redis namespace ต่อรอบ
# ─────────────────────────────────────────────────────────────


class FakeRedis:
    """Redis ปลอมเท่าที่ proxy ต้องใช้ — เก็บ key ที่ถูกเรียกจริงไว้ตรวจ."""

    def __init__(self):
        self.store: dict = {}
        self.calls: list = []
        self.last_set_kwargs: dict = {}

    def set(self, key, value, **kw):
        self.calls.append(("set", key))
        self.last_set_kwargs = kw
        if kw.get("nx") and key in self.store:
            return None
        self.store[key] = value
        return True

    def setex(self, key, ttl, value):
        self.calls.append(("setex", key))
        self.store[key] = value
        return True

    def get(self, key):
        self.calls.append(("get", key))
        return self.store.get(key)

    def getdel(self, key):
        self.calls.append(("getdel", key))
        return self.store.pop(key, None)

    def delete(self, *keys):
        self.calls.append(("delete", keys))
        return sum(self.store.pop(k, None) is not None for k in keys)

    def exists(self, *keys):
        self.calls.append(("exists", keys))
        return sum(k in self.store for k in keys)

    def rpush(self, key, *values):
        self.calls.append(("rpush", key))
        self.store.setdefault(key, []).extend(values)
        return len(self.store[key])

    def llen(self, key):
        self.calls.append(("llen", key))
        return len(self.store.get(key, []))

    def lindex(self, key, index):
        self.calls.append(("lindex", key))
        return self.store.get(key, [])[index]

    def scan_iter(self, match=None, count=None):
        self.calls.append(("scan_iter", match))
        import fnmatch

        for k in list(self.store):
            if match is None or fnmatch.fnmatch(k, match):
                yield k

    def flushdb(self):  # ต้องไม่ถูกเรียกผ่าน proxy
        raise AssertionError("flushdb ต้องถูกปฏิเสธ")


def test_run_id_is_unique_and_filename_safe():
    a, b = NS.new_run_id(), NS.new_run_id()
    assert a != b
    assert a.replace("-", "").replace("_", "").isalnum()


def test_prefix_format():
    assert NS.namespace_prefix("abc123") == "test:abc123:"


def test_write_and_read_go_through_namespace():
    fake = FakeRedis()
    r = NS.NamespacedRedis(fake, "test:run1:")
    r.set("stepup:u1:j1", "x")
    assert fake.store == {"test:run1:stepup:u1:j1": "x"}
    assert r.get("stepup:u1:j1") == "x"
    assert r.exists("stepup:u1:j1") == 1


def test_multi_key_commands_are_prefixed():
    fake = FakeRedis()
    r = NS.NamespacedRedis(fake, "test:run1:")
    r.set("a", "1")
    r.set("b", "2")
    assert r.delete("a", "b") == 2
    assert fake.store == {}


def test_scan_iter_returns_keys_without_prefix():
    fake = FakeRedis()
    r = NS.NamespacedRedis(fake, "test:run1:")
    r.set("stepup:u1", "x")
    fake.store["test:other:leak"] = "y"  # ของรอบอื่น — ต้องไม่เห็น
    assert list(r.scan_iter(match="stepup:*")) == ["stepup:u1"]
    assert list(r.scan_iter()) == ["stepup:u1"]


def test_scan_iter_of_shared_keys_keeps_real_name():
    """key ข้ามบริการไม่มี prefix ให้ตัด — ต้องคืนชื่อจริง ไม่ใช่ตัดหัวทิ้ง."""
    fake = FakeRedis()
    r = NS.NamespacedRedis(fake, "test:run1:")
    r.rpush("l3resid:u1", "x")
    assert list(r.scan_iter(match="l3resid:*")) == ["l3resid:u1"]


def test_unsupported_command_is_refused_not_passed_through():
    """คำสั่งที่ proxy ยังไม่รองรับต้อง raise — ห้ามหลุดไปเขียนนอก namespace."""
    fake = FakeRedis()
    r = NS.NamespacedRedis(fake, "test:run1:")
    with pytest.raises(NS.UnsupportedRedisCommand):
        r.flushdb()
    with pytest.raises(NS.UnsupportedRedisCommand):
        r.does_not_exist_at_all("k")


def test_leak_detection_and_cleanup_without_flushdb():
    fake = FakeRedis()
    r = NS.NamespacedRedis(fake, "test:run1:")
    r.set("a", "1")
    r.rpush("hist", "x")
    fake.store["test:other:keep"] = "z"
    fake.store["dev-key"] = "z"

    assert sorted(NS.keys_in_namespace(fake, "test:run1:")) == ["a", "hist"]
    assert NS.delete_namespace(fake, "test:run1:") == 2
    assert sorted(fake.store) == ["dev-key", "test:other:keep"]
    assert NS.keys_in_namespace(fake, "test:run1:") == []


# ─────────────────────────────────────────────────────────────
# key ที่เป็นสัญญาข้ามบริการ (hub เขียน · ml-service อ่านเอง)
# ─────────────────────────────────────────────────────────────


def test_shared_prefixes_declared():
    assert NS.SHARED_PREFIXES == ("l3dup:", "l3resid:")


def test_shared_contract_keys_keep_their_real_name():
    """`l3resid:` ต้องไม่ถูกเติม prefix — ml-service อ่านคีย์นี้ตรง ๆ ด้วย client ของตัวเอง."""
    fake = FakeRedis()
    r = NS.NamespacedRedis(fake, "test:run1:")
    r.rpush("l3resid:u1", "x")
    r.set("l3dup:u1", "1")
    r.set("stepup:u1:j1", "y")
    assert sorted(fake.store) == ["l3dup:u1", "l3resid:u1", "test:run1:stepup:u1:j1"]
    assert r.get("l3dup:u1") == "1"


def test_list_commands_used_by_l3_are_supported():
    fake = FakeRedis()
    r = NS.NamespacedRedis(fake, "test:run1:")
    r.rpush("l3resid:u1", "a", "b")
    assert r.llen("l3resid:u1") == 2
    assert r.lindex("l3resid:u1", 0) == "a"


def test_delete_shared_keys_clears_only_shared():
    fake = FakeRedis()
    r = NS.NamespacedRedis(fake, "test:run1:")
    r.rpush("l3resid:u1", "x")
    r.set("l3dup:u1", "1")
    r.set("stepup:u1", "y")
    fake.store["dev-key"] = "z"
    assert NS.delete_shared_keys(fake) == 2
    assert sorted(fake.store) == ["dev-key", "test:run1:stepup:u1"]


# ─────────────────────────────────────────────────────────────
# lock กันรันซ้อนบน Redis DB ของเทส
# ─────────────────────────────────────────────────────────────


def test_lock_is_exclusive_and_names_the_holder():
    fake = FakeRedis()
    LOCK.acquire(fake, "run-a")
    with pytest.raises(LOCK.TestRunLocked) as ei:
        LOCK.acquire(fake, "run-b")
    assert "run-a" in str(ei.value)


def test_lock_released_by_owner_only():
    fake = FakeRedis()
    LOCK.acquire(fake, "run-a")
    assert LOCK.release(fake, "run-b") is False  # คนอื่นปลดไม่ได้
    assert LOCK.release(fake, "run-a") is True
    LOCK.acquire(fake, "run-b")  # ปลดแล้วรอบถัดไปจับได้


def test_lock_sets_expiry_so_it_cannot_wedge_forever():
    fake = FakeRedis()
    LOCK.acquire(fake, "run-a", ttl=123)
    assert ("set", LOCK.LOCK_KEY) in fake.calls
    assert fake.last_set_kwargs.get("ex") == 123
    assert fake.last_set_kwargs.get("nx") is True


def test_lock_key_is_outside_run_namespace():
    """lock ต้องไม่อยู่ใน namespace ของรอบ ไม่งั้นจะถูกลบตอน cleanup ของรอบตัวเอง."""
    assert not LOCK.LOCK_KEY.startswith("test:run")
    fake = FakeRedis()
    LOCK.acquire(fake, "run-a")
    r = NS.NamespacedRedis(fake, "test:run-a:")
    NS.delete_namespace(fake, "test:run-a:")
    assert LOCK.LOCK_KEY in fake.store
    assert r is not None
