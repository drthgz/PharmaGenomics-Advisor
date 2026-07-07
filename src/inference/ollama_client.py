"""LLM Inference Client wrapping ollama.chat() for clinical narrative generation.

Calls the local Ollama server to produce clinical interpretation paragraphs
for classified variants. Gracefully degrades to a placeholder narrative on
any failure (network, timeout, HTTP error, empty response).
"""

from __future__ import annotations

import logging
import os

import ollama

from src.models import VariantClassification

logger = logging.getLogger(__name__)


class LLMInferenceClient:
    """Calls ollama.chat() to produce clinical narrative for classified variants."""

    def __init__(self, model: str | None = None, timeout: float = 30.0):
        """Initialize the LLM inference client.

        Args:
            model: Ollama model name. Defaults to OLLAMA_MODEL env var or "medgemma".
            timeout: HTTP timeout in seconds (default 30s per requirement 1.5).
        """
        if model is None:
            env_model = os.environ.get("OLLAMA_MODEL")
            model = env_model if env_model else "medgemma"
        self.model = model
        self.timeout = timeout
        self._client = ollama.Client(timeout=timeout)

    def generate_narrative(self, classification: VariantClassification) -> str:
        """Generate a clinical narrative for a classified variant.

        Args:
            classification: Must have non-empty gene, classification,
                          evidence_references, and therapeutic_relevance.

        Returns:
            Narrative string (max 2000 chars), or empty string if fields missing,
            or placeholder on failure.

        Behavior:
            - Validates all 4 required fields are present and non-empty
            - If any field missing/empty: returns empty string without calling Ollama
            - Calls ollama.chat() with structured prompt
            - Truncates response to 2000 characters
            - On any error: logs WARNING and returns placeholder
        """
        # Validate required fields before calling Ollama
        if not self._has_required_fields(classification):
            return ""

        try:
            prompt = self._build_prompt(classification)
            response = self._client.chat(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
            )

            # Extract content from response
            content = response.get("message", {}).get("content", "")

            # Handle empty/whitespace-only response
            if not content or not content.strip():
                logger.warning(
                    "Ollama returned empty response for variant %s (%s)",
                    classification.gene,
                    classification.classification.value if classification.classification else "N/A",
                )
                return self._placeholder_narrative(classification)

            # Truncate to 2000 characters maximum
            return content[:2000]

        except Exception as exc:
            logger.warning(
                "LLM inference failed for variant %s (%s): %s",
                classification.gene,
                classification.classification.value if classification.classification else "N/A",
                str(exc),
            )
            return self._placeholder_narrative(classification)

    def _has_required_fields(self, classification: VariantClassification) -> bool:
        """Check that all four required fields are present and non-empty.

        Required fields: gene, classification, evidence_references, therapeutic_relevance.
        """
        if not classification.gene:
            return False
        if not classification.classification:
            return False
        if not classification.evidence_references:
            return False
        if not classification.therapeutic_relevance:
            return False
        return True

    def _build_prompt(self, classification: VariantClassification) -> str:
        """Construct the LLM prompt including gene, classification, evidence, and relevance."""
        evidence = "; ".join(classification.evidence_references)
        return (
            "You are a clinical genomics expert. Generate a concise clinical interpretation "
            "paragraph for the following classified genetic variant. Include clinical significance, "
            "potential impact on patient care, and relevant therapeutic considerations.\n\n"
            f"Gene: {classification.gene}\n"
            f"ACMG Classification: {classification.classification.value}\n"
            f"Evidence References: {evidence}\n"
            f"Therapeutic Relevance: {classification.therapeutic_relevance.value}\n\n"
            "Provide a clear, professional clinical narrative suitable for a genomics report."
        )

    def _placeholder_narrative(self, classification: VariantClassification) -> str:
        """Return fallback text when LLM inference fails."""
        gene = classification.gene or "Unknown"
        acmg_value = (
            classification.classification.value
            if classification.classification
            else "Unknown"
        )
        return f"{gene} - {acmg_value} - LLM-generated narrative unavailable"
