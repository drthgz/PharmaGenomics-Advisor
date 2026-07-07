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
            # Prefer env var so Docker builds can inject model at runtime without code changes
            model = env_model if env_model else "medgemma"
        self.model = model
        self.timeout = timeout
        # Instantiate a dedicated client rather than using the module-level default
        # so each client instance can carry its own timeout and host configuration
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
        # Validate early to avoid a costly network round-trip when input is incomplete
        if not self._has_required_fields(classification):
            return ""

        try:
            prompt = self._build_prompt(classification)
            # Use single-message chat (no conversation history) because each narrative
            # is independent — no multi-turn context is needed for clinical summaries
            response = self._client.chat(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
            )

            # Ollama's response schema nests content under "message.content";
            # defensive .get() prevents KeyError if the schema changes between versions
            content = response.get("message", {}).get("content", "")

            # Treat whitespace-only responses the same as empty — they provide no
            # clinical value and would produce a blank section in the final report
            if not content or not content.strip():
                logger.warning(
                    "Ollama returned empty response for variant %s (%s)",
                    classification.gene,
                    classification.classification.value if classification.classification else "N/A",
                )
                return self._placeholder_narrative(classification)

            # Hard cap at 2000 chars to keep downstream report rendering predictable
            # and prevent a runaway LLM from bloating the clinical report
            return content[:2000]

        except Exception as exc:
            # Catch-all ensures the pipeline never crashes due to LLM unavailability;
            # a degraded narrative is acceptable, but a pipeline abort is not
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
        # Each field maps to a distinct prompt section; if any is absent the LLM
        # would hallucinate missing context, producing unreliable clinical text
        if not classification.gene:
            return False
        if not classification.classification:
            return False
        # Evidence list drives the "supporting literature" portion of the prompt —
        # without it the narrative would lack citations and lose clinical credibility
        if not classification.evidence_references:
            return False
        if not classification.therapeutic_relevance:
            return False
        return True

    def _build_prompt(self, classification: VariantClassification) -> str:
        """Construct the LLM prompt including gene, variant details, classification, evidence, and relevance."""
        # Join evidence list into a single semicolon-delimited string so the LLM
        # sees all citations in one block rather than a Python list repr
        evidence = "; ".join(classification.evidence_references)
        # Build a human-readable variant string from HGVS or chrom:pos ref>alt
        variant_detail = (
            classification.variant_description
            or f"{classification.chromosome}:{classification.position} {classification.ref_allele}>{classification.alt_allele}"
        )
        # Include explicit ref/alt allele values so the model never needs to
        # invent or template-fill allele placeholders in its response
        therapeutic_value = (
            classification.therapeutic_relevance.value
            if classification.therapeutic_relevance
            else "unknown"
        )
        # Structured prompt with explicit role-setting ("You are a clinical genomics expert")
        # steers the model toward domain-appropriate language and avoids generic summaries
        return (
            "You are a clinical genomics expert. Generate a concise 2-3 sentence clinical "
            "interpretation for the following classified genetic variant. Include the clinical "
            "significance, potential impact on patient care, and relevant therapeutic "
            "considerations. Use only the exact values provided below — do NOT use placeholder "
            "text, brackets, or template variables in your response.\n\n"
            f"Gene: {classification.gene}\n"
            f"Variant: {variant_detail}\n"
            f"Reference Allele: {classification.ref_allele}\n"
            f"Alternate Allele: {classification.alt_allele}\n"
            f"ACMG Classification: {classification.classification.value}\n"
            f"Evidence References: {evidence}\n"
            f"Therapeutic Relevance: {therapeutic_value}\n\n"
            "Provide a clear, professional clinical narrative suitable for a genomics report. "
            "Do not include any placeholder text such as '[Insert ...]' or '<...>'."
        )

    def _placeholder_narrative(self, classification: VariantClassification) -> str:
        """Return fallback text when LLM inference fails.

        Includes gene, variant description, and ACMG classification so that
        downstream report sections still render meaningful content even when
        the Ollama server is unavailable or returns an empty response.
        """
        gene = classification.gene or "Unknown"
        acmg_value = (
            classification.classification.value
            if classification.classification
            else "Unknown"
        )
        # Include variant description so reviewers have context without the LLM narrative
        variant_desc = (
            classification.variant_description
            or f"{classification.chromosome}:{classification.position} {classification.ref_allele}>{classification.alt_allele}"
        )
        return (
            f"The {gene} variant {variant_desc} is classified as {acmg_value}. "
            "LLM-generated clinical narrative is unavailable (Ollama not reachable). "
            "Manual clinical review is required before acting on this classification."
        )
