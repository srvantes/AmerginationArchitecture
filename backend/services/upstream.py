"""Bounded retries for read-only provider requests; never log URLs or tokens."""
import asyncio
import logging
import random
import re
import time
from contextvars import ContextVar
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import aiohttp
import httpx
import requests
from anime_parsers_ru import errors

from backend.core.config import settings

log = logging.getLogger(__name__)
RETRY_STATUSES = {429, 500, 502, 503, 504, 520}
sync_deadline = ContextVar("upstream_deadline", default=None)


def run_sync_operation(operation, deadline=None):
    token = sync_deadline.set(deadline if deadline is not None else
                              time.monotonic() + settings.EXTERNAL_SERVICE_TIMEOUT_SECONDS)
    try:
        return operation()
    finally:
        sync_deadline.reset(token)


def retryable(error):
    if isinstance(error, requests.exceptions.SSLError):
        return False
    if isinstance(error, (httpx.TimeoutException, httpx.NetworkError,
                          httpx.RemoteProtocolError,
                          requests.Timeout, requests.ConnectionError,
                          aiohttp.ClientConnectionError, asyncio.TimeoutError,
                          errors.TooManyRequests, errors.ServiceIsOverloaded)):
        return True
    if isinstance(error, (httpx.HTTPStatusError, requests.HTTPError)):
        return error.response.status_code in RETRY_STATUSES
    if isinstance(error, aiohttp.ClientResponseError):
        return error.status in RETRY_STATUSES
    if isinstance(error, errors.ServiceError):
        # The parser exposes status codes only in text; don't retry arbitrary errors.
        match = re.search(r"(?:статус|получен:|status(?: code)?[:=]?)\s*(\d{3})\b", str(error), re.I)
        return bool(match and int(match[1]) in RETRY_STATUSES)
    return False


def retry_delay(response, attempt):
    header = response.headers.get("Retry-After") if response is not None else None
    if header:
        try:
            delay = float(header)
        except ValueError:
            try:
                date = parsedate_to_datetime(header)
                delay = (date - datetime.now(timezone.utc)).total_seconds()
            except (TypeError, ValueError):
                delay = 0
        # Don't retry earlier than the provider permits, or hold requests for minutes.
        if delay > settings.EXTERNAL_RETRY_MAX_DELAY_SECONDS:
            return None
        return max(0, delay)
    return min(settings.EXTERNAL_RETRY_MAX_DELAY_SECONDS,
               0.25 * (2 ** attempt) + random.uniform(0, 0.1))


async def run_async(operation, provider):
    """One deadline covers every attempt and backoff, including parser calls."""
    async with asyncio.timeout(settings.EXTERNAL_SERVICE_TIMEOUT_SECONDS):
        for attempt in range(settings.EXTERNAL_SERVICE_ATTEMPTS):
            try:
                return await operation()
            except Exception as error:
                if attempt + 1 == settings.EXTERNAL_SERVICE_ATTEMPTS or not retryable(error):
                    raise
                delay = retry_delay(getattr(error, "response", None), attempt)
                if delay is None:
                    raise
                log.warning("%s request retry %s (%s)", provider, attempt + 1, type(error).__name__)
                await asyncio.sleep(delay)


def get_sync(url, **kwargs):
    """Socket timeouts also apply to requests issued inside synchronous parsers."""
    deadline = sync_deadline.get() or time.monotonic() + settings.EXTERNAL_SERVICE_TIMEOUT_SECONDS
    for attempt in range(settings.EXTERNAL_SERVICE_ATTEMPTS):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise requests.Timeout("Provider operation deadline expired")
        kwargs["timeout"] = (min(settings.EXTERNAL_CONNECT_TIMEOUT_SECONDS, remaining / 2),
                             min(settings.EXTERNAL_READ_TIMEOUT_SECONDS, remaining / 2))
        response = None
        try:
            response = requests.get(url, **kwargs)
            if response.status_code not in RETRY_STATUSES:
                return response
            response.raise_for_status()
        except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as error:
            if attempt + 1 == settings.EXTERNAL_SERVICE_ATTEMPTS or not retryable(error):
                raise
            delay = retry_delay(response, attempt)
            if delay is None:
                raise
            if response is not None:
                response.close()
            if time.monotonic() + delay >= deadline:
                raise requests.Timeout("Provider operation deadline expired") from error
            log.warning("AnimeGo request retry %s (%s)", attempt + 1, type(error).__name__)
            time.sleep(delay)


class ParserRequests:
    """Adapter for anime-parsers-ru's module-local requests dependency."""
    get = staticmethod(get_sync)

    def __getattr__(self, name):
        return getattr(requests, name)
