"""Pipeline orchestrator for end-to-end PharmaGenomics processing.

This module provides a deterministic, local-first pipeline that can run
without cloud APIs. It integrates parser, security, MCP-backed data lookups,
and report generation into one callable entrypoint.
"""

from __future__ import annotations

import asyncio
import html
import logging
import os
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
    CapstoneCoverage,
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
        mcp_sources_used: set[str] = set()
        used_supervisor_path = False

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
            used_supervisor_path = True
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
            mcp_sources_used.update(classification.data_sources_queried)
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
                variant_recs = self._recommend_drugs(
                    variant,
                    classification,
                    warnings,
                    mcp_sources_used,
                )
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
            capstone_coverage=_build_capstone_coverage(
                runtime="local",
                used_supervisor_path=used_supervisor_path,
                mcp_sources_used=mcp_sources_used,
                has_narratives=any(bool(c.clinical_narrative) for c in classifications),
            ),
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
        mcp_sources_used: set[str] | None = None,
    ) -> list[DrugRecommendation]:
        # Query both CPIC and PharmGKB in sequence — each provides complementary
        # drug-gene interaction data from different curation methodologies
        cpic_result = asyncio.run(lookup_cpic_guidelines(variant.gene or ""))
        pharmgkb_result = asyncio.run(lookup_pharmgkb_annotations(variant.gene or ""))
        if mcp_sources_used is not None:
            cpic_source = cpic_result.get("source")
            pharmgkb_source = pharmgkb_result.get("source")
            if cpic_source:
                mcp_sources_used.add(f"cpic:{cpic_source}")
            if pharmgkb_source:
                mcp_sources_used.add(f"pharmgkb:{pharmgkb_source}")

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
                    "gene": variant.gene or "unknown",
                    "variant": f"{variant.chromosome}:{variant.position}",
                    "message": "No established pharmacogenomic guideline found for this variant",
                    "impact": "No gene-drug recommendation was generated",
                    "recommended_action": (
                        "Consider manual review of NCCN/ESMO guidance, clinical-trial eligibility, "
                        "and molecular tumor board consultation"
                    ),
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
    lines.append("## Tools and Platform Features")
    lines.append(f"- Agentic AI (multi-agent): {report.capstone_coverage.agentic_ai}")
    lines.append(f"- ADK runtime path: {report.capstone_coverage.adk_runtime}")
    lines.append(f"- MCP tools/data bridge: {report.capstone_coverage.mcp_tools}")
    lines.append(f"- Ollama inference: {report.capstone_coverage.ollama_inference}")
    lines.append(f"- Security layer enforced: {report.capstone_coverage.security_layer}")
    lines.append(f"- Agent skills configured: {report.capstone_coverage.agent_skills_configured}")
    lines.append(f"- Deployability assets present: {report.capstone_coverage.deployability_assets}")
    for note in report.capstone_coverage.notes:
        lines.append(f"  - {note}")

    lines.append("")
    lines.append("## Warnings")
    if not report.warnings:
        lines.append("None")
    for warning in report.warnings:
        lines.append(f"- {_format_warning(warning)}")

    return "\n".join(lines)


