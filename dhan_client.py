"""Singleton wrapper around the dhanhq SDK client."""

from __future__ import annotations

import logging
from functools import lru_cache

from dhanhq import dhanhq, DhanContext

import config

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_dhan() -> dhanhq:
    """Return a cached dhanhq client instance."""
    config.validate_credentials()
    ctx = DhanContext(config.DHAN_CLIENT_ID, config.DHAN_ACCESS_TOKEN)
    client = dhanhq(ctx)
    logger.info("Dhan client initialised for client_id=%s", config.DHAN_CLIENT_ID)
    return client


def safe_call(fn_name: str, *args, **kwargs):
    """
    Call a method on the dhanhq client, catching all exceptions.

    Returns the raw API response dict on success, or raises RuntimeError
    with a clean message on failure.
    """
    client = get_dhan()
    try:
        method = getattr(client, fn_name)
        return method(*args, **kwargs)
    except AttributeError:
        raise RuntimeError(f"dhanhq SDK has no method '{fn_name}'")
    except Exception as exc:
        msg = str(exc)
        logger.error("Dhan API error in %s: %s", fn_name, msg)
        raise RuntimeError(f"Dhan API error: {msg}") from exc
