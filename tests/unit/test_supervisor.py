"""Unit tests for the SupervisorAgent module.

Tests timeout fallback to rule-based classification, concurrent dispatch
behavior with multiple variants, and unsupported gene skipping.

Validates: Requirements 3.2, 3.4, 3.7
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from src.agents.message_bus import MessageBus
from src.agents.supervisor import SupervisorAgent, GENE_AGENT_ROUTING
from src.inference.ollama_client import LLMInferenceClient
from src.models import (
    AgentMessage,
    MessageType,
    Variant,
    VariantClassification,
)


def _make_variant(gene: str, position: int = 100) -> Variant:
    """Create a test Variant with the given gene."""
    return Variant(
        chromosome="chr17",
        position=position,
        ref_allele="A",
        alt_allele="T",
        gene=gene,
    )


async def _slow_handler(msg: AgentMessage) -> AgentMessage:
    """A handler that sleeps longer than the timeout to trigger fallback."""
    await asyncio.sleep(10)
    return AgentMessage(
        message_type=MessageType.CLASSIFY_RESPONSE,
        sender=msg.recipient,
        recipient=msg.sender,
        payload={},
    )


async def _fast_handler(msg: AgentMessage) -> AgentMessage:
    """A handler that quickly returns a valid classification response."""
    variant_data = msg.payload.get("variant", {})
    gene = variant_data.get("gene", "UNKNOWN")
    classification_data = VariantClassification(
        gene=gene,
        variant_description=f"{gene} test variant",
        chromosome=variant_data.get("chromosome", "chr1"),
        position=variant_data.get("position", 1),
        ref_allele=variant_data.get("ref_allele", "A"),
        alt_allele=variant_data.get("alt_allele", "T"),
        classification="Pathogenic",
        confidence="High",
        evidence_references=["Test evidence"],
        data_sources_queried=["test_source"],
    )
    return AgentMessage(
        message_type=MessageType.CLASSIFY_RESPONSE,
        sender=msg.recipient,
        recipient=msg.sender,
        payload={"classification": classification_data.model_dump(mode="json")},
    )


@pytest.mark.asyncio
async def test_timeout_fallback_to_rule_based() -> None:
    """When a specialist agent times out, supervisor falls back to rule-based classification.

    Validates: Requirement 3.7
    """
    bus = MessageBus()
    # Register a slow handler that will time out
    bus.register_agent("brca_agent", _slow_handler)

    # Mock LLMInferenceClient.generate_narrative to avoid Ollama dependency
    with patch.object(LLMInferenceClient, "generate_narrative", return_value=""):
        llm_client = LLMInferenceClient.__new__(LLMInferenceClient)
        llm_client.model = "medgemma"
        llm_client.timeout = 30.0

        supervisor = SupervisorAgent(bus=bus, llm_client=llm_client)

        variant = _make_variant("BRCA1")
        # Use a very short timeout to trigger the fallback quickly
        # We patch dispatch_concurrent to use a short timeout
        original_dispatch_concurrent = bus.dispatch_concurrent

        async def short_timeout_dispatch(messages, timeout=60.0):
            return await original_dispatch_concurrent(messages, timeout=0.1)

        bus.dispatch_concurrent = short_timeout_dispatch  # type: ignore[assignment]

        results = await supervisor.analyze_variants([variant])

    # Should still get a result via rule-based fallback
    assert len(results) == 1
    result = results[0]
    assert result.gene == "BRCA1"
    # Rule-based fallback should provide a classification
    assert result.classification is not None
    # Should have fallback limitation note
    assert any("fallback" in lim.lower() for lim in result.limitations)


@pytest.mark.asyncio
async def test_concurrent_dispatch_multiple_variants() -> None:
    """Multiple variants for different genes are dispatched concurrently and all return results.

    Validates: Requirement 3.2
    """
    bus = MessageBus()
    # Register fast handlers for all supported genes
    bus.register_agent("brca_agent", _fast_handler)
    bus.register_agent("egfr_agent", _fast_handler)
    bus.register_agent("tp53_agent", _fast_handler)

    # Mock LLMInferenceClient.generate_narrative to avoid Ollama dependency
    with patch.object(LLMInferenceClient, "generate_narrative", return_value=""):
        llm_client = LLMInferenceClient.__new__(LLMInferenceClient)
        llm_client.model = "medgemma"
        llm_client.timeout = 30.0

        supervisor = SupervisorAgent(bus=bus, llm_client=llm_client)

        variants = [
            _make_variant("BRCA1", position=100),
            _make_variant("EGFR", position=200),
            _make_variant("TP53", position=300),
        ]

        results = await supervisor.analyze_variants(variants)

    # All 3 variants should produce classifications
    assert len(results) == 3
    # Verify each gene got classified
    genes_in_results = [r.gene for r in results]
    assert "BRCA1" in genes_in_results
    assert "EGFR" in genes_in_results
    assert "TP53" in genes_in_results


@pytest.mark.asyncio
async def test_unsupported_gene_skipped() -> None:
    """Variants with unsupported gene names are skipped and not included in results.

    Validates: Requirement 3.2
    """
    bus = MessageBus()
    bus.register_agent("brca_agent", _fast_handler)

    # Mock LLMInferenceClient.generate_narrative to avoid Ollama dependency
    with patch.object(LLMInferenceClient, "generate_narrative", return_value=""):
        llm_client = LLMInferenceClient.__new__(LLMInferenceClient)
        llm_client.model = "medgemma"
        llm_client.timeout = 30.0

        supervisor = SupervisorAgent(bus=bus, llm_client=llm_client)

        variants = [
            _make_variant("BRCA1", position=100),
            _make_variant("UNKNOWN", position=200),
        ]

        results = await supervisor.analyze_variants(variants)

    # Only BRCA1 should appear; UNKNOWN gene should be skipped
    assert len(results) == 1
    assert results[0].gene == "BRCA1"
