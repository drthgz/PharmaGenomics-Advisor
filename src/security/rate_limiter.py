"""Rate limiting using a sliding window counter.

Enforces a maximum number of requests per time window per session.
Returns HTTP 429 equivalent when exceeded.
"""

from __future__ import annotations

import time
from collections import defaultdict

from src.exceptions import RateLimitExceededError
from src.models import ValidationResult


class RateLimiter:
    """Sliding window rate limiter.

    Usage:
        limiter = RateLimiter(max_requests=100, window_seconds=60)
        result = limiter.check("session_123")
        if not result.is_valid:
            # Return HTTP 429 with retry-after header
            ...
    """

    def __init__(self, max_requests: int = 100, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)

    def check(self, session_id: str) -> ValidationResult:
        """Check if the session has exceeded its rate limit.

        Args:
            session_id: Unique session identifier.

        Returns:
            ValidationResult. If rate limit exceeded, error_message contains retry-after info.
        """
        now = time.time()
        window_start = now - self.window_seconds

        # Prune old entries
        self._requests[session_id] = [
            ts for ts in self._requests[session_id] if ts > window_start
        ]

        if len(self._requests[session_id]) >= self.max_requests:
            # Calculate retry-after: time until oldest request exits the window
            oldest = self._requests[session_id][0]
            retry_after = int(oldest + self.window_seconds - now) + 1
            return ValidationResult(
                is_valid=False,
                error_message=f"Rate limit exceeded ({self.max_requests} requests per {self.window_seconds}s). Retry after {retry_after}s.",
                rejected_reason="rate_limit_exceeded",
            )

        # Record this request
        self._requests[session_id].append(now)
        return ValidationResult(is_valid=True)

    def reset(self, session_id: str) -> None:
        """Reset rate limit counter for a session (for testing)."""
        self._requests.pop(session_id, None)
