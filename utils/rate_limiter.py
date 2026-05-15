"""Simple token-bucket rate limiter for Dhan API endpoints."""

from __future__ import annotations

import time
import threading
from typing import Dict


class RateLimiter:
    """Thread-safe per-key rate limiter using minimum interval between calls."""

    def __init__(self) -> None:
        self._last_call: Dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, key: str, min_interval: float) -> None:
        """Block until at least `min_interval` seconds have passed since last call for `key`."""
        with self._lock:
            last = self._last_call.get(key, 0.0)
            elapsed = time.monotonic() - last
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed)
            self._last_call[key] = time.monotonic()


# Module-level singleton
_limiter = RateLimiter()


def throttle(key: str, min_interval: float) -> None:
    """Convenience wrapper around the module singleton."""
    _limiter.wait(key, min_interval)
