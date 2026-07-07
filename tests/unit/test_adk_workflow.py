"""Unit tests for ADK workflow compatibility.

Tests that:
- Missing ADK symbols raise ADKNotAvailableError with symbol name
- Successful run returns valid ClinicalReport with populated fields
- Incomplete workflow output raises ADKNotAvailableError
- ADK imports are correctly validated in both available/unavailable scenarios

Requirements: 2.1, 2.3, 2.6
"""

from __future__ import annotations

import importlib
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

from src.pipeline.adk_workflow import ADKNotAvailableError, ADKWorkflowRunner
from src.models import ClinicalReport


class TestMissingADKModule:
    """Test that missing ADK module raises ADKNotAvailableError."""

    def test_missing_adk_module_raises_error(self):
        """When google.adk cannot be imported, ADKNotAvailableError is raised
        with the module name in the message.

        Validates: Requirement 2.1, 2.3
        """
        runner = ADKWorkflowRunner(check_ollama=False)

        def mock_import(name, *args, **kwargs):
            if name == "google.adk":
                raise ImportError("No module named 'google.adk'")
            return importlib.__import__(name, *args, **kwargs)

        with patch("importlib.import_module", side_effect=mock_import):
            with pytest.raises(ADKNotAvailableError) as exc_info:
                runner._import_adk()

        assert "ADK runtime not available" in str(exc_info.value)


class TestMissingADKSymbols:
    """Test that missing individual ADK symbols raise ADKNotAvailableError."""

    def _make_adk_module(self, **overrides):
        """Create a mock ADK module with configurable attributes."""
        adk = MagicMock(spec=[])
        # Set defaults for all required symbols
        adk.Workflow = MagicMock()
        workflow_sub = MagicMock()
        workflow_sub.START = MagicMock()
        adk.workflow = workflow_sub
        adk.Runner = MagicMock()

        # Apply overrides (use None sentinel to delete attributes)
        for key, value in overrides.items():
            if value is None:
                # Remove the attribute so hasattr returns False
                if hasattr(adk, key):
                    delattr(adk, key)
            else:
                setattr(adk, key, value)

        return adk

    def test_missing_workflow_symbol_raises_error(self):
        """When google.adk exists but has no Workflow attribute,
        ADKNotAvailableError is raised with 'Workflow' in the message.

        Validates: Requirement 2.3
        """
        adk_module = self._make_adk_module()
        # Remove Workflow attribute
        del adk_module.Workflow

        def mock_import(name, *args, **kwargs):
            if name == "google.adk":
                return adk_module
            if name == "google.adk.sessions":
                sessions = MagicMock()
                sessions.InMemorySessionService = MagicMock()
                return sessions
            return importlib.__import__(name, *args, **kwargs)

        runner = ADKWorkflowRunner(check_ollama=False)
        with patch("importlib.import_module", side_effect=mock_import):
            with pytest.raises(ADKNotAvailableError) as exc_info:
                runner._import_adk()

        assert "Workflow" in str(exc_info.value)

    def test_missing_runner_symbol_raises_error(self):
        """When google.adk has no Runner attribute,
        ADKNotAvailableError is raised with 'Runner' in the message.

        Validates: Requirement 2.3
        """
        adk_module = self._make_adk_module()
        del adk_module.Runner

        def mock_import(name, *args, **kwargs):
            if name == "google.adk":
                return adk_module
            if name == "google.adk.sessions":
                sessions = MagicMock()
                sessions.InMemorySessionService = MagicMock()
                return sessions
            return importlib.__import__(name, *args, **kwargs)

        runner = ADKWorkflowRunner(check_ollama=False)
        with patch("importlib.import_module", side_effect=mock_import):
            with pytest.raises(ADKNotAvailableError) as exc_info:
                runner._import_adk()

        assert "Runner" in str(exc_info.value)

    def test_missing_session_service_raises_error(self):
        """When google.adk.sessions has no InMemorySessionService attribute,
        ADKNotAvailableError is raised with 'InMemorySessionService' in the message.

        Validates: Requirement 2.3
        """
        adk_module = self._make_adk_module()

        def mock_import(name, *args, **kwargs):
            if name == "google.adk":
                return adk_module
            if name == "google.adk.sessions":
                sessions = MagicMock(spec=[])
                # No InMemorySessionService attribute
                return sessions
            return importlib.__import__(name, *args, **kwargs)

        runner = ADKWorkflowRunner(check_ollama=False)
        with patch("importlib.import_module", side_effect=mock_import):
            with pytest.raises(ADKNotAvailableError) as exc_info:
                runner._import_adk()

        assert "InMemorySessionService" in str(exc_info.value)

    def test_missing_workflow_start_raises_error(self):
        """When google.adk.workflow exists but has no START attribute,
        ADKNotAvailableError is raised with 'workflow.START' in the message.

        Validates: Requirement 2.3
        """
        adk_module = self._make_adk_module()
        # Create workflow submodule without START
        workflow_sub = MagicMock(spec=[])
        adk_module.workflow = workflow_sub

        def mock_import(name, *args, **kwargs):
            if name == "google.adk":
                return adk_module
            if name == "google.adk.sessions":
                sessions = MagicMock()
                sessions.InMemorySessionService = MagicMock()
                return sessions
            return importlib.__import__(name, *args, **kwargs)

        runner = ADKWorkflowRunner(check_ollama=False)
        with patch("importlib.import_module", side_effect=mock_import):
            with pytest.raises(ADKNotAvailableError) as exc_info:
                runner._import_adk()

        assert "workflow.START" in str(exc_info.value)


