"""Temporary backoff for valid risk-step-up flows; no permanent account lock."""
from fastapi import HTTPException
from app.redis_client import redis_client

_FAILURE = """
local n = redis.call('INCR', KEYS[1])
if n == 1 then redis.call('EXPIRE', KEYS[1], 600) end
local delay = 0
if n >= 3 then
  if n >= 7 then delay = 300 else delay = 30 * (2 ^ (n - 3)) end
  redis.call('SET', KEYS[2], '1', 'EX', delay)
end
return delay
"""

def _keys(user_id, method):
    prefix = f'auth_retry:{user_id}:{method}'
    return prefix + ':count', prefix + ':wait'

def check(user_id, method):
    remaining = redis_client.ttl(_keys(user_id, method)[1])
    if remaining > 0:
        raise HTTPException(status_code=429, headers={'Retry-After': str(remaining)},
            detail={'code': 'auth_retry_wait', 'message': f'กรุณารอ {remaining} วินาทีก่อนลองยืนยันอีกครั้ง', 'retry_after': remaining})

def failed(user_id, method):
    return redis_client.eval(_FAILURE, 2, *_keys(user_id, method))

def succeeded(user_id, method):
    redis_client.delete(*_keys(user_id, method))
