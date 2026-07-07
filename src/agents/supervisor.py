"""Supervisor Agent Runtime for delegating variant classification to specialists.

Receives variant analysis requests, routes to specialist agents via the message bus,
aggregates results preserving input order, and generates clinical narratives via LLM.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from src.agents.message_bus import MessageBus
from src.inference.ollama_client import LLMInferenceClient
from src.models import (
    AgentMessage,
    MessageType,
    Variant,
    VariantClassification,
)
from src.pipeline.orchestrator import (
    _rule_based_acmg,
    _variant_description,
)

logger = logging.getLogger(__name__)

# Routing map: gene name → specialist agent name
GENE_AGENT_ROUTING: dict[str, str] = {
    "BRCA1": "brca_agent",
    "BRCA2": "brca_agent",
    "EGFR": "egfr_agent",
    "TP53": "tp53_agent",
}

# Set of supported genes for quick lookup
SUPPORTED_GENES: set[str] = set(GENE_AGENT_ROUTING.keys())


class SupervisorAgent:
    """Runtime supervisor that delegates to specialist agents with real message-passing.

    Routes variants to gene-specific specialist agents via the MessageBus,
    falls back to rule-based classification on errors/timeouts, and generates
    clinical narratives via the LLM inference client.
    """

    def __init__(
        self,
        bus: MessageBus,
        llm_client: LLMInferenceClient,
        audit_logger: object | None = None,
    ) -> None:
        """Initialize the supervisor agent.

        Args:
            bus: MessageBus instance with specialist agents already registered.
            llm_client: LLMInferenceClient for generating clinical narratives.
            audit_logger: Any object with a log method, or None (uses Python logging).
        """
        self.bus = bus
        self.llm_client = llm_client
        self.audit_logger = audit_logger

    async def analyze_variants(
        self, variants: list[Variant]
    ) -> list[VariantClassification]:
        """Analyze a list of variants by routing to specialist agents.

        1. Filter to supported genes only (skip unsupported)
        2. Construct AgentMessages for each supported variant
        3. Dispatch concurrently via MessageBus
        4. On timeout/error: fall back to rule-based classification
        5. Generate clinical narrative via LLMInferenceClient for each classification
        6. Return classifications in original variant order

        Args:
            variants: List of Variant objects to classify.

        Returns:
            List of VariantClassification objects in the same order as input variants,
            excluding variants with unsupported genes.
        """
        self._log_audit("analyze_variants_start", f"Processing {len(variants)} variants")

        # Build (original_index, variant, agent_name) tuples for supported variants
        routable: list[tuple[int, Variant, str]] = []
        for idx, variant in enumerate(variants):
            gene = variant.gene
            if gene and gene in SUPPORTED_GENES:
                agent_name = GENE_AGENT_ROUTING[gene]
                routable.append((idx, variant, agent_name))
            else:
                logger.debug(
                    "Skipping variant at index %d: gene=%s not in supported set",
                    idx,
                    gene,
                )

        if not routable:
            self._log_audit("analyze_variants_end", "No routable variants found")
            return []

        # Construct AgentMessages for dispatch
        messages: list[AgentMessage] = []
        for _, variant, agent_name in routable:
            msg = AgentMessage(
                message_type=MessageType.CLASSIFY_REQUEST,
                sender="supervisor",
                recipient=agent_name,
                payload={"variant": variant.model_dump(mode="json")},
                timestamp=datetime.now(timezone.utc),
            )
            messages.append(msg)

        # Dispatch concurrently via message bus
        responses = await self.bus.dispatch_concurrent(messages)

        # Process responses and build classifications, preserving order
        classifications: list[VariantClassification] = []
        for i, (orig_idx, variant, agent_name) in enumerate(routable):
            response = responses[i]
            classification = self._process_response(response, variant)
            classifications.append(classification)

        # Generate clinical narratives for each classification
        for classification in classifications:
            narrative = self.llm_client.generate_narrative(classification)
            if narrative:
                classification.clinical_narrative = narrative

        self._log_audit(
            "analyze_variants_end",
            f"Completed {len(classifications)} classifications",
        )

        return classifications

    def _process_response(
        self, response: AgentMessage, variant: Variant
    ) -> VariantClassification:
        """Process a specialist agent response, falling back on error.

        Args:
            response: The AgentMessage response from the specialist (or error).
            variant: The original variant for fallback classification.

        Returns:
            VariantClassification from the specialist or from rule-based fallback.
        """
        if response.message_type == MessageType.CLASSIFY_RESPONSE:
            # Successfully received classification from specialist
            try:
                classification_data = response.payload.get("classification", {})
                return VariantClassification(**classification_data)
            except Exception as exc:
                logger.warning(
                    "Failed to parse specialist response for %s: %s. Falling back.",
                    variant.gene,
                    str(exc),
                )
                return self._fallback_classification(variant)
        else:
            # ERROR or unexpected message type — fall back to rule-based
            error_detail = response.payload.get("error", "unknown error")
            logger.warning(
                "Specialist agent error for %s: %s. Using rule-based fallback.",
                variant.gene,
                error_detail,
            )
            return self._fallback_classification(variant)

    def _fallback_classification(self, variant: Variant) -> VariantClassification:
        """Generate a rule-based classification as fallback.

        Uses the existing _rule_based_acmg function from the orchestrator.

        Args:
            variant: The variant to classify.

        Returns:
            VariantClassification with rule-based results.
        """
        classification, confidence = _rule_based_acmg(variant)
        return VariantClassification(
            gene=variant.gene or "Unknown",
            variant_description=_variant_description(variant),
            chromosome=variant.chromosome,
            position=variant.position,
            ref_allele=variant.ref_allele,
            alt_allele=variant.alt_allele,
            classification=classification,
            confidence=confidence,
            evidence_references=["Rule-based fallback assessment"],
            data_sources_queried=["local_rules"],
            limitations=["Specialist agent unavailable; used rule-based fallback"],
        )

    def _log_audit(self, action: str, detail: str) -> None:
        """Log an audit entry via the audit_logger or standard logging."""
        if self.audit_logger and hasattr(self.audit_logger, "log"):
            self.audit_logger.log(action, detail)  # type: ignore[union-attr]
        else:
            logger.info("Audit [supervisor] %s: %s", action, detail)
