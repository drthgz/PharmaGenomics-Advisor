"""ADK-backed workflow runner for PharmaGenomics Advisor.

This module adds an explicit Google ADK execution path while preserving the
existing deterministic pipeline behavior.
"""

from __future__ import annotations

import importlib
import time
from pathlib import Path
from typing import Any

from google.genai import types

from src.infrastructure.ollama_check import check_ollama_ready
from src.models import (
    DrugRecommendation,
    ClinicalReport,
    ConfidenceLevel,
    RecommendationAction,
    TherapeuticRelevance,
    VariantClassification,
    ProvenanceMetadata,
    RouteStatus,
)
import src.pipeline.orchestrator as orchestrator_module
from src.pipeline.orchestrator import (
    ACTIONABLE_CLASSES,
    PipelineOrchestrator,
    _egfr_therapeutic_relevance,
    _rule_based_acmg,
    _to_action,
    _tp53_functional_status,
    _variant_description,
    render_markdown_report,
)


class ADKNotAvailableError(RuntimeError):
    """Raised when Google ADK runtime cannot be imported or used."""


class ADKWorkflowRunner:
    """Execute pipeline through a Google ADK workflow."""

    def __init__(self, check_ollama: bool = False):
        self._orchestrator = PipelineOrchestrator(check_ollama=check_ollama)
        self._check_ollama = check_ollama

    def run(self, vcf_path: str | Path, session_id: str = "demo") -> ClinicalReport:
        """Run the pipeline using ADK workflow orchestration."""
        adk = self._import_adk()
        workflow = self._build_workflow(adk)
        runner = self._build_runner(adk, workflow)

        user_message = types.UserContent(parts=[types.Part.from_text(text="run pipeline")])
        state_delta = {
            "vcf_path": str(vcf_path),
            "session_id": session_id,
            "check_ollama": self._check_ollama,
        }

        final_output: Any = None
        for event in runner.run(
            user_id="local-user",
            session_id=f"{session_id}-adk",
            new_message=user_message,
            state_delta=state_delta,
        ):
            if event.output is not None:
                final_output = event.output

        if isinstance(final_output, dict) and isinstance(final_output.get("report"), ClinicalReport):
            return final_output["report"]

        raise ADKNotAvailableError(
            "ADK workflow run completed but did not return a ClinicalReport output"
        )

    def _import_adk(self):
        try:
            return importlib.import_module("google.adk")
        except Exception as exc:  # pragma: no cover - environment-dependent
            raise ADKNotAvailableError(
                "google-adk runtime is unavailable. Install with: "
                "python3 -m pip install 'google-adk>=2.0.0'"
            ) from exc

    def _build_workflow(self, adk_module):
        Workflow = getattr(adk_module, "Workflow", None)
        workflow_module = getattr(adk_module, "workflow", None)
        start = getattr(workflow_module, "START", None)

        if Workflow is None or start is None:
            raise ADKNotAvailableError(
                "Current google-adk installation does not expose Workflow/START API"
            )

        validate_node = self._node_validate_parse
        classify_node = self._node_classify
        recommend_node = self._node_recommend
        literature_node = self._node_literature
        assemble_node = self._node_assemble

        edges = [
            (start, validate_node),
            (validate_node, classify_node),
            (classify_node, recommend_node),
            (recommend_node, literature_node),
            (literature_node, assemble_node),
        ]

        return Workflow(
            name="pharmagenomics_pipeline_adk",
            description="ADK workflow for variant-to-report pipeline",
            edges=edges,
        )

    def _build_runner(self, adk_module, workflow):
        Runner = getattr(adk_module, "Runner", None)
        sessions_module = importlib.import_module("google.adk.sessions")
        InMemorySessionService = getattr(sessions_module, "InMemorySessionService", None)

        if Runner is None or InMemorySessionService is None:
            raise ADKNotAvailableError("ADK Runner or InMemorySessionService not found")

        return Runner(
            app_name="pharmagenomics-advisor",
            node=workflow,
            session_service=InMemorySessionService(),
            auto_create_session=True,
        )

    def _node_validate_parse(
        self,
        vcf_path: str,
        session_id: str,
        check_ollama: bool = False,
    ) -> dict[str, Any]:
        warnings: list[dict] = []
        if check_ollama:
            try:
                check_ollama_ready()
            except Exception as exc:  # pragma: no cover - environment dependent
                warnings.append({"stage": "ollama_check", "message": str(exc)})

        vcf_file = Path(vcf_path)
        raw_text = vcf_file.read_text(encoding="utf-8")
        validation = self._orchestrator.security.validate(raw_text, session_id=session_id)
        if not validation.is_valid:
            raise ValueError(
                f"Security validation failed: {validation.error_message} "
                f"({validation.rejected_reason})"
            )

        parse_result = self._orchestrator.parser.parse(vcf_file)
        return {
            "parse_result": parse_result,
            "warnings": warnings,
            "session_id": session_id,
            "started_at": time.perf_counter(),
        }

    async def _node_classify(self, node_input: dict[str, Any]) -> dict[str, Any]:
        parse_result = node_input["parse_result"]
        warnings = node_input.get("warnings", [])
        classifications = []
        provenance = []

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

            clinvar = await orchestrator_module.lookup_clinvar(variant)
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

            classification_value, confidence = _rule_based_acmg(variant)
            therapeutic_relevance = _egfr_therapeutic_relevance(variant)
            functional_status = _tp53_functional_status(variant)

            classification = VariantClassification(
                gene=variant.gene,
                variant_description=_variant_description(variant),
                chromosome=variant.chromosome,
                position=variant.position,
                ref_allele=variant.ref_allele,
                alt_allele=variant.alt_allele,
                classification=classification_value,
                confidence=confidence,
                evidence_references=evidence or ["Rule-based assessment from local knowledge base"],
                therapeutic_relevance=therapeutic_relevance,
                functional_status=functional_status,
                data_sources_queried=data_sources,
                limitations=limitations,
            )

            classifications.append(classification)
            provenance.append(
                ProvenanceMetadata(
                    source_agent=f"{variant.gene.lower()}_agent",
                    data_sources_queried=classification.data_sources_queried,
                    confidence=classification.confidence,
                )
            )

        node_input["warnings"] = warnings
        node_input["classifications"] = classifications
        node_input["provenance"] = provenance
        return node_input

    async def _node_recommend(self, node_input: dict[str, Any]) -> dict[str, Any]:
        parse_result = node_input["parse_result"]
        classifications = node_input.get("classifications", [])
        warnings = node_input.get("warnings", [])
        recommendations = []

        classified_by_key = {
            (c.chromosome, c.position, c.ref_allele, c.alt_allele): c
            for c in classifications
        }

        for variant in parse_result.variants:
            key = (variant.chromosome, variant.position, variant.ref_allele, variant.alt_allele)
            classification = classified_by_key.get(key)
            if classification is None:
                continue
            if classification.classification not in ACTIONABLE_CLASSES:
                continue

            variant_start_count = len(recommendations)
            cpic_result = await orchestrator_module.lookup_cpic_guidelines(variant.gene or "")
            pharmgkb_result = await orchestrator_module.lookup_pharmgkb_annotations(variant.gene or "")

            seen_keys: set[tuple[str, str]] = set()

            if cpic_result.get("status") == "success":
                for row in cpic_result.get("results", []):
                    row_key = (row.get("gene", ""), row.get("drug", ""))
                    if row_key in seen_keys:
                        continue
                    seen_keys.add(row_key)
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
                    row_key = (row.get("gene", ""), row.get("drug", ""))
                    if row_key in seen_keys:
                        continue
                    seen_keys.add(row_key)
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

            if len(recommendations) == variant_start_count:
                warnings.append(
                    {
                        "stage": "pgx",
                        "variant": f"{variant.chromosome}:{variant.position}",
                        "message": "No established pharmacogenomic guideline found",
                    }
                )

        node_input["warnings"] = warnings
        node_input["recommendations"] = recommendations
        return node_input

    def _node_literature(self, node_input: dict[str, Any]) -> dict[str, Any]:
        recommendations = node_input.get("recommendations", [])
        provenance = node_input.get("provenance", [])

        if recommendations:
            literature = self._orchestrator.literature.retrieve(recommendations)
            provenance.append(
                ProvenanceMetadata(
                    source_agent="literature_rag",
                    data_sources_queried=["local_literature_corpus"],
                    confidence=ConfidenceLevel.MODERATE,
                )
            )
        else:
            literature = []

        node_input["literature"] = literature
        node_input["provenance"] = provenance
        return node_input

    def _node_assemble(self, node_input: dict[str, Any]) -> dict[str, Any]:
        parse_result = node_input["parse_result"]
        started_at = node_input.get("started_at", time.perf_counter())
        report = ClinicalReport(
            total_execution_time_seconds=time.perf_counter() - started_at,
            variant_summary=parse_result.variants,
            classifications=node_input.get("classifications", []),
            drug_recommendations=node_input.get("recommendations", []),
            literature_evidence=node_input.get("literature", []),
            provenance=node_input.get("provenance", []),
            warnings=node_input.get("warnings", []),
        )
        report.markdown_summary = render_markdown_report(report)
        return {"report": report}
