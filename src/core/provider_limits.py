"""Process-wide provider cooldowns based on HTTP Retry-After, without sleeps."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import math
import threading
import time


class ProviderCooldowns:
    """Share rate-limit deadlines across searches while keeping providers separate.

    Deadlines use the monotonic clock. An HTTP-date is converted to a duration
    once, so later wall-clock changes cannot invalidate the stored cooldown.
    Create an independent instance for isolated clients or tests.
    """

    def __init__(self):
        self._deadlines = {}
        self._lock = threading.Lock()

    @staticmethod
    def _key(provider):
        key = str(provider).strip().lower()
        return 'openalex' if key == 'openalex' or key.startswith('openalex_') else key

    @staticmethod
    def _delay(retry_after):
        try:
            delay = float(retry_after)
        except (TypeError, ValueError, OverflowError):
            try:
                date = parsedate_to_datetime(str(retry_after))
                if date.tzinfo is None:
                    date = date.replace(tzinfo=timezone.utc)
                delay = (date - datetime.now(timezone.utc)).total_seconds()
            except (TypeError, ValueError, OverflowError):
                delay = 60.0
        if not math.isfinite(delay):
            delay = 60.0
        return max(1.0, delay)

    def remaining(self, provider, now=None):
        """Return seconds until this provider may be retried, or zero."""
        with self._lock:
            instant = time.monotonic() if now is None else now
            return max(0.0, self._deadlines.get(self._key(provider), instant) - instant)

    def record_limit(self, provider, retry_after, now=None):
        """Record a 429 response and return the effective remaining delay.

        A later response never shortens an existing cooldown. Missing or invalid
        Retry-After uses 60 seconds; valid long delays are preserved in full.
        """
        delay = self._delay(retry_after)
        with self._lock:
            instant = time.monotonic() if now is None else now
            key = self._key(provider)
            deadline = max(self._deadlines.get(key, instant), instant + delay)
            self._deadlines[key] = deadline
            return deadline - instant


provider_cooldowns = ProviderCooldowns()


def remaining(provider, now=None):
    return provider_cooldowns.remaining(provider, now=now)


def record_limit(provider, retry_after, now=None):
    return provider_cooldowns.record_limit(provider, retry_after, now=now)