def render_html_report(report: ClinicalReport) -> str:
        """Render a visually rich HTML report suitable for broad audiences."""
        generated = report.generated_at.strftime("%Y-%m-%d %H:%M:%S UTC")

        def _flag(value: bool) -> str:
                return "Used" if value else "Not used"

        classification_cards: list[str] = []
        for item in report.classifications:
                summary = (
                        f"{item.variant_description}: "
                        f"{item.classification.value if item.classification else 'Unavailable'} "
                        f"({item.confidence.value if item.confidence else 'Unknown'})"
                )
                narrative = _format_html_narrative(item.clinical_narrative)
                classification_cards.append(
                        """
                        <article class=\"card\"> 
                            <h3>{summary}</h3>
                            <p>{narrative}</p>
                        </article>
                        """.format(summary=_escape(summary), narrative=narrative)
                )

        drug_rows: list[str] = []
        for rec in report.drug_recommendations:
                drug_rows.append(
                        """
                        <tr>
                            <td>{gene}</td>
                            <td>{variant}</td>
                            <td>{drug}</td>
                            <td>{action}</td>
                            <td>{evidence}</td>
                        </tr>
                        """.format(
                                gene=_escape(rec.gene),
                                variant=_escape(rec.variant),
                                drug=_escape(rec.drug_name),
                                action=_escape(rec.action.value),
                                evidence=_escape(rec.evidence_level),
                        )
                )

        literature_blocks: list[str] = []
        for block in report.literature_evidence:
                literature_blocks.append(
                        """
                        <article class=\"card\"> 
                            <h3>{query}</h3>
                            <p><strong>Citations:</strong> {count}</p>
                            <p>{synthesis}</p>
                        </article>
                        """.format(
                                query=_escape(block.query),
                                count=len(block.citations),
                                synthesis=_escape(block.synthesis_paragraph or "No synthesis generated."),
                        )
                )

        warnings_html = "".join(
            f"<li>{_escape(_format_warning(warning))}</li>" for warning in report.warnings
        ) or "<li>None</li>"

        coverage_rows = "".join(
                [
                        f"<tr><td>Multi-agent pipeline</td><td>{_flag(report.capstone_coverage.agentic_ai)}</td></tr>",
                        f"<tr><td>ADK runtime path</td><td>{_flag(report.capstone_coverage.adk_runtime)}</td></tr>",
                        f"<tr><td>MCP tools and data bridge</td><td>{_flag(report.capstone_coverage.mcp_tools)}</td></tr>",
                        f"<tr><td>Ollama inference</td><td>{_flag(report.capstone_coverage.ollama_inference)}</td></tr>",
                        f"<tr><td>Security layer</td><td>{_flag(report.capstone_coverage.security_layer)}</td></tr>",
                        f"<tr><td>Agent skills configuration</td><td>{_flag(report.capstone_coverage.agent_skills_configured)}</td></tr>",
                        f"<tr><td>Deployment assets</td><td>{_flag(report.capstone_coverage.deployability_assets)}</td></tr>",
                ]
        )
        coverage_notes = "".join(
                f"<li>{_escape(note)}</li>" for note in report.capstone_coverage.notes
        )

        return f"""<!DOCTYPE html>
<html lang=\"en\">
<head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <title>PharmaGenomics Advisor Clinical Report</title>
    <style>
        :root {{
            --bg: #f4f6f8;
            --panel: #ffffff;
            --ink: #0f1720;
            --muted: #4b5968;
            --accent: #0f4c81;
            --accent-soft: #e5eef7;
            --ok: #0b7a54;
            --warn: #9a3f1a;
            --border: #d9e1e8;
        }}
        * {{ box-sizing: border-box; }}
        body {{ margin: 0; font-family: "Segoe UI", Tahoma, sans-serif; background: linear-gradient(180deg, #eef4f9 0%, var(--bg) 70%); color: var(--ink); }}
        .wrap {{ max-width: 1100px; margin: 0 auto; padding: 28px 18px 40px; }}
        .header {{ background: var(--panel); border: 1px solid var(--border); border-radius: 14px; padding: 22px; box-shadow: 0 10px 24px rgba(12, 38, 59, 0.08); }}
        .header h1 {{ margin: 0 0 8px; font-size: 1.5rem; color: var(--accent); }}
        .header p {{ margin: 4px 0; color: var(--muted); }}
        .grid {{ display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); margin-top: 14px; }}
        .kpi {{ background: var(--accent-soft); border-radius: 10px; padding: 12px; border: 1px solid #c8d9ea; }}
        .kpi strong {{ display: block; font-size: 1.2rem; color: var(--accent); }}
        .section {{ margin-top: 18px; background: var(--panel); border: 1px solid var(--border); border-radius: 14px; padding: 16px; }}
        h2 {{ margin: 0 0 12px; font-size: 1.1rem; color: #123d65; border-bottom: 1px solid var(--border); padding-bottom: 8px; }}
        .stack {{ display: grid; gap: 10px; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); }}
        .card {{ background: #fbfdff; border: 1px solid var(--border); border-radius: 10px; padding: 12px; }}
        .card h3 {{ margin: 0 0 8px; font-size: 0.98rem; }}
        .card p {{ margin: 0; line-height: 1.45; color: var(--muted); }}
        table {{ width: 100%; border-collapse: collapse; font-size: 0.95rem; }}
        th, td {{ border: 1px solid var(--border); padding: 8px; text-align: left; vertical-align: top; }}
        th {{ background: #edf3f8; color: #173a5b; }}
        ul {{ margin: 0; padding-left: 20px; }}
        .notes {{ color: var(--muted); margin-top: 10px; }}
        .warn {{ color: var(--warn); }}
        @media (max-width: 640px) {{
            .header h1 {{ font-size: 1.25rem; }}
            th, td {{ font-size: 0.88rem; }}
        }}
    </style>
</head>
<body>
    <div class=\"wrap\">
        <header class=\"header\">
            <h1>PharmaGenomics Advisor Clinical Report</h1>
            <p><strong>Report ID:</strong> {_escape(report.report_id)}</p>
            <p><strong>Generated:</strong> {_escape(generated)}</p>
            <p><strong>Pipeline Version:</strong> {_escape(report.pipeline_version)}</p>
            <div class=\"grid\">
                <div class=\"kpi\"><span>Variants</span><strong>{len(report.variant_summary)}</strong></div>
                <div class=\"kpi\"><span>Classifications</span><strong>{len(report.classifications)}</strong></div>
                <div class=\"kpi\"><span>Drug Recommendations</span><strong>{len(report.drug_recommendations)}</strong></div>
                <div class=\"kpi\"><span>Literature Bundles</span><strong>{len(report.literature_evidence)}</strong></div>
                <div class=\"kpi\"><span>Execution Time</span><strong>{report.total_execution_time_seconds:.2f}s</strong></div>
            </div>
        </header>

        <section class=\"section\">
            <h2>Variant Classifications</h2>
            <div class=\"stack\">{''.join(classification_cards) or '<p>No routed variants were classified.</p>'}</div>
        </section>

        <section class=\"section\">
            <h2>Therapeutic Recommendations</h2>
            <table>
                <thead>
                    <tr><th>Gene</th><th>Variant</th><th>Drug</th><th>Action</th><th>Evidence</th></tr>
                </thead>
                <tbody>
                    {''.join(drug_rows) or '<tr><td colspan="5">No pharmacogenomic recommendations generated.</td></tr>'}
                </tbody>
            </table>
        </section>

        <section class=\"section\">
            <h2>Literature Evidence</h2>
            <div class=\"stack\">{''.join(literature_blocks) or '<p>No literature evidence generated.</p>'}</div>
        </section>

        <section class=\"section\">
            <h2>Tools and Platform Features</h2>
            <table>
                <thead><tr><th>Capability</th><th>Status</th></tr></thead>
                <tbody>{coverage_rows}</tbody>
            </table>
            <ul class=\"notes\">{coverage_notes}</ul>
        </section>

        <section class=\"section\">
            <h2>Clinical and Operational Warnings</h2>
            <ul class=\"warn\">{warnings_html}</ul>
        </section>
    </div>
</body>
</html>
"""


