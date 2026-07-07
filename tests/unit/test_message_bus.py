"""Unit tests for the MessageBus module."""

from __future__ import annotations

import asyncio

import pytest

from src.agents.message_bus import MessageBus
from src.models import AgentMessage, MessageType


@pytest.fixture
def bus() -> MessageBus:
    return MessageBus()


async def echo_handler(msg: AgentMessage) -> AgentMessage:
    """Simple handler that echoes back."""
    return AgentMessage(
        message_type=MessageType.CLASSIFY_RESPONSE,
        sender=msg.recipient,
        recipient=msg.sender,
        payload=msg.payload,
    )


async def slow_handler(msg: AgentMessage) -> AgentMessage:
    """Handler that takes too long."""
    await asyncio.sleep(5)
    return AgentMessage(
        message_type=MessageType.CLASSIFY_RESPONSE,
        sender=msg.recipient,
        recipient=msg.sender,
        payload={},
    )


async def failing_handler(msg: AgentMessage) -> AgentMessage:
    """Handler that raises an exception."""
    raise RuntimeError("Agent crashed")


@pytest.mark.asyncio
async def test_dispatch_success(bus: MessageBus) -> None:
    """Dispatch to a registered agent returns the handler response."""
    bus.register_agent("test_agent", echo_handler)

    msg = AgentMessage(
        message_type=MessageType.CLASSIFY_REQUEST,
        sender="supervisor",
        recipient="test_agent",
        payload={"variant": "BRCA1"},
    )

    response = await bus.dispatch(msg)
    assert response.message_type == MessageType.CLASSIFY_RESPONSE
    assert response.sender == "test_agent"
    assert response.recipient == "supervisor"
    assert response.payload == {"variant": "BRCA1"}


@pytest.mark.asyncio
async def test_dispatch_unknown_recipient(bus: MessageBus) -> None:
    """Dispatch to an unregistered agent returns ERROR."""
    msg = AgentMessage(
        message_type=MessageType.CLASSIFY_REQUEST,
        sender="supervisor",
        recipient="nonexistent_agent",
        payload={},
    )

    response = await bus.dispatch(msg)
    assert response.message_type == MessageType.ERROR
    assert response.sender == "message_bus"
    assert response.recipient == "supervisor"
    assert "unknown recipient" in response.payload["error"]


@pytest.mark.asyncio
async def test_dispatch_timeout(bus: MessageBus) -> None:
    """Dispatch with a short timeout returns ERROR on timeout."""
    bus.register_agent("slow_agent", slow_handler)

    msg = AgentMessage(
        message_type=MessageType.CLASSIFY_REQUEST,
        sender="supervisor",
        recipient="slow_agent",
        payload={},
    )

    response = await bus.dispatch(msg, timeout=0.1)
    assert response.message_type == MessageType.ERROR
    assert response.sender == "message_bus"
    assert response.recipient == "supervisor"
    assert response.payload["error"] == "timeout"


@pytest.mark.asyncio
async def test_dispatch_handler_exception(bus: MessageBus) -> None:
    """Dispatch to a handler that raises returns ERROR with exception detail."""
    bus.register_agent("failing_agent", failing_handler)

    msg = AgentMessage(
        message_type=MessageType.CLASSIFY_REQUEST,
        sender="supervisor",
        recipient="failing_agent",
        payload={},
    )

    response = await bus.dispatch(msg)
    assert response.message_type == MessageType.ERROR
    assert "Agent crashed" in response.payload["error"]


@pytest.mark.asyncio
async def test_dispatch_concurrent_success(bus: MessageBus) -> None:
    """Concurrent dispatch to multiple agents returns responses in order."""
    bus.register_agent("agent_a", echo_handler)
    bus.register_agent("agent_b", echo_handler)

    messages = [
        AgentMessage(
            message_type=MessageType.CLASSIFY_REQUEST,
            sender="supervisor",
            recipient="agent_a",
            payload={"index": 0},
        ),
        AgentMessage(
            message_type=MessageType.CLASSIFY_REQUEST,
            sender="supervisor",
            recipient="agent_b",
            payload={"index": 1},
        ),
    ]

    responses = await bus.dispatch_concurrent(messages, timeout=5.0)
    assert len(responses) == 2
    assert responses[0].payload == {"index": 0}
    assert responses[1].payload == {"index": 1}
    assert all(r.message_type == MessageType.CLASSIFY_RESPONSE for r in responses)


@pytest.mark.asyncio
async def test_dispatch_concurrent_partial_failure(bus: MessageBus) -> None:
    """Concurrent dispatch handles partial failures gracefully."""
    bus.register_agent("good_agent", echo_handler)
    # "bad_agent" not registered — will produce an ERROR

    messages = [
        AgentMessage(
            message_type=MessageType.CLASSIFY_REQUEST,
            sender="supervisor",
            recipient="good_agent",
            payload={"data": "ok"},
        ),
        AgentMessage(
            message_type=MessageType.CLASSIFY_REQUEST,
            sender="supervisor",
            recipient="bad_agent",
            payload={},
        ),
    ]

    responses = await bus.dispatch_concurrent(messages, timeout=5.0)
    assert len(responses) == 2
    assert responses[0].message_type == MessageType.CLASSIFY_RESPONSE
    assert responses[1].message_type == MessageType.ERROR
    assert "unknown recipient" in responses[1].payload["error"]
