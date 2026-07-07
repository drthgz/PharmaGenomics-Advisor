"""Composable security middleware layer.

Chains all security checks in order: size → injection → PHI → rate limit.
Applied to all inputs before they reach any agent or MCP server.
"""

from __future__ import annotations

import os

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
        # InputValidator runs first because rejecting oversized or malicious
        # payloads early avoids wasting cycles on expensive PHI regex scans.
        self.input_validator = InputValidator(max_chars=config.max_input_chars)
        # PHI detection is separate from injection prevention so clinical-use
        # environments can selectively relax PHI rules without weakening
        # injection defenses.
        self.phi_detector = PHIDetector(clinical_use_mode=config.clinical_use_mode)
        # Rate limiter is per-session to prevent a single user from exhausting
        # LLM inference capacity while still allowing concurrent sessions.
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
        # Environment-based config allows Docker deployments to override
        # security thresholds without code changes or rebuilds.
        config = SecurityConfig(
            phi_detection_enabled=True,
            # Clinical-use mode relaxes PHI blocking so that legitimate
            # clinical workflows (e.g., variant reports) aren't rejected.
            clinical_use_mode=os.getenv("PHI_CLINICAL_USE", "false").lower() == "true",
            # Defaults tuned for demo workloads; production would use
            # stricter limits sourced from a secrets manager.
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
        # Chain order matters: cheapest checks first (size/injection), then
        # expensive regex-based PHI scan, then stateful rate-limit lookup.
        # This fail-fast ordering minimizes resource use on malicious inputs.

        # 1. Size limit and injection patterns — rejects prompt-injection
        # attempts and oversized payloads before they reach downstream logic.
        result = self.input_validator.validate(input_data)
        if not result.is_valid:
            self.audit_logger.log(
                agent_name="security_layer",
                action_type="validate_input",
                input_data=input_data,
                output_data=f"rejected:{result.rejected_reason}",
            )
            # Early return prevents wasted PHI/rate-limit processing and
            # ensures the audit trail captures the first failing check only.
            return result

        # 2. PHI detection — uses regex heuristics for SSN, MRN, and name
        # patterns. Runs after injection check so that injection payloads
        # disguised as PHI don't bypass the injection filter.
        result = self.phi_detector.check(input_data)
        if not result.is_valid:
            self.audit_logger.log(
                agent_name="security_layer",
                action_type="detect_phi",
                input_data=input_data,
                output_data=f"rejected:{result.rejected_reason}",
            )
            return result

        # 3. Rate limiting — checked last because it's the only stateful
        # operation (updates a sliding window counter). Skipping it for
        # already-invalid inputs avoids polluting the rate-limit window.
        result = self.rate_limiter.check(session_id)
        if not result.is_valid:
            self.audit_logger.log(
                agent_name="security_layer",
                action_type="rate_limit",
                input_data=input_data,
                output_data=f"rejected:{result.rejected_reason}",
            )
            return result

        self.audit_logger.log(
            agent_name="security_layer",
            action_type="validate_pass",
            input_data=input_data,
            output_data="accepted",
        )

        return ValidationResult(is_valid=True)