def _escape(value: str) -> str:
        """Escape user/model text before inserting into HTML output."""
        return html.escape(value, quote=True)


def _format_warning(warning: dict | str) -> str:
    """Render warning dictionaries as concise human-readable lines."""
    if isinstance(warning, dict):
        stage = warning.get("stage", "pipeline")
        gene = warning.get("gene")
        message = warning.get("message", "No additional details")
        variant = warning.get("variant")
        impact = warning.get("impact")
        recommended_action = warning.get("recommended_action")

        label = stage
        if gene:
            label = f"{stage}/{gene}"

        base = f"{label}: {message}"
        if variant:
            base = f"{base} ({variant})"
        if impact:
            base = f"{base}. Impact: {impact}."
        if recommended_action:
            base = f"{base} Recommended action: {recommended_action}."
        return base
    return str(warning)


def _format_html_narrative(narrative: str) -> str:
    """Convert markdown-like LLM narrative text into HTML-safe display text."""
    if not narrative:
        return "No narrative generated."
    cleaned = narrative.replace("**", "").replace("*", "")
    escaped = _escape(cleaned)
    return escaped.replace("\n", "<br />")


def _build_capstone_coverage(
    runtime: str,
    used_supervisor_path: bool,
    mcp_sources_used: set[str],
    has_narratives: bool,
) -> CapstoneCoverage:
    """Construct runtime coverage signals aligned to capstone evaluation criteria."""
    agent_skills_configured = Path("agent.yaml").exists() and Path("agents").exists()
    deployability_assets = all(
        Path(p).exists()
        for p in ["Dockerfile", "docker-compose.yml", "scripts/setup.sh", "readme.md"]
    )

    mcp_tools = bool(mcp_sources_used) or any(
        item.startswith("clinvar") or item.startswith("cpic") or item.startswith("pharmgkb")
        for item in mcp_sources_used
    )

    notes = [
        f"Runtime: {runtime}",
        f"Knowledge sources observed: {', '.join(sorted(mcp_sources_used)) or 'none'}",
        f"ENABLE_CLINVAR_ONLINE={os.getenv('ENABLE_CLINVAR_ONLINE', 'false')}",
    ]

    return CapstoneCoverage(
        agentic_ai=used_supervisor_path,
        adk_runtime=runtime == "adk",
        mcp_tools=mcp_tools,
        ollama_inference=has_narratives,
        security_layer=True,
        agent_skills_configured=agent_skills_configured,
        deployability_assets=deployability_assets,
        notes=notes,
    )
