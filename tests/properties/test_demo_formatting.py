"""Property-based tests for demo script agent event formatting.

Tests validate that:
- Property 1: Agent event log formatting contains required fields (Requirements 4.1, 4.2, 4.3, 4.4)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

# Ensure the project root and scripts directory are importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from scripts.demo import format_agent_event, PREFIX_AGENT


# ─── Strategies ──────────────────────────────────────────────────────────────

# Generate valid message_type strings (non-empty, printable, no whitespace)
_message_types = st.text(
    min_size=1,
    max_size=50,
    alphabet=st.characters(
        whitelist_categories=("Lu", "Ll", "Nd"),
        whitelist_characters="_",
    ),
)

# Generate valid sender names (non-empty, printable, no whitespace)
_sender_names = st.text(
    min_size=1,
    max_size=50,
    alphabet=st.characters(
        whitelist_categories=("Lu", "Ll", "Nd"),
        whitelist_characters="_",
    ),
)

# Generate valid recipient names (non-empty, printable, no whitespace)
_recipient_names = st.text(
    min_size=1,
    max_size=50,
    alphabet=st.characters(
        whitelist_categories=("Lu", "Ll", "Nd"),
        whitelist_characters="_",
    ),
)


# ─── Property Tests ──────────────────────────────────────────────────────────


class TestAgentEventLogFormattingContainsRequiredFields:
    """**Validates: Requirements 4.1, 4.2, 4.3, 4.4**

    For any AgentMessage with a valid message_type, sender, and recipient,
    formatting it as a demo log line SHALL produce a string that contains the
    message_type value, the sender name, and the recipient name, preceded by
    a visual emoji prefix.
    """

    @pytest.mark.property
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        message_type=_message_types,
        sender=_sender_names,
        recipient=_recipient_names,
    )
    def test_formatted_line_contains_message_type(self, message_type, sender, recipient):
        """The formatted agent event line contains the message_type value."""
        result = format_agent_event(message_type, sender, recipient)
        assert message_type in result

    @pytest.mark.property
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        message_type=_message_types,
        sender=_sender_names,
        recipient=_recipient_names,
    )
    def test_formatted_line_contains_sender(self, message_type, sender, recipient):
        """The formatted agent event line contains the sender name."""
        result = format_agent_event(message_type, sender, recipient)
        assert sender in result

    @pytest.mark.property
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        message_type=_message_types,
        sender=_sender_names,
        recipient=_recipient_names,
    )
    def test_formatted_line_contains_recipient(self, message_type, sender, recipient):
        """The formatted agent event line contains the recipient name."""
        result = format_agent_event(message_type, sender, recipient)
        assert recipient in result

    @pytest.mark.property
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        message_type=_message_types,
        sender=_sender_names,
        recipient=_recipient_names,
    )
    def test_formatted_line_starts_with_emoji_prefix(self, message_type, sender, recipient):
        """The formatted agent event line starts with the emoji prefix."""
        result = format_agent_event(message_type, sender, recipient)
        assert result.startswith(PREFIX_AGENT)
