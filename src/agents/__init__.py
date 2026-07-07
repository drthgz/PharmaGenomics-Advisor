"""Agent communication module for inter-agent message passing."""

from src.agents.handlers import brca_handler, egfr_handler, tp53_handler
from src.agents.message_bus import MessageBus
from src.agents.supervisor import SupervisorAgent

__all__ = [
    "MessageBus",
    "SupervisorAgent",
    "brca_handler",
    "egfr_handler",
    "tp53_handler",
]
