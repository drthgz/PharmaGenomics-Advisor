"""Pipeline orchestration module."""

from src.pipeline.orchestrator import (
    PipelineOrchestrator,
    render_html_report,
    render_markdown_report,
)

try:
    from src.pipeline.adk_workflow import ADKNotAvailableError, ADKWorkflowRunner
except (ImportError, ModuleNotFoundError):
    # google-adk or google.genai not installed; define fallback symbols
    class ADKNotAvailableError(RuntimeError):  # type: ignore[no-redef]
        """Raised when Google ADK runtime cannot be imported or used."""

    ADKWorkflowRunner = None  # type: ignore[assignment, misc]

__all__ = [
	"PipelineOrchestrator",
	"ADKWorkflowRunner",
	"ADKNotAvailableError",
    "render_html_report",
	"render_markdown_report",
]
