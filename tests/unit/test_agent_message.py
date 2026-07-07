"""Unit tests for AgentMessage model validation and MessageType enum.

Validates: Requirements 3.2, 3.4
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from src.models import AgentMessage, MessageType


class TestMessageTypeEnum:
    """Tests for the MessageType enum values."""

    def test_classify_request_value(self) -> None:
        """MessageType.CLASSIFY_REQUEST has correct string value."""
        assert MessageType.CLASSIFY_REQUEST == "CLASSIFY_REQUEST"
        assert MessageType.CLASSIFY_REQUEST.value == "CLASSIFY_REQUEST"

    def test_classify_response_value(self) -> None:
        """MessageType.CLASSIFY_RESPONSE has correct string value."""
        assert MessageType.CLASSIFY_RESPONSE == "CLASSIFY_RESPONSE"
        assert MessageType.CLASSIFY_RESPONSE.value == "CLASSIFY_RESPONSE"

    def test_error_value(self) -> None:
        """MessageType.ERROR has correct string value."""
        assert MessageType.ERROR == "ERROR"
        assert MessageType.ERROR.value == "ERROR"

    def test_all_enum_members(self) -> None:
        """MessageType has exactly three members."""
        members = list(MessageType)
        assert len(members) == 3
        assert set(members) == {
            MessageType.CLASSIFY_REQUEST,
            MessageType.CLASSIFY_RESPONSE,
            MessageType.ERROR,
        }


class TestAgentMessageValidation:
    """Tests for AgentMessage Pydantic model validation."""

    def test_valid_message_creation(self) -> None:
        """A valid AgentMessage can be created with required fields."""
        msg = AgentMessage(
            message_type=MessageType.CLASSIFY_REQUEST,
            sender="supervisor",
            recipient="brca_agent",
        )
        assert msg.message_type == MessageType.CLASSIFY_REQUEST
        assert msg.sender == "supervisor"
        assert msg.recipient == "brca_agent"

    def test_payload_defaults_to_empty_dict(self) -> None:
        """Payload field defaults to an empty dict if not provided."""
        msg = AgentMessage(
            message_type=MessageType.CLASSIFY_REQUEST,
            sender="supervisor",
            recipient="brca_agent",
        )
        assert msg.payload == {}

    def test_timestamp_defaults_to_utc_now(self) -> None:
        """Timestamp field defaults to approximately UTC now."""
        before = datetime.now(timezone.utc)
        msg = AgentMessage(
            message_type=MessageType.CLASSIFY_REQUEST,
            sender="supervisor",
            recipient="brca_agent",
        )
        after = datetime.now(timezone.utc)

        assert msg.timestamp >= before
        assert msg.timestamp <= after
        # Verify timezone is UTC
        assert msg.timestamp.tzinfo is not None

    def test_custom_payload_and_timestamp(self) -> None:
        """Custom payload and timestamp are preserved."""
        custom_ts = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        msg = AgentMessage(
            message_type=MessageType.CLASSIFY_RESPONSE,
            sender="brca_agent",
            recipient="supervisor",
            payload={"classification": {"gene": "BRCA1"}},
            timestamp=custom_ts,
        )
        assert msg.payload == {"classification": {"gene": "BRCA1"}}
        assert msg.timestamp == custom_ts

    def test_missing_message_type_raises_validation_error(self) -> None:
        """Missing message_type raises a ValidationError."""
        with pytest.raises(ValidationError):
            AgentMessage(
                sender="supervisor",
                recipient="brca_agent",
            )  # type: ignore[call-arg]

    def test_missing_sender_raises_validation_error(self) -> None:
        """Missing sender raises a ValidationError."""
        with pytest.raises(ValidationError):
            AgentMessage(
                message_type=MessageType.CLASSIFY_REQUEST,
                recipient="brca_agent",
            )  # type: ignore[call-arg]

    def test_missing_recipient_raises_validation_error(self) -> None:
        """Missing recipient raises a ValidationError."""
        with pytest.raises(ValidationError):
            AgentMessage(
                message_type=MessageType.CLASSIFY_REQUEST,
                sender="supervisor",
            )  # type: ignore[call-arg]

    def test_invalid_message_type_raises_validation_error(self) -> None:
        """An invalid message_type value raises a ValidationError."""
        with pytest.raises(ValidationError):
            AgentMessage(
                message_type="INVALID_TYPE",  # type: ignore[arg-type]
                sender="supervisor",
                recipient="brca_agent",
            )
