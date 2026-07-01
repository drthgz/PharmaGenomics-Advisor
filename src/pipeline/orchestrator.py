"""Pipeline orchestrator for end-to-end PharmaGenomics processing.

This module provides a deterministic, local-first pipeline that can run
without cloud APIs. It integrates parser, security, MCP-backed data lookups,
and report generation into one callable entrypoint.
"""

from __future__ import annotations

import asyncio
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

        if self.check_ollama:
            try:
                check_ollama_ready()
            except Exception as exc:  # pragma: no cover - environment dependent
                warnings.append({"stage": "ollama_check", "message": str(exc)})

        raw_text = Path(vcf_path).read_text(encoding="utf-8")
        validation = self.security.validate(raw_text, session_id=session_id)
        if not validation.is_valid:
            raise ValueError(
                f"Security validation failed: {validation.error_message} "
                f"({validation.rejected_reason})"
            )

        parse_result = self.parser.parse(vcf_path)

        classifications: list[VariantClassification] = []
        recommendations: list[DrugRecommendation] = []
        literature: list[LiteratureResult] = []
        provenance: list[ProvenanceMetadata] = []

        for variant in parse_result.variants:
            if variant.route_status == RouteStatus.UNROUTED or not variant.gene:
                warnings.append(
                    {
                        "stage": "routing",
                        "variant": f"{variant.chromosome}:{variant.position}",
                        "message": "Unsupported or missing gene annotation",
                    }
                )
                continue

            classification = self._classify_variant(variant, warnings)
            classifications.append(classification)
            provenance.append(
                ProvenanceMetadata(
                    source_agent=f"{variant.gene.lower()}_agent",
                    data_sources_queried=classification.data_sources_queried,
                    confidence=classification.confidence,
                )
            )

            if classification.classification in ACTIONABLE_CLASSES:
                variant_recs = self._recommend_drugs(variant, classification, warnings)
                recommendations.extend(variant_recs)

        if recommendations:
            literature = self.literature.retrieve(recommendations)
            provenance.append(
                ProvenanceMetadata(
                    source_agent="literature_rag",
                    data_sources_queried=["local_literature_corpus"],
                    confidence=ConfidenceLevel.MODERATE,
                )
            )

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

    def _classify_variant(self, variant: Variant, warnings: list[dict]) -> VariantClassification:
        clinvar = asyncio.run(lookup_clinvar(variant))
        data_sources = ["local_rules"]
        limitations: list[str] = []
        evidence: list[str] = []

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
            warnings.append(
                {
                    "stage": "clinvar",
                    "variant": f"{variant.chromosome}:{variant.position}",
                    "message": clinvar.get("error", clinvar.get("status", "lookup failed")),
                }
            )

        classification, confidence = _rule_based_acmg(variant)
        therapeutic_relevance = _egfr_therapeutic_relevance(variant)
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
        cpic_result = asyncio.run(lookup_cpic_guidelines(variant.gene or ""))
        pharmgkb_result = asyncio.run(lookup_pharmgkb_annotations(variant.gene or ""))

        recommendations: list[DrugRecommendation] = []
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
