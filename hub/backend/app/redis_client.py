"""Redis client — ใช้เก็บ OAuth state, authorization code, และ cache.

decode_responses=True ทำให้ค่าที่ดึงมาเป็น str (ไม่ใช่ bytes)
"""
import redis

from app.config import settings

redis_client = redis.from_url(settings.redis_url, decode_responses=True)
