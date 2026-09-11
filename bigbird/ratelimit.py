"""Adaptive pacing: back off when a site seems to be throttling us, and ease
back toward the profile's baseline delay once requests are succeeding again.

Sites signal "slow down" in different ways -- an explicit 429/403, a 5xx
while overloaded, or (seen from golfmk7.com's bot-mitigation layer) refusing
the connection outright after a burst of requests. All of these should push
the crawl's pace down, not just trigger a same-page retry at the same speed.
"""

import time

RETRYABLE_STATUS = {403, 408, 429, 500, 502, 503, 504}


class RateLimiter:
    def __init__(
        self,
        base_delay: float,
        max_delay: float = 120.0,
        backoff_factor: float = 2.0,
        decay_factor: float = 0.8,
        decay_after: int = 5,
    ):
        self.base_delay = base_delay
        self.delay = base_delay
        self.max_delay = max_delay
        self.backoff_factor = backoff_factor
        self.decay_factor = decay_factor
        self.decay_after = decay_after
        self._consecutive_successes = 0

    def wait(self) -> None:
        time.sleep(self.delay)

    def on_blocked(self) -> None:
        self.delay = min(self.delay * self.backoff_factor, self.max_delay)
        self._consecutive_successes = 0

    def on_success(self) -> None:
        self._consecutive_successes += 1
        if self._consecutive_successes >= self.decay_after and self.delay > self.base_delay:
            self.delay = max(self.delay * self.decay_factor, self.base_delay)
            self._consecutive_successes = 0
