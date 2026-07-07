"""Unit tests for LLM Inference Client edge cases.

Tests fallback behavior on various error conditions, default model selection,
and placeholder narrative formatting.

Requirements: 1.4, 1.7
"""

import logging
import os
from unittest.mock import MagicMock, patch

import pytest

from src.inference.ollama_client import LLMInferenceClient
from src.models import (
    ACMGClassification,
    TherapeuticRelevance,
    VariantClassification,
)


def _make_valid_classification(
    gene: str = "BRCA1",
    classification: ACMGClassification = ACMGClassification.PATHOGENIC,
    evidence_references: list[str] | None = None,
    therapeutic_relevance: TherapeuticRelevance = TherapeuticRelevance.TKI_SENSITIVE,
) -> VariantClassification:
    """Helper to create a VariantClassification with all required fields populated."""
    return VariantClassification(
        gene=gene,
        variant_description="c.5266dupC (p.Gln1756Profs*74)",
        chromosome="chr17",
        position=41276045,
        ref_allele="A",
        alt_allele="T",
        classification=classification,
        evidence_references=evidence_references or ["ClinVar:RCV000013961", "PMID:20104584"],
        therapeutic_relevance=therapeutic_relevance,
    )


class TestFallbackOnConnectionError:
    """Test that ConnectionError triggers placeholder fallback with WARNING log."""

    def test_fallback_on_connection_error(self, caplog):
        """Mock chat to raise ConnectionError → verify placeholder returned and WARNING logged."""
        classification = _make_valid_classification()

        with patch("src.inference.ollama_client.ollama.Client") as mock_client_cls:
            mock_instance = MagicMock()
            mock_instance.chat.side_effect = ConnectionError("Connection refused")
            mock_client_cls.return_value = mock_instance

            client = LLMInferenceClient(model="medgemma")

            with caplog.at_level(logging.WARNING):
                result = client.generate_narrative(classification)

        assert result == "BRCA1 - Pathogenic - LLM-generated narrative unavailable"
        assert any("WARNING" == record.levelname for record in caplog.records)


class TestFallbackOnHTTPError:
    """Test that HTTP-like exceptions trigger placeholder fallback."""

    def test_fallback_on_http_error(self, caplog):
        """Mock chat to raise an HTTP-like exception → verify placeholder."""
        classification = _make_valid_classification()

        with patch("src.inference.ollama_client.ollama.Client") as mock_client_cls:
            mock_instance = MagicMock()
            mock_instance.chat.side_effect = Exception("HTTP 500 Internal Server Error")
            mock_client_cls.return_value = mock_instance

            client = LLMInferenceClient(model="medgemma")

            with caplog.at_level(logging.WARNING):
                result = client.generate_narrative(classification)

        assert result == "BRCA1 - Pathogenic - LLM-generated narrative unavailable"
        assert any("WARNING" == record.levelname for record in caplog.records)


class TestFallbackOnTimeout:
    """Test that TimeoutError triggers placeholder fallback."""

    def test_fallback_on_timeout(self, caplog):
        """Mock chat to raise TimeoutError → verify placeholder."""
        classification = _make_valid_classification()

        with patch("src.inference.ollama_client.ollama.Client") as mock_client_cls:
            mock_instance = MagicMock()
            mock_instance.chat.side_effect = TimeoutError("Request timed out after 30s")
            mock_client_cls.return_value = mock_instance

            client = LLMInferenceClient(model="medgemma")

            with caplog.at_level(logging.WARNING):
                result = client.generate_narrative(classification)

        assert result == "BRCA1 - Pathogenic - LLM-generated narrative unavailable"
        assert any("WARNING" == record.levelname for record in caplog.records)


class TestFallbackOnEmptyResponse:
    """Test that an empty response from Ollama triggers placeholder fallback."""

    def test_fallback_on_empty_response(self, caplog):
        """Mock chat to return empty content → verify placeholder."""
        classification = _make_valid_classification()

        with patch("src.inference.ollama_client.ollama.Client") as mock_client_cls:
            mock_instance = MagicMock()
            mock_instance.chat.return_value = {"message": {"content": ""}}
            mock_client_cls.return_value = mock_instance

            client = LLMInferenceClient(model="medgemma")

            with caplog.at_level(logging.WARNING):
                result = client.generate_narrative(classification)

        assert result == "BRCA1 - Pathogenic - LLM-generated narrative unavailable"
        assert any("WARNING" == record.levelname for record in caplog.records)


class TestDefaultModelSelection:
    """Test OLLAMA_MODEL environment variable handling."""

    def test_default_model_when_env_unset(self):
        """Ensure OLLAMA_MODEL is not set, create client, verify model == 'medgemma'."""
        env = os.environ.copy()
        env.pop("OLLAMA_MODEL", None)

        with patch("src.inference.ollama_client.ollama.Client"):
            with patch.dict(os.environ, env, clear=True):
                client = LLMInferenceClient()

        assert client.model == "medgemma"

    def test_default_model_when_env_empty(self):
        """Set OLLAMA_MODEL to '', verify model == 'medgemma'."""
        with patch("src.inference.ollama_client.ollama.Client"):
            with patch.dict(os.environ, {"OLLAMA_MODEL": ""}, clear=False):
                client = LLMInferenceClient()

        assert client.model == "medgemma"

    def test_model_from_env(self):
        """Set OLLAMA_MODEL to 'llama3', verify model == 'llama3'."""
        with patch("src.inference.ollama_client.ollama.Client"):
            with patch.dict(os.environ, {"OLLAMA_MODEL": "llama3"}, clear=False):
                client = LLMInferenceClient()

        assert client.model == "llama3"


class TestPlaceholderNarrativeFormat:
    """Test that the placeholder narrative includes gene name and classification value."""

    def test_placeholder_contains_gene_and_classification(self):
        """Verify the placeholder string format includes gene name and classification value."""
        classification = _make_valid_classification(
            gene="EGFR",
            classification=ACMGClassification.LIKELY_PATHOGENIC,
        )

        with patch("src.inference.ollama_client.ollama.Client") as mock_client_cls:
            mock_instance = MagicMock()
            mock_instance.chat.side_effect = ConnectionError("unreachable")
            mock_client_cls.return_value = mock_instance

            client = LLMInferenceClient(model="medgemma")
            result = client.generate_narrative(classification)

        assert "EGFR" in result
        assert "Likely Pathogenic" in result
        assert "LLM-generated narrative unavailable" in result
