"""Pipeline orchestrator for end-to-end PharmaGenomics processing.

This module provides a deterministic, local-first pipeline that can run
without cloud APIs. It integrates parser, security, MCP-backed data lookups,
and report generation into one callable entrypoint.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from src.infrastructure.ollama_check import check_ollama_ready
from src.mcp_servers_bridge import (
    lookup_clinvar,
    lookup_cpic_guidelines,
    lookup_pharmgkb_annotations,
)
from src.models import (
    ACMGClassification,
    ClinicalReport,
    ConfidenceLevel,
    DrugRecommendation,
    FunctionalStatus,
    LiteratureResult,
    ProvenanceMetadata,
    RecommendationAction,
    RouteStatus,
    TherapeuticRelevance,
    Variant,
    VariantClassification,
)
from src.parsers import VCFParser
from src.rag.literature_service import LiteratureService
from src.security.layer import SecurityLayer

logger = logging.getLogger(__name__)


ACTIONABLE_CLASSES = {
    ACMGClassification.PATHOGENIC,
    ACMGClassification.LIKELY_PATHOGENIC,
}


class PipelineOrchestrator:
    """Run the complete variant-to-report workflow."""

    def __init__(self, check_ollama: bool = False):
        self.parser = VCFParser()
        self.security = SecurityLayer.from_env()
        self.literature = LiteratureService()
        self.check_ollama = check_ollama

    def run(self, vcf_path: str | Path, session_id: str = "demo") -> ClinicalReport:
        """Execute full pipeline and return a clinical report model."""
        started = time.perf_counter()
        warnings: list[dict] = []

        # Ollama check is optional — only needed when LLM narratives are desired;
        # we degrade gracefully so the pipeline can still produce rule-based results
        if self.check_ollama:
            try:
                check_ollama_ready()
            except Exception as exc:  # pragma: no cover - environment dependent
                warnings.append({"stage": "ollama_check", "message": str(exc)})

        # Security validation runs BEFORE parsing to reject malicious input early,
        # preventing potential injection attacks from reaching the VCF parser
        raw_text = Path(vcf_path).read_text(encoding="utf-8")
        validation = self.security.validate(raw_text, session_id=session_id)
        if not validation.is_valid:
            raise ValueError(
                f"Security validation failed: {validation.error_message} "
                f"({validation.rejected_reason})"
            )

        parse_result = self.parser.parse(vcf_path)

        # Accumulate results across pipeline stages; each list is populated
        # independently so a failure in one stage doesn't lose earlier results
        classifications: list[VariantClassification] = []
        recommendations: list[DrugRecommendation] = []
        literature: list[LiteratureResult] = []
        provenance: list[ProvenanceMetadata] = []

        # Routing stage: only variants with known gene annotations can be dispatched
        # to specialist agents — unrouted variants are logged as warnings for reviewer visibility
        routable_variants: list[Variant] = []
        for variant in parse_result.variants:
            if variant.route_status == RouteStatus.UNROUTED or not variant.gene:
                warnings.append(
                    {
                        "stage": "routing",
                        "variant": f"{variant.chromosome}:{variant.position}",
                        "message": "Unsupported or missing gene annotation",
                    }
                )
            else:
                routable_variants.append(variant)

        # Classification strategy: prefer supervisor-based (multi-agent + LLM narratives)
        # but fall back to deterministic rule-based logic if agents or LLM are unavailable.
        # This ensures the pipeline always produces results even in degraded environments.
        try:
            classifications = self._classify_with_supervisor(routable_variants)
        except Exception as exc:
            logger.warning(
                "Supervisor-based classification failed, falling back to rule-based: %s",
                str(exc),
            )
            classifications = []
            for variant in routable_variants:
                classification = self._classify_variant(variant, warnings)
                classifications.append(classification)

        # Provenance tracking: record which agent and data sources contributed to each
        # classification — required for audit trail and reviewer transparency
        for i, variant in enumerate(routable_variants):
            classification = classifications[i]
            provenance.append(
                ProvenanceMetadata(
                    source_agent=f"{variant.gene.lower()}_agent",
                    data_sources_queried=classification.data_sources_queried,
                    confidence=classification.confidence,
                )
            )

            # Only pathogenic/likely-pathogenic variants trigger drug lookups —
            # VUS variants lack sufficient evidence for pharmacogenomic action
            if classification.classification in ACTIONABLE_CLASSES:
                variant_recs = self._recommend_drugs(variant, classification, warnings)
                recommendations.extend(variant_recs)

        # Literature retrieval is gated on having recommendations — no point querying
        # the RAG corpus if there are no actionable drug-gene pairs to evidence
        if recommendations:
            literature = self.literature.retrieve(recommendations)
            provenance.append(
                ProvenanceMetadata(
                    source_agent="literature_rag",
                    data_sources_queried=["local_literature_corpus"],
                    confidence=ConfidenceLevel.MODERATE,
                )
            )

        # Report assembly: gather all stage outputs into a single immutable report object.
        # Markdown rendering happens last so it can reflect the complete pipeline state.
        elapsed = time.perf_counter() - started
        report = ClinicalReport(
            total_execution_time_seconds=elapsed,
            variant_summary=parse_result.variants,
            classifications=classifications,
            drug_recommendations=recommendations,
            literature_evidence=literature,
            provenance=provenance,
            warnings=warnings,
        )
        report.markdown_summary = render_markdown_report(report)
        return report

    def _classify_with_supervisor(
        self, variants: list[Variant]
    ) -> list[VariantClassification]:
        """Classify variants using the SupervisorAgent and message bus.

        Creates a MessageBus, registers specialist handlers, instantiates
        an LLMInferenceClient and SupervisorAgent, then dispatches variants
        for concurrent classification with clinical narrative generation.

        Args:
            variants: List of routable Variant objects with supported genes.

        Returns:
            List of VariantClassification objects (with clinical narratives attached).

        Raises:
            Any exception if the supervisor-based classification fails.
        """
        # Deferred imports to avoid circular dependency — handlers and supervisor
        # reference models defined alongside this module's imports
        from src.agents.handlers import brca_handler, egfr_handler, tp53_handler
        from src.agents.message_bus import MessageBus
        from src.agents.supervisor import SupervisorAgent
        from src.inference.ollama_client import LLMInferenceClient

        bus = MessageBus()
        bus.register_agent("brca_agent", brca_handler)
        bus.register_agent("egfr_agent", egfr_handler)
        bus.register_agent("tp53_agent", tp53_handler)

        llm_client = LLMInferenceClient()
        supervisor = SupervisorAgent(bus, llm_client)

        # Run the async supervisor workflow synchronously — the pipeline's top-level
        # entry is sync, but agents use async internally for concurrent dispatch
        classifications = asyncio.run(supervisor.analyze_variants(variants))
        return classifications

    def _classify_variant(self, variant: Variant, warnings: list[dict]) -> VariantClassification:
        # ClinVar lookup happens first because its curated evidence informs the
        # final classification confidence — rule-based logic alone is less reliable
        clinvar = asyncio.run(lookup_clinvar(variant))
        data_sources = ["local_rules"]
        limitations: list[str] = []
        evidence: list[str] = []

        if clinvar.get("status") == "success":
            data_sources.append("clinvar")
            # Cap at 2 results to keep the evidence list concise for report readability;
            # additional ClinVar entries rarely change the clinical interpretation
            for result in clinvar.get("results", [])[:2]:
                significance = result.get("clinical_significance", "unknown")
                review = result.get("review_status", "unknown")
                evidence.append(f"ClinVar: {significance} ({review})")
        elif clinvar.get("status") == "disabled":
            limitations.append("ClinVar online lookup disabled")
        else:
            # Record the failure as both a limitation and a warning — limitations appear
            # in the classification output, warnings appear in the pipeline summary
            limitations.append("ClinVar unavailable or no records found")
            warnings.append(
                {
                    "stage": "clinvar",
                    "variant": f"{variant.chromosome}:{variant.position}",
                    "message": clinvar.get("error", clinvar.get("status", "lookup failed")),
                }
            )

        # Combine rule-based classification with gene-specific annotations;
        # therapeutic relevance and functional status are only set for EGFR/TP53 respectively
        classification, confidence = _rule_based_acmg(variant)
        therapeutic_relevance = _egfr_therapeutic_relevance(variant) or TherapeuticRelevance.UNKNOWN
        functional_status = _tp53_functional_status(variant)

        return VariantClassification(
            gene=variant.gene,
            variant_description=_variant_description(variant),
            chromosome=variant.chromosome,
            position=variant.position,
            ref_allele=variant.ref_allele,
            alt_allele=variant.alt_allele,
            classification=classification,
            confidence=confidence,
            evidence_references=evidence or ["Rule-based assessment from local knowledge base"],
            therapeutic_relevance=therapeutic_relevance,
            functional_status=functional_status,
            data_sources_queried=data_sources,
            limitations=limitations,
        )

    def _recommend_drugs(
        self,
        variant: Variant,
        classification: VariantClassification,
        warnings: list[dict],
    ) -> list[DrugRecommendation]:
        # Query both CPIC and PharmGKB in sequence — each provides complementary
        # drug-gene interaction data from different curation methodologies
        cpic_result = asyncio.run(lookup_cpic_guidelines(variant.gene or ""))
        pharmgkb_result = asyncio.run(lookup_pharmgkb_annotations(variant.gene or ""))

        recommendations: list[DrugRecommendation] = []
        # Deduplication via seen_keys prevents the same gene-drug pair from appearing
        # twice when both CPIC and PharmGKB report overlapping guideline entries
        seen_keys: set[tuple[str, str]] = set()

        if cpic_result.get("status") == "success":
            for row in cpic_result.get("results", []):
                key = (row.get("gene", ""), row.get("drug", ""))
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                recommendations.append(
                    DrugRecommendation(
                        drug_name=row.get("drug", "unknown"),
                        gene=row.get("gene", variant.gene or "unknown"),
                        variant=variant.hgvs or _variant_description(variant),
                        action=_to_action(row.get("recommendation", "alternative therapy")),
                        evidence_level=str(row.get("cpic_level", "B")),
                        guideline_source_url=row.get("url", ""),
                        contraindications=row.get("contraindications", []),
                    )
                )

        # PharmGKB is only consulted for EGFR TKI-sensitive variants — other genes
        # rely solely on CPIC guidelines to avoid noisy/irrelevant annotations
        if (
            variant.gene == "EGFR"
            and classification.therapeutic_relevance == TherapeuticRelevance.TKI_SENSITIVE
            and pharmgkb_result.get("status") == "success"
        ):
            for row in pharmgkb_result.get("results", []):
                key = (row.get("gene", ""), row.get("drug", ""))
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                recommendations.append(
                    DrugRecommendation(
                        drug_name=row.get("drug", "unknown"),
                        gene=row.get("gene", variant.gene),
                        variant=row.get("variant", variant.hgvs or "unknown"),
                        action=RecommendationAction.RECOMMENDED,
                        evidence_level=str(row.get("evidence_level", "B")),
                        guideline_source_url="https://www.pharmgkb.org/",
                        contraindications=[],
                    )
                )

        if not recommendations:
            # Surface the absence of guidelines as a warning rather than silently omitting —
            # reviewers need visibility into which variants lacked pharmacogenomic coverage
            warnings.append(
                {
                    "stage": "pgx",
                    "variant": f"{variant.chromosome}:{variant.position}",
                    "message": "No established pharmacogenomic guideline found",
                }
            )

        return recommendations


def _variant_description(variant: Variant) -> str:
    hgvs = f" ({variant.hgvs})" if variant.hgvs else ""
    return f"{variant.gene} {variant.chromosome}:{variant.position} {variant.ref_allele}>{variant.alt_allele}{hgvs}"


def _rule_based_acmg(variant: Variant) -> tuple[ACMGClassification, ConfidenceLevel]:
    hgvs = (variant.hgvs or "").upper()
    note = str(variant.info.get("Note", "")).upper()

    if variant.gene in {"BRCA1", "BRCA2"}:
        if variant.variant_type.name in {"FRAMESHIFT", "NONSENSE", "SPLICE"}:
            return ACMGClassification.PATHOGENIC, ConfidenceLevel.HIGH
        return ACMGClassification.LIKELY_PATHOGENIC, ConfidenceLevel.MODERATE

    if variant.gene == "EGFR":
        if any(token in hgvs or token in note for token in ["L858R", "EXON 19", "G719", "L861Q"]):
            return ACMGClassification.PATHOGENIC, ConfidenceLevel.HIGH
        if any(token in hgvs or token in note for token in ["T790M", "C797S", "EXON 20"]):
            return ACMGClassification.LIKELY_PATHOGENIC, ConfidenceLevel.MODERATE
        return ACMGClassification.VUS, ConfidenceLevel.LOW

    if variant.gene == "TP53":
        if any(token in hgvs or token in note for token in ["R175H", "R248W", "R273H", "Y220C", "G245S", "R249S"]):
            return ACMGClassification.PATHOGENIC, ConfidenceLevel.HIGH
        if variant.variant_type.name in {"FRAMESHIFT", "NONSENSE", "SPLICE"}:
            return ACMGClassification.PATHOGENIC, ConfidenceLevel.MODERATE
        return ACMGClassification.LIKELY_PATHOGENIC, ConfidenceLevel.MODERATE

    return ACMGClassification.VUS, ConfidenceLevel.LOW


def _egfr_therapeutic_relevance(variant: Variant) -> TherapeuticRelevance | None:
    if variant.gene != "EGFR":
        return None

    text = f"{variant.hgvs or ''} {variant.info.get('Note', '')}".upper()
    if any(token in text for token in ["L858R", "EXON 19", "G719", "L861Q", "S768I"]):
        return TherapeuticRelevance.TKI_SENSITIVE
    if any(token in text for token in ["T790M", "C797S", "EXON 20"]):
        return TherapeuticRelevance.TKI_RESISTANT
    return TherapeuticRelevance.UNKNOWN


def _tp53_functional_status(variant: Variant) -> FunctionalStatus | None:
    if variant.gene != "TP53":
        return None

    text = f"{variant.hgvs or ''} {variant.info.get('Note', '')}".upper()
    if any(token in text for token in ["R175H", "R248W", "R273H", "Y220C", "G245S", "R249S"]):
        return FunctionalStatus.GAIN_OF_FUNCTION
    if variant.variant_type.name in {"FRAMESHIFT", "NONSENSE", "SPLICE"}:
        return FunctionalStatus.LOSS_OF_FUNCTION
    return FunctionalStatus.UNDETERMINED


def _to_action(value: str) -> RecommendationAction:
    normalized = value.strip().lower()
    mapping = {
        "avoid": RecommendationAction.AVOID,
        "dose adjustment": RecommendationAction.DOSE_ADJUSTMENT,
        "standard dosing": RecommendationAction.STANDARD_DOSING,
        "alternative therapy": RecommendationAction.ALTERNATIVE_THERAPY,
        "recommended": RecommendationAction.RECOMMENDED,
    }
    return mapping.get(normalized, RecommendationAction.ALTERNATIVE_THERAPY)


def render_markdown_report(report: ClinicalReport) -> str:
    """Render a concise Markdown summary for human review."""
    lines: list[str] = []
    # Header section includes key metrics upfront so reviewers can assess
    # pipeline completeness at a glance without scrolling through details
    lines.append("# PharmaGenomics Advisor Clinical Report")
    lines.append("")
    lines.append(f"- Report ID: {report.report_id}")
    lines.append(f"- Pipeline Version: {report.pipeline_version}")
    lines.append(f"- Variants Analyzed: {len(report.variant_summary)}")
    lines.append(f"- Classifications: {len(report.classifications)}")
    lines.append(f"- Drug Recommendations: {len(report.drug_recommendations)}")
    lines.append(f"- Literature Bundles: {len(report.literature_evidence)}")
    lines.append(f"- Execution Time: {report.total_execution_time_seconds:.2f}s")
    lines.append("")

    lines.append("## Variant Classifications")
    if not report.classifications:
        lines.append("No routed variants were classified.")
    for item in report.classifications:
        lines.append(
            f"- {item.variant_description}: {item.classification.value if item.classification else 'Unavailable'} "
            f"({item.confidence.value if item.confidence else 'Unknown'})"
        )
        if item.clinical_narrative:
            lines.append(f"  - Clinical Narrative: {item.clinical_narrative}")

    lines.append("")
    lines.append("## Drug Recommendations")
    if not report.drug_recommendations:
        lines.append("No pharmacogenomic recommendations generated.")
    for rec in report.drug_recommendations:
        lines.append(
            f"- {rec.gene} {rec.variant}: {rec.drug_name} | {rec.action.value} | evidence {rec.evidence_level}"
        )

    lines.append("")
    lines.append("## Literature Evidence")
    if not report.literature_evidence:
        lines.append("No literature evidence generated.")
    for block in report.literature_evidence:
        lines.append(f"- Query: {block.query} ({len(block.citations)} citations)")
        if block.synthesis_paragraph:
            lines.append(f"  - Synthesis: {block.synthesis_paragraph}")

    lines.append("")
    lines.append("## Warnings")
    if not report.warnings:
        lines.append("None")
    for warning in report.warnings:
        lines.append(f"- {warning}")

    return "\n".join(lines)
