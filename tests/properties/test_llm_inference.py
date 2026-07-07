"""Property-based tests for the LLM Inference Client.

Tests validate that:
- Property 1: Prompt validation guards LLM calls (Requirement 1.2)
- Property 2: Narrative truncation bound (Requirement 1.3)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from src.inference.ollama_client import LLMInferenceClient
from src.models import (
    ACMGClassification,
    TherapeuticRelevance,
    VariantClassification,
)


# ─── Strategies ──────────────────────────────────────────────────────────────

# Strategy for a valid VariantClassification with all required fields present
_acmg_values = st.sampled_from(list(ACMGClassification))
_therapeutic_values = st.sampled_from(list(TherapeuticRelevance))
_non_empty_strings = st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=("L", "N")))
_evidence_lists = st.lists(_non_empty_strings, min_size=1, max_size=5)


def _variant_classification_with_missing_fields():
    """Strategy that generates VariantClassification objects with at least one
    required field missing or empty (gene, classification, evidence_references,
    therapeutic_relevance).
    """
    # We generate each field as either valid or invalid, ensuring at least one is invalid
    return st.builds(
        _build_classification_missing_field,
        gene=st.one_of(st.just(""), st.just(None), _non_empty_strings),
        classification=st.one_of(st.just(None), _acmg_values),
        evidence_references=st.one_of(st.just([]), _evidence_lists),
        therapeutic_relevance=st.one_of(st.just(None), _therapeutic_values),
    ).filter(_has_at_least_one_missing_field)


def _build_classification_missing_field(
    gene, classification, evidence_references, therapeutic_relevance
):
    """Build a VariantClassification with potentially missing fields."""
    return VariantClassification(
        gene=gene or "",
        variant_description="Test variant",
        chromosome="chr17",
        position=41245466,
        ref_allele="A",
        alt_allele="T",
        classification=classification,
        evidence_references=evidence_references,
        therapeutic_relevance=therapeutic_relevance,
    )


def _has_at_least_one_missing_field(vc: VariantClassification) -> bool:
    """Return True if at least one of the four required fields is missing/empty."""
    if not vc.gene:
        return True
    if not vc.classification:
        return True
    if not vc.evidence_references:
        return True
    if not vc.therapeutic_relevance:
        return True
    return False


# Strategy for valid classifications (all fields present)
def _valid_variant_classification():
    """Strategy that generates VariantClassification objects with all required fields."""
    return st.builds(
        lambda gene, classification, evidence_references, therapeutic_relevance: VariantClassification(
            gene=gene,
            variant_description="Test variant",
            chromosome="chr17",
            position=41245466,
            ref_allele="A",
            alt_allele="T",
            classification=classification,
            evidence_references=evidence_references,
            therapeutic_relevance=therapeutic_relevance,
        ),
        gene=_non_empty_strings,
        classification=_acmg_values,
        evidence_references=_evidence_lists,
        therapeutic_relevance=_therapeutic_values,
    )


# ─── Property Tests ──────────────────────────────────────────────────────────


# Feature: project-completion-fixes, Property 1: Prompt validation guards LLM calls
class TestPromptValidationGuardsLLMCalls:
    """**Validates: Requirements 1.2**

    For any VariantClassification object, if any of the four required fields
    (gene, classification, evidence_references, therapeutic_relevance) is missing
    or empty, then generate_narrative() SHALL NOT invoke ollama.chat().
    """

    @pytest.mark.property
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(data=st.data())
    def test_ollama_not_called_when_fields_missing(self, data):
        """Ollama.chat() must never be called when required fields are missing."""
        classification = data.draw(_variant_classification_with_missing_fields())

        with patch("src.inference.ollama_client.ollama.Client") as mock_client_cls:
            mock_client_instance = MagicMock()
            mock_client_cls.return_value = mock_client_instance

            client = LLMInferenceClient(model="test-model", timeout=5.0)

            result = client.generate_narrative(classification)

            # ollama.chat() must NOT be called
            mock_client_instance.chat.assert_not_called()

            # Should return empty string (no LLM call made)
            assert result == ""


# Feature: project-completion-fixes, Property 2: Narrative truncation bound
class TestNarrativeTruncationBound:
    """**Validates: Requirements 1.3**

    For any non-empty string returned by Ollama (of any length from 1 to
    arbitrarily large), generate_narrative() SHALL return a string of at most
    2000 characters.
    """

    @pytest.mark.property
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        classification=_valid_variant_classification(),
        response_text=st.text(min_size=1, max_size=10000),
    )
    def test_output_never_exceeds_2000_chars(self, classification, response_text):
        """Output of generate_narrative must always be ≤ 2000 characters."""
        with patch("src.inference.ollama_client.ollama.Client") as mock_client_cls:
            mock_client_instance = MagicMock()
            mock_client_cls.return_value = mock_client_instance

            # Mock the chat method to return our random response
            mock_client_instance.chat.return_value = {
                "message": {"content": response_text}
            }

            client = LLMInferenceClient(model="test-model", timeout=5.0)

            result = client.generate_narrative(classification)

            # Output must never exceed 2000 characters
            assert len(result) <= 2000
