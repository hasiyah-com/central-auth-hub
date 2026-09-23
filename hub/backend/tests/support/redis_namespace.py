"""Redis namespace ต่อรอบทดสอบ — `test:{run_id}:` นำหน้าทุก key.

มีไว้เพื่อ
  * วัดว่ารอบนั้นทิ้ง key ค้างไว้กี่ตัว (ที่ผ่านมา `l3resid` ค้าง 311 key ไม่มี TTL)
  * ลบเฉพาะ key ของรอบตัวเอง โดยไม่ใช้ `FLUSHDB` ซึ่งจะลบของรอบอื่นไปด้วย

คำสั่งที่ยังไม่รองรับจะ **raise** ไม่ปล่อยผ่านไปยัง client จริง เพราะการปล่อยผ่าน
หมายถึง key หลุดออกนอก namespace โดยไม่มีใครรู้
"""

from __future__ import annotations

import uuid

PREFIX_TEMPLATE = "test:{run_id}:"

# key ที่เป็น **สัญญาข้ามบริการ**: hub เขียน · ml-service อ่านเองด้วย client ของตัวเอง
# (ml-service/app/main.py อ่าน REDIS_URL ของตัวเอง) — ใส่ prefix ไม่ได้เพราะอีกฝั่งไม่รู้จัก
# การแยกของ key กลุ่มนี้อาศัย "คนละ Redis DB" แทน (ml-service ของเทสชี้ DB ของเทส)
SHARED_PREFIXES = ("l3dup:", "l3resid:")


def apply_prefix(prefix: str, key) -> str:
    """เติม namespace — ยกเว้น key ที่เป็นสัญญาข้ามบริการ."""
    text = str(key)
    if text.startswith(SHARED_PREFIXES):
        return text
    return f"{prefix}{text}"


# คำสั่งที่ key เป็นอาร์กิวเมนต์แรกตัวเดียว
_SINGLE_KEY = frozenset(
    {
        "get",
        "getdel",
        "set",
        "setex",
        "setnx",
        "incr",
        "decr",
        "expire",
        "ttl",
        "persist",
        "type",
        "rpush",
        "lpush",
        "lrange",
        "ltrim",
        "llen",
        "lindex",
        "sadd",
        "srem",
        "smembers",
        "scard",
        "hset",
        "hget",
        "hgetall",
        "hdel",
    }
)
# คำสั่งที่รับ key ได้หลายตัว
_MULTI_KEY = frozenset({"delete", "exists", "unlink", "touch"})
# คำสั่งที่ไม่มี key
_NO_KEY = frozenset({"ping"})


class UnsupportedRedisCommand(RuntimeError):
    """คำสั่งนี้ยังไม่ถูกทำให้ทำงานภายใต้ namespace — ปฏิเสธไว้ก่อนเพื่อกัน key รั่ว."""


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]


def namespace_prefix(run_id: str) -> str:
    return PREFIX_TEMPLATE.format(run_id=run_id)


class NamespacedPipeline:
    """pipeline ที่เติม prefix ให้ key เหมือนกัน."""

    _PASSTHROUGH = frozenset({"execute", "reset", "__enter__", "__exit__"})

    def __init__(self, pipe, prefix: str):
        self._pipe = pipe
        self._prefix = prefix

    def __getattr__(self, name: str):
        if name in _NO_KEY or name in self._PASSTHROUGH:
            return getattr(self._pipe, name)
        if name in _SINGLE_KEY:

            def single(key, *args, **kwargs):
                getattr(self._pipe, name)(
                    apply_prefix(self._prefix, key), *args, **kwargs
                )
                return self

            return single
        if name in _MULTI_KEY:

            def multi(*keys, **kwargs):
                getattr(self._pipe, name)(
                    *[apply_prefix(self._prefix, k) for k in keys], **kwargs
                )
                return self

            return multi
        raise UnsupportedRedisCommand(f"pipeline.{name} ยังไม่รองรับใน namespace ของเทส")


class NamespacedRedis:
    """ครอบ redis client จริง — ทุก key ถูกเติม `test:{run_id}:` โดยอัตโนมัติ."""

    def __init__(self, client, prefix: str):
        self._client = client
        self._prefix = prefix

    @property
    def prefix(self) -> str:
        return self._prefix

    @property
    def raw(self):
        """client จริง — ใช้เฉพาะตอนตรวจหรือล้าง namespace."""
        return self._client

    def _key(self, key) -> str:
        return apply_prefix(self._prefix, key)

    def scan_iter(self, match=None, count=None):
        pattern = self._key(match if match is not None else "*")
        for key in self._client.scan_iter(match=pattern, count=count):
            text = key.decode() if isinstance(key, bytes) else key
            # key ข้ามบริการไม่มี prefix ให้ตัด — คืนชื่อจริง
            yield text[len(self._prefix) :] if text.startswith(self._prefix) else text

    def pipeline(self, *args, **kwargs):
        return NamespacedPipeline(self._client.pipeline(*args, **kwargs), self._prefix)

    def __getattr__(self, name: str):
        if name in _NO_KEY:
            return getattr(self._client, name)
        if name in _SINGLE_KEY:

            def single(key, *args, **kwargs):
                return getattr(self._client, name)(self._key(key), *args, **kwargs)

            return single
        if name in _MULTI_KEY:

            def multi(*keys, **kwargs):
                return getattr(self._client, name)(
                    *[self._key(k) for k in keys], **kwargs
                )

            return multi
        raise UnsupportedRedisCommand(
            f"redis.{name} ยังไม่รองรับใน namespace ของเทส — "
            "เพิ่มใน tests/support/redis_namespace.py ก่อนใช้"
        )


def keys_in_namespace(client, prefix: str) -> list[str]:
    """key ที่ยังค้างใน namespace (ตัด prefix ออกแล้ว)."""
    out = []
    for key in client.scan_iter(match=f"{prefix}*"):
        text = key.decode() if isinstance(key, bytes) else key
        out.append(text[len(prefix) :])
    return out


def delete_namespace(client, prefix: str, *, batch: int = 200) -> int:
    """ลบเฉพาะ key ของ namespace นี้ — ไม่ใช้ FLUSHDB."""
    deleted = 0
    batch_keys: list[str] = []
    for key in list(client.scan_iter(match=f"{prefix}*")):
        batch_keys.append(key.decode() if isinstance(key, bytes) else key)
        if len(batch_keys) >= batch:
            deleted += client.delete(*batch_keys)
            batch_keys = []
    if batch_keys:
        deleted += client.delete(*batch_keys)
    return deleted


def delete_shared_keys(client) -> int:
    """ลบ key ที่เป็นสัญญาข้ามบริการใน Redis DB ของเทส (ไม่มี prefix ให้ลบตาม namespace)."""
    deleted = 0
    for prefix in SHARED_PREFIXES:
        keys = [
            key.decode() if isinstance(key, bytes) else key
            for key in client.scan_iter(match=f"{prefix}*")
        ]
        if keys:
            deleted += client.delete(*keys)
    return deleted
