"""Composable security middleware layer.

Chains all security checks in order: size → injection → PHI → rate limit.
Applied to all inputs before they reach any agent or MCP server.
"""

from __future__ import annotations

import os
import json
from typing import Any

from pydantic import BaseModel

from src.models import SecurityConfig, ValidationResult
from src.security.audit_logger import AuditLogger
from src.security.input_validator import InputValidator
from src.security.phi_detector import PHIDetector
from src.security.rate_limiter import RateLimiter


class SecurityLayer:
    """Composable security middleware chain.

    Applies all security checks in sequence. Stops at the first failure.

    Usage:
        security = SecurityLayer.from_env()
        result = security.validate("some input", session_id="user_123")
        if not result.is_valid:
            print(f"Rejected: {result.error_message}")
    """

    def __init__(self, config: SecurityConfig):
        self.config = config
        self.input_validator = InputValidator(max_chars=config.max_input_chars)
        self.phi_detector = PHIDetector(clinical_use_mode=config.clinical_use_mode)
        self.rate_limiter = RateLimiter(
            max_requests=config.rate_limit_requests,
            window_seconds=config.rate_limit_window_seconds,
        )
        self.audit_logger = AuditLogger(log_path=config.audit_log_path)

    @classmethod
    def from_env(cls) -> "SecurityLayer":
        """Create SecurityLayer from environment variables.

        Reads: PHI_CLINICAL_USE, RATE_LIMIT_REQUESTS, RATE_LIMIT_WINDOW_SECONDS,
               MAX_INPUT_CHARS, DATA_PERSISTENCE, AUDIT_LOG_PATH, OLLAMA_HOST,
               OLLAMA_PORT, OLLAMA_MODEL
        """
        config = SecurityConfig(
            phi_detection_enabled=True,
            clinical_use_mode=os.getenv("PHI_CLINICAL_USE", "false").lower() == "true",
            rate_limit_requests=int(os.getenv("RATE_LIMIT_REQUESTS", "100")),
            rate_limit_window_seconds=int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60")),
            max_input_chars=int(os.getenv("MAX_INPUT_CHARS", "10000")),
            data_persistence_enabled=os.getenv("DATA_PERSISTENCE", "false").lower() == "true",
            audit_log_path=os.getenv("AUDIT_LOG_PATH", "audit.log"),
            ollama_host=os.getenv("OLLAMA_HOST", "http://localhost"),
            ollama_port=int(os.getenv("OLLAMA_PORT", "11434")),
            ollama_model=os.getenv("OLLAMA_MODEL", "medgemma"),
        )
        return cls(config)

    def validate(self, input_data: str, session_id: str = "default") -> ValidationResult:
        """Run all security checks in sequence.

        Order: size limit → injection patterns → PHI detection → rate limit.

        Args:
            input_data: The user input to validate.
            session_id: Session identifier for rate limiting.

        Returns:
            ValidationResult — passes if all checks succeed, fails with first error.
        """
        # 1. Size limit and injection patterns
        result = self.input_validator.validate(input_data)
        if not result.is_valid:
            return result

        # 2. PHI detection
        result = self.phi_detector.check(input_data)
        if not result.is_valid:
            return result

        # 3. Rate limiting
        result = self.rate_limiter.check(session_id)
        if not result.is_valid:
            return result

        return ValidationResult(is_valid=True)

    def audit(
        self,
        agent_name: str,
        action_type: str,
        input_data: Any,
        output_data: Any,
    ):
        """Persist hashed audit metadata for an agent invocation."""
        return self.audit_logger.log(
            agent_name=agent_name,
            action_type=action_type,
            input_data=self._serialize_payload(input_data),
            output_data=self._serialize_payload(output_data),
        )

    @staticmethod
    def _serialize_payload(payload: Any) -> str:
        """Serialize structured payloads before hashing them."""
        return json.dumps(SecurityLayer._normalize_payload(payload), sort_keys=True, default=str)

    @staticmethod
    def _normalize_payload(payload: Any) -> Any:
        """Convert structured payloads into JSON-serializable data."""
        if isinstance(payload, BaseModel):
            return payload.model_dump(mode="json")
        if isinstance(payload, list):
            return [SecurityLayer._normalize_payload(item) for item in payload]
        if isinstance(payload, dict):
            return {
                str(key): SecurityLayer._normalize_payload(value)
                for key, value in sorted(payload.items(), key=lambda item: str(item[0]))
            }
        return payload