class TestWorkflowWithoutReportOutput:
    """Test that workflow completing without a ClinicalReport raises error."""

    def test_workflow_without_report_output_raises_error(self):
        """When ADK workflow runs but produces output without a ClinicalReport,
        ADKNotAvailableError is raised indicating missing report.

        Validates: Requirement 2.6
        """
        runner = ADKWorkflowRunner(check_ollama=False)

        # Create a full mock ADK environment
        adk_module = MagicMock()
        workflow_sub = MagicMock()
        workflow_sub.START = MagicMock()
        adk_module.workflow = workflow_sub
        adk_module.Workflow = MagicMock()
        adk_module.Runner = MagicMock()

        sessions_module = MagicMock()
        sessions_module.InMemorySessionService = MagicMock()

        # Mock google.genai.types for user message construction
        types_module = MagicMock()
        types_module.UserContent = MagicMock()
        types_module.Part = MagicMock()
        types_module.Part.from_text = MagicMock(return_value=MagicMock())

        # Create mock runner that yields events without a ClinicalReport
        mock_event = MagicMock()
        mock_event.output = {"some_key": "some_value"}  # No "report" key
        mock_runner_instance = MagicMock()
        mock_runner_instance.run.return_value = [mock_event]
        adk_module.Runner.return_value = mock_runner_instance

        def mock_import(name, *args, **kwargs):
            if name == "google.adk":
                return adk_module
            if name == "google.adk.sessions":
                return sessions_module
            if name == "google.genai.types":
                return types_module
            return importlib.__import__(name, *args, **kwargs)

        with patch("importlib.import_module", side_effect=mock_import):
            # Also patch the google.genai import inside the run method
            with patch.dict("sys.modules", {"google.genai": MagicMock(types=types_module), "google.genai.types": types_module}):
                with pytest.raises(ADKNotAvailableError) as exc_info:
                    runner.run(
                        vcf_path="data/samples/sample_variants.vcf",
                        session_id="test-session",
                    )

        error_msg = str(exc_info.value)
        assert "ClinicalReport" in error_msg or "report" in error_msg.lower()


class TestSuccessfulRun:
    """Test that successful ADK run returns a valid ClinicalReport."""

    def test_successful_run_returns_clinical_report(self):
        """When ADK workflow completes with a ClinicalReport in its output,
        the run method returns a valid ClinicalReport with populated fields.

        Validates: Requirement 2.1, 2.6
        """
        runner = ADKWorkflowRunner(check_ollama=False)

        # Build a valid ClinicalReport
        from src.models import Variant, VariantClassification, ACMGClassification, ConfidenceLevel, TherapeuticRelevance

        test_variant = Variant(
            chromosome="chr17",
            position=7577120,
            id="rs28934576",
            ref_allele="G",
            alt_allele="A",
            quality=99.0,
            filter_status="PASS",
            info={"gene": "TP53"},
            gene="TP53",
        )
        test_classification = VariantClassification(
            gene="TP53",
            variant_description="chr17:7577120 G>A",
            chromosome="chr17",
            position=7577120,
            ref_allele="G",
            alt_allele="A",
            classification=ACMGClassification.PATHOGENIC,
            confidence=ConfidenceLevel.HIGH,
            evidence_references=["ClinVar: Pathogenic (reviewed by expert panel)"],
            therapeutic_relevance=TherapeuticRelevance.UNKNOWN,
        )

        valid_report = ClinicalReport(
            variant_summary=[test_variant],
            classifications=[test_classification],
            markdown_summary="# Clinical Report\n\nTP53 variant classified as Pathogenic.",
        )

        # Create full mock ADK environment
        adk_module = MagicMock()
        workflow_sub = MagicMock()
        workflow_sub.START = MagicMock()
        adk_module.workflow = workflow_sub
        adk_module.Workflow = MagicMock()
        adk_module.Runner = MagicMock()

        sessions_module = MagicMock()
        sessions_module.InMemorySessionService = MagicMock()

        types_module = MagicMock()
        types_module.UserContent = MagicMock()
        types_module.Part = MagicMock()
        types_module.Part.from_text = MagicMock(return_value=MagicMock())

        # Runner yields an event with a proper ClinicalReport
        mock_event = MagicMock()
        mock_event.output = {"report": valid_report}
        mock_runner_instance = MagicMock()
        mock_runner_instance.run.return_value = [mock_event]
        adk_module.Runner.return_value = mock_runner_instance

        def mock_import(name, *args, **kwargs):
            if name == "google.adk":
                return adk_module
            if name == "google.adk.sessions":
                return sessions_module
            if name == "google.genai.types":
                return types_module
            return importlib.__import__(name, *args, **kwargs)

        with patch("importlib.import_module", side_effect=mock_import):
            with patch.dict("sys.modules", {"google.genai": MagicMock(types=types_module), "google.genai.types": types_module}):
                result = runner.run(
                    vcf_path="data/samples/sample_variants.vcf",
                    session_id="test-session",
                )

        # Verify it's a ClinicalReport
        assert isinstance(result, ClinicalReport)
        # Verify populated fields
        assert len(result.variant_summary) > 0
        assert len(result.classifications) > 0
        assert result.markdown_summary != ""
