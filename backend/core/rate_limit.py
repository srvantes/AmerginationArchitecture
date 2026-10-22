"""Atomic sliding windows shared across processes through Redis."""
import hashlib
import hmac
import logging
import math
from uuid import uuid4

from fastapi import Depends, HTTPException, Request
from redis.exceptions import RedisError

from backend.core.config import settings
from backend.core.redis import redis_client
from backend.core.security import get_current_user, get_verified_user
from backend.database.sсhemas.user import UserLogin
from backend.database.sсhemas.password_reset import ResetRequest

log = logging.getLogger(__name__)
RATE_LIMIT_RESPONSES = {
    429: {"description": "Слишком частые действия",
          "headers": {"Retry-After": {"description": "Через сколько секунд повторить запрос", "schema": {"type": "string"}}}},
    503: {"description": "Redis проверки лимитов временно недоступен",
          "headers": {"Retry-After": {"schema": {"type": "string"}}}},
}

# Redis time avoids clock differences between API workers. Check every policy
# before charging any of them, so cooldown rejections don't consume hourly quota.
WINDOW_SCRIPT = """
local clock = redis.call('TIME')
local now = tonumber(clock[1]) * 1000 + math.floor(tonumber(clock[2]) / 1000)
local wait = 0
for i, key in ipairs(KEYS) do
    local limit = tonumber(ARGV[2*i])
    local window = tonumber(ARGV[2*i+1])
    redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)
    local count = redis.call('ZCARD', key)
    if count >= limit then
        local oldest = redis.call('ZRANGE', key, count-limit, count-limit, 'WITHSCORES')
        wait = math.max(wait, tonumber(oldest[2]) + window - now)
    end
end
if wait > 0 then return wait end
for i, key in ipairs(KEYS) do
    redis.call('ZADD', key, now, ARGV[1])
    redis.call('PEXPIRE', key, tonumber(ARGV[2*i+1]))
end
return 0
"""


def identity(value):
    # Don't store IP addresses or login names in Redis keys or logs.
    return hmac.new(settings.SECRET_KEY.encode(), str(value).encode(), hashlib.sha256).hexdigest()


def client_ip(request):
    # Forwarded headers are trusted only by the server's configured proxy layer.
    return request.client.host if request.client else "unknown"


def policy(action, actor, count, seconds):
    return (f"rate:v1:{{limits}}:{action}:{identity(actor)}", count, seconds * 1000)


class RedisRateLimiter:
    def __init__(self, client=None):
        self.client = client if client is not None else redis_client

    async def check(self, policies):
        keys = [key for key, _, _ in policies]
        arguments = [uuid4().hex]
        for _, count, milliseconds in policies:
            arguments.extend((count, milliseconds))
        try:
            wait_ms = int(await self.client.eval(WINDOW_SCRIPT, len(keys), *keys, *arguments))
        except RedisError:
            log.warning("Redis rate limiter unavailable")
            # Stop protected writes rather than silently disabling protection.
            raise HTTPException(503, "Сервис временно недоступен. Повторите через 5 секунд.",
                                headers={"Retry-After": "5"}) from None
        if wait_ms > 0:
            seconds = max(1, math.ceil(wait_ms / 1000))
            raise HTTPException(429, f"Слишком частые действия. Повторите через {seconds} сек.",
                                headers={"Retry-After": str(seconds)})


def get_rate_limiter():
    return RedisRateLimiter()


async def limited_registration(request: Request, limiter=Depends(get_rate_limiter)):
    await limiter.check([policy("registration", client_ip(request), settings.REGISTRATION_LIMIT_PER_HOUR, 3600)])


async def limited_login(request: Request, form_data: UserLogin, limiter=Depends(get_rate_limiter)):
    ip = client_ip(request)
    await limiter.check([
        policy("login-ip", ip, settings.LOGIN_LIMIT_PER_5_MINUTES, 300),
        policy("login-account-ip", ip + ":" + form_data.username.strip().casefold(),
               settings.LOGIN_ACCOUNT_LIMIT_PER_5_MINUTES, 300),
    ])


async def limited_comment_create(user=Depends(get_verified_user), limiter=Depends(get_rate_limiter)):
    await limiter.check([
        policy("comment-hour", user.id, settings.COMMENT_LIMIT_PER_HOUR, 3600),
        policy("comment-cooldown", user.id, 1, settings.COMMENT_COOLDOWN_SECONDS),
    ])
    return user


async def limited_discussion_edit(user=Depends(get_verified_user), limiter=Depends(get_rate_limiter)):
    await limiter.check([policy("discussion-edit", user.id, settings.DISCUSSION_EDIT_LIMIT_PER_MINUTE, 60)])
    return user


async def limited_like(user=Depends(get_verified_user), limiter=Depends(get_rate_limiter)):
    await limiter.check([policy("like", user.id, settings.LIKE_LIMIT_PER_MINUTE, 60)])
    return user


async def limited_review_create(user=Depends(get_verified_user), limiter=Depends(get_rate_limiter)):
    await limiter.check([policy("review-create", user.id, settings.REVIEW_LIMIT_PER_HOUR, 3600)])
    return user


async def limited_email_send(user=Depends(get_current_user), limiter=Depends(get_rate_limiter)):
    await limiter.check([policy("email-send", user.id, settings.EMAIL_SEND_LIMIT_PER_HOUR, 3600)])
    return user


async def limited_reset_request(request: Request, data: ResetRequest, limiter=Depends(get_rate_limiter)):
    await limiter.check([
        policy("reset-ip", client_ip(request), 10, 3600),
        policy("reset-email", data.email, 5, 3600),
        policy("reset-pause", data.email, 1, 120),
    ])


async def limited_reset_attempt(request: Request, limiter=Depends(get_rate_limiter)):
    await limiter.check([policy("reset-attempt", client_ip(request), 30, 300)])


async def limited_profile_edit(user=Depends(get_current_user), limiter=Depends(get_rate_limiter)):
    await limiter.check([policy("profile-edit", user.id, 30, 60)])
    return user


async def limited_avatar_upload(user=Depends(get_current_user), limiter=Depends(get_rate_limiter)):
    await limiter.check([policy("avatar-upload", user.id, 10, 3600)])
    return user
