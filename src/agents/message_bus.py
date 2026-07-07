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
        # Use a dict for O(1) handler lookup by agent name — critical for low-latency
        # dispatch when the supervisor fans out to multiple specialists concurrently.
        self._handlers: dict[str, Callable[[AgentMessage], Awaitable[AgentMessage]]] = {}

    def register_agent(
        self, name: str, handler: Callable[[AgentMessage], Awaitable[AgentMessage]]
    ) -> None:
        """Register an agent handler under the given name.

        Args:
            name: Unique agent name used as the message recipient field.
            handler: Async callable that receives an AgentMessage and returns one.
        """
        # Overwrite-on-duplicate is intentional: allows hot-swapping agent handlers
        # during testing or dynamic reconfiguration without needing an unregister step.
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

        # Resolve the recipient's handler first — fail fast before doing any async work.
        # This keeps the error path synchronous and avoids unnecessary task scheduling.
        handler = self._handlers.get(message.recipient)
        if handler is None:
            # Return an ERROR message back to the sender rather than raising an exception,
            # so callers can handle missing recipients uniformly without try/except logic.
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

        # Wrap the handler call with asyncio.wait_for to enforce a hard timeout.
        # Without this, a misbehaving specialist agent could block the entire
        # supervisor's dispatch loop indefinitely.
        try:
            response = await asyncio.wait_for(handler(message), timeout=timeout)
        except asyncio.TimeoutError:
            # Timeout produces a structured ERROR response rather than propagating the
            # exception — this lets dispatch_concurrent collect partial results without
            # aborting the entire fan-out operation.
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
            # Catch-all ensures no handler bug can crash the bus — the bus must remain
            # stable so other concurrent dispatches are unaffected.
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
        # Use asyncio.gather with return_exceptions=True so one failing dispatch
        # doesn't cancel sibling tasks — partial success is better than total failure
        # when the supervisor needs at least some specialist responses to build a report.
        tasks = [self.dispatch(msg, timeout=timeout) for msg in messages]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        responses: list[AgentMessage] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                # Defensive fallback: dispatch() already catches all exceptions internally,
                # but gather() could surface cancellation or event-loop-level errors that
                # bypass the handler try/except. Convert these to ERROR messages to keep
                # the response list length consistent with the input list.
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
