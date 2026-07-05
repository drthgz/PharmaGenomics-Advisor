"""Append-only audit logging for agent invocations.

Records every agent call with ISO 8601 timestamps and SHA-256 hashes
of inputs/outputs for compliance and traceability.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from src.models import AuditRecord


class AuditLogger:
    """Immutable, append-only audit logger.

    Each log entry contains:
    - ISO 8601 timestamp (UTC)
    - Agent name
    - Action type (classify, recommend, retrieve, etc.)
    - SHA-256 hash of input
    - SHA-256 hash of output

    Usage:
        logger = AuditLogger("audit.log")
        logger.log("BRCA_Agent", "classify", input_text, output_text)
    """

    def __init__(self, log_path: str = "audit.log"):
        self.log_path = Path(log_path)

    def log(
        self,
        agent_name: str,
        action_type: str,
        input_data: str,
        output_data: str,
    ) -> AuditRecord:
        """Append an audit record to the log file.

        Args:
            agent_name: Name of the agent that was invoked.
            action_type: Type of action performed (e.g., "classify", "recommend").
            input_data: Raw input string (will be hashed, not stored).
            output_data: Raw output string (will be hashed, not stored).

        Returns:
            The created AuditRecord.
        """
        record = AuditRecord(
            timestamp=datetime.now(timezone.utc),
            agent_name=agent_name,
            action_type=action_type,
            input_hash=self._hash(input_data),
            output_hash=self._hash(output_data),
        )

        # Append to log file (create if doesn't exist)
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(record.model_dump_json() + "\n")

        return record

    @staticmethod
    def _hash(data: str) -> str:
        """Compute SHA-256 hex digest of input string."""
        return hashlib.sha256(data.encode("utf-8")).hexdigest()

    def read_log(self) -> list[AuditRecord]:
        """Read all audit records from the log file (for testing/review)."""
        records = []
        if not self.log_path.exists():
            return records

        with open(self.log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(AuditRecord.model_validate_json(line))

        return records
