"""Property-based tests for agent routing and order preservation.

Tests validate that:
- Property 4: Gene-based routing correctness (Requirement 3.1)
- Property 5: Order preservation in aggregation (Requirement 3.5)
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from src.agents.message_bus import MessageBus
from src.agents.supervisor import GENE_AGENT_ROUTING, SupervisorAgent
from src.models import (
    ACMGClassification,
    AgentMessage,
    ConfidenceLevel,
    MessageType,
    Variant,
    VariantClassification,
)


# ─── Strategies ──────────────────────────────────────────────────────────────

_supported_genes = st.sampled_from(["BRCA1", "BRCA2", "EGFR", "TP53"])

_chromosomes = st.text(
    min_size=1, max_size=10, alphabet=st.characters(whitelist_categories=("L", "N"))
)
_positions = st.integers(min_value=1, max_value=2_147_483_647)
_alleles = st.text(min_size=1, max_size=10, alphabet=st.sampled_from("ATCGN"))


def _variant_with_supported_gene():
    """Strategy generating Variant objects with a gene in the supported set."""
    return st.builds(
        Variant,
        chromosome=_chromosomes,
        position=_positions,
        ref_allele=_alleles,
        alt_allele=_alleles,
        gene=_supported_genes,
    )


def _variant_list():
    """Strategy generating lists of Variants with supported genes."""
    return st.lists(
        _variant_with_supported_gene(),
        min_size=1,
        max_size=10,
    )


# ─── Property Tests ──────────────────────────────────────────────────────────


# Feature: project-completion-fixes, Property 4: Gene-based routing correctness
class TestGenBasedRoutingCorrectness:
    """**Validates: Requirements 3.1**

    For any Variant with a gene field matching one of {BRCA1, BRCA2, EGFR, TP53},
    the SupervisorAgent SHALL construct an AgentMessage with recipient equal to the
    correct specialist agent name (brca_agent for BRCA1/BRCA2, egfr_agent for EGFR,
    tp53_agent for TP53).
    """

    @pytest.mark.property
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(variant=_variant_with_supported_gene())
    def test_routing_maps_gene_to_correct_agent(self, variant):
        """The GENE_AGENT_ROUTING constant maps each supported gene to the correct agent."""
        gene = variant.gene
        expected_agent = GENE_AGENT_ROUTING[gene]

        # Verify the routing map provides the correct specialist agent
        if gene in ("BRCA1", "BRCA2"):
            assert expected_agent == "brca_agent"
        elif gene == "EGFR":
            assert expected_agent == "egfr_agent"
        elif gene == "TP53":
            assert expected_agent == "tp53_agent"

    @pytest.mark.property
    @pytest.mark.asyncio
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(variant=_variant_with_supported_gene())
    async def test_supervisor_constructs_message_with_correct_recipient(self, variant):
        """SupervisorAgent dispatches AgentMessage with recipient matching the routing map."""
        expected_agent = GENE_AGENT_ROUTING[variant.gene]

        # Mock the bus to capture dispatched messages
        mock_bus = MagicMock(spec=MessageBus)

        # Build a valid classification response for the mock
        classification_response = VariantClassification(
            gene=variant.gene,
            variant_description=f"{variant.chromosome}:{variant.position}",
            chromosome=variant.chromosome,
            position=variant.position,
            ref_allele=variant.ref_allele,
            alt_allele=variant.alt_allele,
            classification=ACMGClassification.VUS,
            confidence=ConfidenceLevel.MODERATE,
            evidence_references=["test"],
            data_sources_queried=["local_rules"],
        )

        response_msg = AgentMessage(
            message_type=MessageType.CLASSIFY_RESPONSE,
            sender=expected_agent,
            recipient="supervisor",
            payload={"classification": classification_response.model_dump(mode="json")},
            timestamp=datetime.now(timezone.utc),
        )

        mock_bus.dispatch_concurrent = AsyncMock(return_value=[response_msg])

        # Mock LLM client
        mock_llm = MagicMock()
        mock_llm.generate_narrative = MagicMock(return_value="")

        supervisor = SupervisorAgent(bus=mock_bus, llm_client=mock_llm)
        await supervisor.analyze_variants([variant])

        # Verify dispatch_concurrent was called
        mock_bus.dispatch_concurrent.assert_called_once()
        dispatched_messages = mock_bus.dispatch_concurrent.call_args[0][0]

        # There should be exactly one message dispatched
        assert len(dispatched_messages) == 1
        msg = dispatched_messages[0]

        # The recipient must match the expected agent from GENE_AGENT_ROUTING
        assert msg.recipient == expected_agent
        assert msg.message_type == MessageType.CLASSIFY_REQUEST
        assert msg.sender == "supervisor"


# Feature: project-completion-fixes, Property 5: Order preservation in aggregation
class TestOrderPreservationInAggregation:
    """**Validates: Requirements 3.5**

    For any list of variants processed by the SupervisorAgent, the returned list
    of VariantClassification objects SHALL maintain the same ordering as the input
    variant list (matched by chromosome, position, ref_allele, alt_allele).
    """

    @pytest.mark.property
    @pytest.mark.asyncio
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(variants=_variant_list())
    async def test_output_order_matches_input_order(self, variants):
        """Output classifications preserve input variant order."""
        # Build mock responses in same order as the routable variants
        mock_responses = []
        for variant in variants:
            agent_name = GENE_AGENT_ROUTING[variant.gene]
            classification = VariantClassification(
                gene=variant.gene,
                variant_description=f"{variant.chromosome}:{variant.position}",
                chromosome=variant.chromosome,
                position=variant.position,
                ref_allele=variant.ref_allele,
                alt_allele=variant.alt_allele,
                classification=ACMGClassification.VUS,
                confidence=ConfidenceLevel.MODERATE,
                evidence_references=["test"],
                data_sources_queried=["local_rules"],
            )
            response_msg = AgentMessage(
                message_type=MessageType.CLASSIFY_RESPONSE,
                sender=agent_name,
                recipient="supervisor",
                payload={"classification": classification.model_dump(mode="json")},
                timestamp=datetime.now(timezone.utc),
            )
            mock_responses.append(response_msg)

        # Mock bus to return responses in same order
        mock_bus = MagicMock(spec=MessageBus)
        mock_bus.dispatch_concurrent = AsyncMock(return_value=mock_responses)

        # Mock LLM client
        mock_llm = MagicMock()
        mock_llm.generate_narrative = MagicMock(return_value="")

        supervisor = SupervisorAgent(bus=mock_bus, llm_client=mock_llm)
        results = await supervisor.analyze_variants(variants)

        # The number of results should match the number of input variants
        assert len(results) == len(variants)

        # Verify order is preserved by matching identifying fields
        for i, (result, original_variant) in enumerate(zip(results, variants)):
            assert result.chromosome == original_variant.chromosome, (
                f"Mismatch at index {i}: chromosome {result.chromosome} "
                f"!= {original_variant.chromosome}"
            )
            assert result.position == original_variant.position, (
                f"Mismatch at index {i}: position {result.position} "
                f"!= {original_variant.position}"
            )
            assert result.ref_allele == original_variant.ref_allele, (
                f"Mismatch at index {i}: ref_allele {result.ref_allele} "
                f"!= {original_variant.ref_allele}"
            )
            assert result.alt_allele == original_variant.alt_allele, (
                f"Mismatch at index {i}: alt_allele {result.alt_allele} "
                f"!= {original_variant.alt_allele}"
            )
