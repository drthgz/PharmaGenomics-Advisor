"""Input validation against injection patterns.

Detects SQL injection, prompt injection, and command injection patterns
before data reaches agents or MCP servers.
"""

from __future__ import annotations

import re

from src.models import ValidationResult

# ─── Injection Pattern Definitions ───────────────────────────────────────────

SQL_INJECTION_PATTERNS = [
    r"(?i)\b(SELECT|INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE)\b\s",
    r"(?i)\b(UNION\s+SELECT|OR\s+1\s*=\s*1|AND\s+1\s*=\s*1)\b",
    r"(?i)(--|;)\s*(DROP|SELECT|INSERT|DELETE)",
    r"(?i)'\s*(OR|AND)\s+'",
]

PROMPT_INJECTION_PATTERNS = [
    r"(?i)(ignore|disregard|forget)\s+(previous|above|all|prior)\s+(instructions|prompts|rules)",
    r"(?i)you\s+are\s+now\s+(a|an|the)\b",
    r"(?i)(system|admin)\s*:\s*",
    r"(?i)jailbreak|DAN|do\s+anything\s+now",
]

COMMAND_INJECTION_PATTERNS = [
    r"[;|`]\s*(rm|cat|curl|wget|chmod|chown|sudo|bash|sh|python|perl)\s",
    r"\$\(.*\)",  # Command substitution
    r"&&\s*(rm|cat|curl|wget)",
    r"\|\s*(bash|sh|python)",
]


class InputValidator:
    """Validates inputs against known injection attack patterns.

    Usage:
        validator = InputValidator()
        result = validator.validate("SELECT * FROM users")
        # result.is_valid == False
    """

    def __init__(self, max_chars: int = 10_000):
        self.max_chars = max_chars
        self._patterns: list[tuple[str, re.Pattern]] = []

        for pattern in SQL_INJECTION_PATTERNS:
            self._patterns.append(("sql_injection", re.compile(pattern)))
        for pattern in PROMPT_INJECTION_PATTERNS:
            self._patterns.append(("prompt_injection", re.compile(pattern)))
        for pattern in COMMAND_INJECTION_PATTERNS:
            self._patterns.append(("command_injection", re.compile(pattern)))

    def validate(self, text: str) -> ValidationResult:
        """Check input for size limits and injection patterns.

        Args:
            text: User input to validate.

        Returns:
            ValidationResult with is_valid=True if clean, or error details if rejected.
        """
        # Size check
        if len(text) > self.max_chars:
            return ValidationResult(
                is_valid=False,
                error_message=f"Input exceeds {self.max_chars} character limit ({len(text)} chars)",
                rejected_reason="size_limit",
            )

        # Pattern matching
        for pattern_type, pattern in self._patterns:
            if pattern.search(text):
                return ValidationResult(
                    is_valid=False,
                    error_message="Input rejected: potentially malicious pattern detected",
                    rejected_reason=pattern_type,
                )

        return ValidationResult(is_valid=True)
