"""In-process async message router for agent communication.

Provides typed message-passing between the supervisor and specialist agents
with timeout handling, structured audit logging, and concurrent dispatch.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from src.models import AgentMessage, MessageType

logger = logging.getLogger(__name__)


class MessageBus:
    """In-process async message router for agent communication.

    Agents register handlers by name. The bus dispatches AgentMessages to
    the named recipient's handler and returns the response. Timeouts and
    unknown recipients produce ERROR-type messages.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, Callable[[AgentMessage], Awaitable[AgentMessage]]] = {}

    def register_agent(
        self, name: str, handler: Callable[[AgentMessage], Awaitable[AgentMessage]]
    ) -> None:
        """Register an agent handler under the given name.

        Args:
            name: Unique agent name used as the message recipient field.
            handler: Async callable that receives an AgentMessage and returns one.
        """
        self._handlers[name] = handler
        logger.info("Registered agent: %s", name)

    async def dispatch(
        self, message: AgentMessage, timeout: float = 60.0
    ) -> AgentMessage:
        """Dispatch a message to its recipient and return the response.

        Args:
            message: The AgentMessage to route.
            timeout: Maximum seconds to wait for the handler (default 60s).

        Returns:
            The response AgentMessage from the handler, or an ERROR AgentMessage
            on timeout or unknown recipient.
        """
        # Audit log: dispatch
        logger.info(
            "Dispatching message: message_type=%s sender=%s recipient=%s timestamp=%s",
            message.message_type.value,
            message.sender,
            message.recipient,
            message.timestamp.isoformat(),
        )

        # Check if recipient is registered
        handler = self._handlers.get(message.recipient)
        if handler is None:
            logger.warning(
                "Unknown recipient: %s (sender=%s, message_type=%s)",
                message.recipient,
                message.sender,
                message.message_type.value,
            )
            return AgentMessage(
                message_type=MessageType.ERROR,
                sender="message_bus",
                recipient=message.sender,
                payload={"error": f"unknown recipient: {message.recipient}"},
                timestamp=datetime.now(timezone.utc),
            )

        # Dispatch with timeout
        try:
            response = await asyncio.wait_for(handler(message), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(
                "Timeout dispatching to %s after %.1fs (sender=%s, message_type=%s)",
                message.recipient,
                timeout,
                message.sender,
                message.message_type.value,
            )
            return AgentMessage(
                message_type=MessageType.ERROR,
                sender="message_bus",
                recipient=message.sender,
                payload={"error": "timeout"},
                timestamp=datetime.now(timezone.utc),
            )
        except Exception as exc:
            logger.warning(
                "Handler exception for %s: %s (sender=%s, message_type=%s)",
                message.recipient,
                str(exc),
                message.sender,
                message.message_type.value,
            )
            return AgentMessage(
                message_type=MessageType.ERROR,
                sender="message_bus",
                recipient=message.sender,
                payload={"error": str(exc)},
                timestamp=datetime.now(timezone.utc),
            )

        # Audit log: response received
        logger.info(
            "Response received: message_type=%s sender=%s recipient=%s timestamp=%s",
            response.message_type.value,
            response.sender,
            response.recipient,
            response.timestamp.isoformat(),
        )

        return response

    async def dispatch_concurrent(
        self, messages: list[AgentMessage], timeout: float = 60.0
    ) -> list[AgentMessage]:
        """Dispatch multiple messages concurrently and collect responses.

        Uses asyncio.gather with return_exceptions=True to handle partial
        failures gracefully. Each failed dispatch returns an ERROR AgentMessage.

        Args:
            messages: List of AgentMessages to dispatch in parallel.
            timeout: Maximum seconds to wait for each handler (default 60s).

        Returns:
            List of response AgentMessages in the same order as the input messages.
        """
        tasks = [self.dispatch(msg, timeout=timeout) for msg in messages]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        responses: list[AgentMessage] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                # Should not normally reach here since dispatch() catches exceptions,
                # but handle defensively.
                logger.warning(
                    "Unexpected exception in concurrent dispatch for message %d: %s",
                    i,
                    str(result),
                )
                responses.append(
                    AgentMessage(
                        message_type=MessageType.ERROR,
                        sender="message_bus",
                        recipient=messages[i].sender,
                        payload={"error": str(result)},
                        timestamp=datetime.now(timezone.utc),
                    )
                )
            else:
                responses.append(result)

        return responses
