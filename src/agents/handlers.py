"""Specialist agent handlers for gene-specific variant classification.

Each handler wraps existing rule-based classification logic from the pipeline
orchestrator, providing an async message-passing interface for the MessageBus.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from src.models import (
    AgentMessage,
    MessageType,
    TherapeuticRelevance,
    Variant,
    VariantClassification,
)
from src.mcp_servers_bridge import lookup_clinvar
from src.pipeline.orchestrator import (
    _egfr_therapeutic_relevance,
    _rule_based_acmg,
    _tp53_functional_status,
    _variant_description,
)

logger = logging.getLogger(__name__)


async def brca_handler(msg: AgentMessage) -> AgentMessage:
    """Classify BRCA1/BRCA2 variants using existing rule-based ACMG logic.

    Args:
        msg: AgentMessage with payload containing a serialized Variant dict.

    Returns:
        AgentMessage with CLASSIFY_RESPONSE containing VariantClassification,
        or ERROR message on failure.
    """
    try:
        variant = Variant(**msg.payload["variant"])
        classification, confidence = _rule_based_acmg(variant)
        clinvar = await lookup_clinvar(variant)

        evidence = ["Rule-based assessment from local knowledge base"]
        data_sources = ["local_rules"]
        limitations: list[str] = []

        if clinvar.get("status") == "success":
            data_sources.append("clinvar")
            for result in clinvar.get("results", [])[:2]:
                significance = result.get("clinical_significance", "unknown")
                review = result.get("review_status", "unknown")
                evidence.append(f"ClinVar: {significance} ({review})")
        elif clinvar.get("status") == "disabled":
            limitations.append("ClinVar online lookup disabled")
        else:
            limitations.append("ClinVar unavailable or no records found")

        result = VariantClassification(
            gene=variant.gene or "BRCA",
            variant_description=_variant_description(variant),
            chromosome=variant.chromosome,
            position=variant.position,
            ref_allele=variant.ref_allele,
            alt_allele=variant.alt_allele,
            classification=classification,
            confidence=confidence,
            evidence_references=evidence,
            therapeutic_relevance=TherapeuticRelevance.UNKNOWN,
            data_sources_queried=data_sources,
            limitations=limitations,
        )

        return AgentMessage(
            message_type=MessageType.CLASSIFY_RESPONSE,
            sender="brca_agent",
            recipient=msg.sender,
            payload={"classification": result.model_dump(mode="json")},
            timestamp=datetime.now(timezone.utc),
        )
    except Exception as exc:
        logger.warning("brca_handler error: %s", str(exc))
        return AgentMessage(
            message_type=MessageType.ERROR,
            sender="brca_agent",
            recipient=msg.sender,
            payload={"error": str(exc)},
            timestamp=datetime.now(timezone.utc),
        )


async def egfr_handler(msg: AgentMessage) -> AgentMessage:
    """Classify EGFR variants with TKI sensitivity annotation.

    Args:
        msg: AgentMessage with payload containing a serialized Variant dict.

    Returns:
        AgentMessage with CLASSIFY_RESPONSE containing VariantClassification
        (including therapeutic_relevance), or ERROR message on failure.
    """
    try:
        variant = Variant(**msg.payload["variant"])
        classification, confidence = _rule_based_acmg(variant)
        therapeutic_relevance = _egfr_therapeutic_relevance(variant)
        clinvar = await lookup_clinvar(variant)

        evidence = ["Rule-based assessment from local knowledge base"]
        data_sources = ["local_rules"]
        limitations: list[str] = []

        if clinvar.get("status") == "success":
            data_sources.append("clinvar")
            for result in clinvar.get("results", [])[:2]:
                significance = result.get("clinical_significance", "unknown")
                review = result.get("review_status", "unknown")
                evidence.append(f"ClinVar: {significance} ({review})")
        elif clinvar.get("status") == "disabled":
            limitations.append("ClinVar online lookup disabled")
        else:
            limitations.append("ClinVar unavailable or no records found")

        result = VariantClassification(
            gene=variant.gene or "EGFR",
            variant_description=_variant_description(variant),
            chromosome=variant.chromosome,
            position=variant.position,
            ref_allele=variant.ref_allele,
            alt_allele=variant.alt_allele,
            classification=classification,
            confidence=confidence,
            evidence_references=evidence,
            therapeutic_relevance=therapeutic_relevance,
            data_sources_queried=data_sources,
            limitations=limitations,
        )

        return AgentMessage(
            message_type=MessageType.CLASSIFY_RESPONSE,
            sender="egfr_agent",
            recipient=msg.sender,
            payload={"classification": result.model_dump(mode="json")},
            timestamp=datetime.now(timezone.utc),
        )
    except Exception as exc:
        logger.warning("egfr_handler error: %s", str(exc))
        return AgentMessage(
            message_type=MessageType.ERROR,
            sender="egfr_agent",
            recipient=msg.sender,
            payload={"error": str(exc)},
            timestamp=datetime.now(timezone.utc),
        )


async def tp53_handler(msg: AgentMessage) -> AgentMessage:
    """Classify TP53 variants with functional status annotation.

    Args:
        msg: AgentMessage with payload containing a serialized Variant dict.

    Returns:
        AgentMessage with CLASSIFY_RESPONSE containing VariantClassification
        (including functional_status), or ERROR message on failure.
    """
    try:
        variant = Variant(**msg.payload["variant"])
        classification, confidence = _rule_based_acmg(variant)
        functional_status = _tp53_functional_status(variant)
        clinvar = await lookup_clinvar(variant)

        evidence = ["Rule-based assessment from local knowledge base"]
        data_sources = ["local_rules"]
        limitations: list[str] = []

        if clinvar.get("status") == "success":
            data_sources.append("clinvar")
            for result in clinvar.get("results", [])[:2]:
                significance = result.get("clinical_significance", "unknown")
                review = result.get("review_status", "unknown")
                evidence.append(f"ClinVar: {significance} ({review})")
        elif clinvar.get("status") == "disabled":
            limitations.append("ClinVar online lookup disabled")
        else:
            limitations.append("ClinVar unavailable or no records found")

        result = VariantClassification(
            gene=variant.gene or "TP53",
            variant_description=_variant_description(variant),
            chromosome=variant.chromosome,
            position=variant.position,
            ref_allele=variant.ref_allele,
            alt_allele=variant.alt_allele,
            classification=classification,
            confidence=confidence,
            evidence_references=evidence,
            functional_status=functional_status,
            therapeutic_relevance=TherapeuticRelevance.UNKNOWN,
            data_sources_queried=data_sources,
            limitations=limitations,
        )

        return AgentMessage(
            message_type=MessageType.CLASSIFY_RESPONSE,
            sender="tp53_agent",
            recipient=msg.sender,
            payload={"classification": result.model_dump(mode="json")},
            timestamp=datetime.now(timezone.utc),
        )
    except Exception as exc:
        logger.warning("tp53_handler error: %s", str(exc))
        return AgentMessage(
            message_type=MessageType.ERROR,
            sender="tp53_agent",
            recipient=msg.sender,
            payload={"error": str(exc)},
            timestamp=datetime.now(timezone.utc),
        )
