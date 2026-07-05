"""ADK-backed workflow runner for PharmaGenomics Advisor.

This module adds an explicit Google ADK execution path while preserving the
existing deterministic pipeline behavior.
"""

from __future__ import annotations

import importlib
import time
from pathlib import Path
from typing import Any

from src.infrastructure.ollama_check import check_ollama_ready
from src.models import (
    ClinicalReport,
    ProvenanceMetadata,
    RouteStatus,
)
from src.pipeline.orchestrator import (
    ACTIONABLE_CLASSES,
    PipelineOrchestrator,
    _agent_name_for_gene,
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
        try:
            genai_types = importlib.import_module("google.genai.types")
        except ImportError as exc:  # pragma: no cover - environment-specific
            raise ADKNotAvailableError(
                "google-genai runtime is unavailable. Install with: "
                "python3 -m pip install 'google-adk>=2.0.0'"
            ) from exc
        adk = self._import_adk()
        workflow = self._build_workflow(adk)
        runner = self._build_runner(adk, workflow)

        user_message = genai_types.UserContent(parts=[genai_types.Part.from_text(text="run pipeline")])
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

            classification = await self._orchestrator._classify_variant_async(variant, warnings)
            classifications.append(classification)
            provenance.append(
                ProvenanceMetadata(
                    source_agent=_agent_name_for_gene(variant.gene),
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

            recommendations.extend(
                await self._orchestrator._recommend_drugs_async(variant, classification, warnings)
            )

        node_input["warnings"] = warnings
        node_input["recommendations"] = recommendations
        return node_input

    def _node_literature(self, node_input: dict[str, Any]) -> dict[str, Any]:
        recommendations = node_input.get("recommendations", [])
        provenance = node_input.get("provenance", [])

        if recommendations:
            literature, literature_provenance = self._orchestrator._retrieve_literature(recommendations)
            provenance.append(literature_provenance)
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
        self._orchestrator.security.audit(
            "supervisor",
            "assemble_report",
            {"workflow": "adk", "started_at": started_at},
            report,
        )
        return {"report": report}
