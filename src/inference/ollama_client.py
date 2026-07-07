"""LLM Inference Client wrapping ollama.chat() for clinical narrative generation.

Calls the local Ollama server to produce clinical interpretation paragraphs
for classified variants. Gracefully degrades to a placeholder narrative on
any failure (network, timeout, HTTP error, empty response).
"""

from __future__ import annotations

import logging
import os
import re

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

            cleaned = self._sanitize_narrative(content, classification)
            # Hard cap at 2000 chars to keep downstream report rendering predictable
            # and prevent a runaway LLM from bloating the clinical report
            return cleaned[:2000]

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

    def _sanitize_narrative(self, narrative: str, classification: VariantClassification) -> str:
        """Normalize LLM output and replace unresolved template content.

        Some model responses contain bracketed placeholders (e.g.,
        "[Insert Variant Allele]") or mismatched variant references copied from
        generic templates. Those should never appear in clinical reports.
        """
        text = narrative.strip()
        if not text:
            return self._placeholder_narrative(classification)

        unresolved_placeholder_patterns = [
            r"\[[^\]]*(insert|variant|allele|gene|identifier|fill|placeholder)[^\]]*\]",
            r"<[^>]*(insert|variant|allele|gene|identifier|placeholder)[^>]*>",
            r"\b(\[variant identifier\]|\[insert [^\]]+\])\b",
        ]
        for pattern in unresolved_placeholder_patterns:
            if re.search(pattern, text, flags=re.IGNORECASE):
                logger.warning(
                    "LLM narrative contained unresolved placeholders for %s; using deterministic fallback",
                    classification.gene,
                )
                return self._deterministic_narrative(classification)

        # If the model omits the target gene entirely, prefer a deterministic
        # narrative to avoid reporting likely cross-variant hallucinations.
        if classification.gene and classification.gene.upper() not in text.upper():
            logger.warning(
                "LLM narrative omitted target gene for %s; using deterministic fallback",
                classification.gene,
            )
            return self._deterministic_narrative(classification)

        return text

    def _deterministic_narrative(self, classification: VariantClassification) -> str:
        """Generate a deterministic clinical narrative from structured fields."""
        gene = classification.gene or "Unknown"
        label = classification.classification.value if classification.classification else "Unknown"
        confidence = classification.confidence.value if classification.confidence else "Unknown"
        variant = (
            f"{classification.chromosome}:{classification.position} "
            f"{classification.ref_allele}>{classification.alt_allele}"
        )

        therapeutic_text = "Therapeutic relevance is not established for this variant."
        if classification.therapeutic_relevance:
            therapeutic_text = (
                f"Therapeutic relevance is annotated as "
                f"{classification.therapeutic_relevance.value}."
            )

        evidence_text = "Supporting evidence is available from local rule-based assessment."
        if classification.evidence_references:
            top = "; ".join(classification.evidence_references[:2])
            evidence_text = f"Supporting evidence includes: {top}."

        return (
            f"The {gene} variant ({variant}) is classified as {label} "
            f"with {confidence} confidence. "
            f"This interpretation should be reviewed alongside patient history, "
            f"tumor context, and current guidelines. "
            f"{therapeutic_text} {evidence_text}"
        )

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
        """Construct the LLM prompt including gene, classification, evidence, and relevance."""
        # Join evidence list into a single semicolon-delimited string so the LLM
        # sees all citations in one block rather than a Python list repr
        evidence = "; ".join(classification.evidence_references)
        # Structured prompt with explicit role-setting ("You are a clinical genomics expert")
        # steers the model toward domain-appropriate language and avoids generic summaries
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
        # Fallback preserves gene + classification so downstream report sections
        # still render meaningful headers even without a full narrative
        gene = classification.gene or "Unknown"
        acmg_value = (
            classification.classification.value
            if classification.classification
            else "Unknown"
        )
        return f"{gene} - {acmg_value} - LLM-generated narrative unavailable"
