"""ADK-backed workflow runner for PharmaGenomics Advisor.

This module adds an explicit Google ADK execution path while preserving the
existing deterministic pipeline behavior. Validates ADK 2.x API symbols at
import time and integrates SupervisorAgent message-passing for classification.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import time
from pathlib import Path
from typing import Any

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

logger = logging.getLogger(__name__)


class ADKNotAvailableError(RuntimeError):
    """Raised when Google ADK runtime cannot be imported or used."""


# Required ADK symbols that must exist for the workflow to function
_REQUIRED_ADK_SYMBOLS = {
    "Workflow": ("google.adk", "Workflow"),
    "workflow.START": ("google.adk", "workflow"),
    "Runner": ("google.adk", "Runner"),
    "InMemorySessionService": ("google.adk.sessions", "InMemorySessionService"),
}


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

        # Import types for user message construction
        try:
            from google.genai import types
        except (ImportError, AttributeError) as exc:
            raise ADKNotAvailableError(
                "Missing ADK symbol: google.genai.types. The installed google-adk version may be incompatible."
            ) from exc

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
        """Import and validate all required ADK symbols.

        Validates that google.adk and google.adk.sessions modules can be imported
        and that all required symbols (Workflow, workflow.START, Runner,
        InMemorySessionService) exist.

        Returns:
            The google.adk module.

        Raises:
            ADKNotAvailableError: If any required symbol is missing, with the
                specific symbol name included in the error message.
        """
        # Try to import the base ADK module
        try:
            adk_module = importlib.import_module("google.adk")
        except (ImportError, ModuleNotFoundError) as exc:
            raise ADKNotAvailableError(
                "ADK runtime not available. Install with: pip install 'google-adk>=2.0.0'"
            ) from exc
        except Exception as exc:
            raise ADKNotAvailableError(
                "ADK runtime not available. Install with: pip install 'google-adk>=2.0.0'"
            ) from exc

        # Validate Workflow symbol
        if not hasattr(adk_module, "Workflow"):
            raise ADKNotAvailableError(
                "Missing ADK symbol: Workflow. The installed google-adk version may be incompatible."
            )

        # Validate workflow sub-module and START
        workflow_submodule = getattr(adk_module, "workflow", None)
        if workflow_submodule is None:
            raise ADKNotAvailableError(
                "Missing ADK symbol: workflow. The installed google-adk version may be incompatible."
            )
        if not hasattr(workflow_submodule, "START"):
            raise ADKNotAvailableError(
                "Missing ADK symbol: workflow.START. The installed google-adk version may be incompatible."
            )

        # Validate Runner symbol
        if not hasattr(adk_module, "Runner"):
            raise ADKNotAvailableError(
                "Missing ADK symbol: Runner. The installed google-adk version may be incompatible."
            )

        # Validate InMemorySessionService from google.adk.sessions
        try:
            sessions_module = importlib.import_module("google.adk.sessions")
        except (ImportError, ModuleNotFoundError) as exc:
            raise ADKNotAvailableError(
                "Missing ADK symbol: InMemorySessionService. The installed google-adk version may be incompatible."
            ) from exc
        except Exception as exc:
            raise ADKNotAvailableError(
                "Missing ADK symbol: InMemorySessionService. The installed google-adk version may be incompatible."
            ) from exc

        if not hasattr(sessions_module, "InMemorySessionService"):
            raise ADKNotAvailableError(
                "Missing ADK symbol: InMemorySessionService. The installed google-adk version may be incompatible."
            )

        return adk_module

    def _build_workflow(self, adk_module):
        """Construct the ADK Workflow with all five pipeline stages as distinct nodes.

        Args:
            adk_module: The validated google.adk module.

        Returns:
            A Workflow object with ordered edges connecting the five stages.

        Raises:
            ADKNotAvailableError: If Workflow or START symbols are not accessible.
        """
        Workflow = getattr(adk_module, "Workflow", None)
        workflow_module = getattr(adk_module, "workflow", None)
        start = getattr(workflow_module, "START", None) if workflow_module else None

        if Workflow is None:
            raise ADKNotAvailableError(
                "Missing ADK symbol: Workflow. The installed google-adk version may be incompatible."
            )
        if start is None:
            raise ADKNotAvailableError(
                "Missing ADK symbol: workflow.START. The installed google-adk version may be incompatible."
            )

        # Register all five pipeline stages as distinct callable node functions
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
        """Construct the ADK Runner with InMemorySessionService.

        Args:
            adk_module: The validated google.adk module.
            workflow: The Workflow object to run.

        Returns:
            A Runner instance configured for the workflow.

        Raises:
            ADKNotAvailableError: If Runner or InMemorySessionService symbols are missing.
        """
        Runner = getattr(adk_module, "Runner", None)
        if Runner is None:
            raise ADKNotAvailableError(
                "Missing ADK symbol: Runner. The installed google-adk version may be incompatible."
            )

        try:
            sessions_module = importlib.import_module("google.adk.sessions")
        except (ImportError, ModuleNotFoundError) as exc:
            raise ADKNotAvailableError(
                "Missing ADK symbol: InMemorySessionService. The installed google-adk version may be incompatible."
            ) from exc
        except Exception as exc:
            raise ADKNotAvailableError(
                "Missing ADK symbol: InMemorySessionService. The installed google-adk version may be incompatible."
            ) from exc

        InMemorySessionService = getattr(sessions_module, "InMemorySessionService", None)
        if InMemorySessionService is None:
            raise ADKNotAvailableError(
                "Missing ADK symbol: InMemorySessionService. The installed google-adk version may be incompatible."
            )

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
        """Stage 1: Validate input and parse VCF file.

        Performs security validation and VCF parsing, producing the ParseResult
        that subsequent stages operate on.
        """
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
        """Stage 2: Classify variants using SupervisorAgent message-passing.

        Integrates the SupervisorAgent for agent-based classification of variants
        with supported genes (BRCA1, BRCA2, EGFR, TP53). Falls back to direct
        rule-based classification if the agent pipeline encounters any errors.
        """
        parse_result = node_input["parse_result"]
        warnings = node_input.get("warnings", [])
        classifications = []
        provenance = []

        # Attempt agent-based classification via SupervisorAgent
        agent_classifications = await self._classify_with_supervisor(
            parse_result.variants, warnings
        )

        if agent_classifications is not None:
            # Successfully used SupervisorAgent — map results back
            agent_classified_keys = {
                (c.chromosome, c.position, c.ref_allele, c.alt_allele): c
                for c in agent_classifications
            }

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

                key = (variant.chromosome, variant.position, variant.ref_allele, variant.alt_allele)
                classification = agent_classified_keys.get(key)

                if classification is not None:
                    classifications.append(classification)
                    provenance.append(
                        ProvenanceMetadata(
                            source_agent=f"{variant.gene.lower()}_agent",
                            data_sources_queried=classification.data_sources_queried,
                            confidence=classification.confidence,
                        )
                    )
                else:
                    # Variant not handled by supervisor (unsupported gene) — fallback
                    classification = await self._classify_variant_direct(variant, warnings)
                    if classification:
                        classifications.append(classification)
                        provenance.append(
                            ProvenanceMetadata(
                                source_agent=f"{variant.gene.lower()}_agent",
                                data_sources_queried=classification.data_sources_queried,
                                confidence=classification.confidence,
                            )
                        )
        else:
            # Fallback: direct rule-based classification for all variants
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

                classification = await self._classify_variant_direct(variant, warnings)
                if classification:
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

    async def _classify_with_supervisor(
        self, variants: list, warnings: list[dict]
    ) -> list[VariantClassification] | None:
        """Attempt to classify variants using the SupervisorAgent with message-passing.

        Creates a MessageBus, registers specialist handlers, and delegates
        classification to the SupervisorAgent. Returns None on any failure
        to signal that the caller should fall back to direct classification.

        Args:
            variants: List of Variant objects to classify.
            warnings: Mutable warnings list for logging issues.

        Returns:
            List of VariantClassification objects, or None if agent pipeline fails.
        """
        try:
            from src.agents.message_bus import MessageBus
            from src.agents.handlers import brca_handler, egfr_handler, tp53_handler
            from src.agents.supervisor import SupervisorAgent
            from src.inference.ollama_client import LLMInferenceClient

            # Create message bus and register specialist handlers
            bus = MessageBus()
            bus.register_agent("brca_agent", brca_handler)
            bus.register_agent("egfr_agent", egfr_handler)
            bus.register_agent("tp53_agent", tp53_handler)

            # Create LLM client for narrative generation
            llm_client = LLMInferenceClient()

            # Create supervisor agent
            supervisor = SupervisorAgent(
                bus=bus,
                llm_client=llm_client,
                audit_logger=None,
            )

            # Run agent-based classification
            results = await supervisor.analyze_variants(variants)
            logger.info(
                "SupervisorAgent classified %d variants via message-passing", len(results)
            )
            return results

        except Exception as exc:
            logger.warning(
                "SupervisorAgent classification failed, falling back to direct: %s",
                str(exc),
            )
            warnings.append(
                {
                    "stage": "classify_supervisor",
                    "message": f"Agent-based classification failed: {str(exc)}; using rule-based fallback",
                }
            )
            return None

    async def _classify_variant_direct(
        self, variant: Any, warnings: list[dict]
    ) -> VariantClassification | None:
        """Classify a single variant using direct rule-based logic with ClinVar lookup.

        This is the fallback path used when SupervisorAgent is not available.

        Args:
            variant: A Variant object to classify.
            warnings: Mutable warnings list for logging issues.

        Returns:
            A VariantClassification, or None if the variant cannot be classified.
        """
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

        return classification

    async def _node_recommend(self, node_input: dict[str, Any]) -> dict[str, Any]:
        """Stage 3: Generate drug recommendations based on classifications.

        Queries CPIC and PharmGKB for pharmacogenomic guidelines relevant to
        the classified actionable variants.
        """
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
        """Stage 4: Retrieve literature evidence for recommendations.

        Uses the RAG literature service to find relevant citations for
        the generated drug recommendations.
        """
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
        """Stage 5: Assemble the final ClinicalReport from all pipeline outputs.

        Combines variant summaries, classifications, recommendations, literature
        evidence, and provenance into a unified ClinicalReport with markdown summary.
        """
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
