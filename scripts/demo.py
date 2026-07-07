#!/usr/bin/env python3
"""CLI demo entrypoint for PharmaGenomics Advisor."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.pipeline import ADKNotAvailableError, ADKWorkflowRunner, PipelineOrchestrator

# ─── Logging Configuration ────────────────────────────────────────────────────
# Configure INFO-level logging for agent modules so dispatch and response events
# are printed to stdout during the demo, showcasing the multi-agent architecture.
logging.basicConfig(level=logging.INFO, format="%(message)s")
for _logger_name in ("src.agents.supervisor", "src.agents.message_bus", "src.agents.handlers"):
    logging.getLogger(_logger_name).setLevel(logging.INFO)

# ─── Emoji Prefix Constants ──────────────────────────────────────────────────
PREFIX_AGENT = "🤖"
PREFIX_LLM = "🧠"
PREFIX_REPORT = "📋"


def format_agent_event(message_type: str, sender: str, recipient: str) -> str:
    """Format an agent message as a demo log line with emoji prefix.

    Returns a string containing the PREFIX_AGENT emoji, the message_type value,
    the sender name, and the recipient name in a structured log format.
    """
    return (
        f"{PREFIX_AGENT} DISPATCH: message_type={message_type} "
        f"sender={sender} recipient={recipient}"
    )


def print_report_preview(markdown: str, max_lines: int = 40) -> None:
    """Print the first *max_lines* lines of the markdown report as a preview."""
    lines = markdown.splitlines()[:max_lines]
    print(f"\n{PREFIX_REPORT} ── Report Preview (first {max_lines} lines) ──")
    for line in lines:
        print(f"{PREFIX_REPORT} {line}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run PharmaGenomics Advisor demo pipeline")
    parser.add_argument(
        "--vcf",
        default="data/samples/sample_variants.vcf",
        help="Path to input VCF file",
    )
    parser.add_argument(
        "--output-dir",
        default="output",
        help="Directory for report outputs",
    )
    parser.add_argument(
        "--session-id",
        default="demo-session",
        help="Session id used for security rate limiting",
    )
    parser.add_argument(
        "--check-ollama",
        action="store_true",
        help="Verify Ollama and model availability before running",
    )
    parser.add_argument(
        "--runtime",
        default="local",
        choices=["local", "adk"],
        help="Execution runtime: local orchestrator or ADK workflow",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        if args.runtime == "adk":
            runner = ADKWorkflowRunner(check_ollama=args.check_ollama)
            report = runner.run(vcf_path=args.vcf, session_id=args.session_id)
        else:
            orchestrator = PipelineOrchestrator(check_ollama=args.check_ollama)
            report = orchestrator.run(vcf_path=args.vcf, session_id=args.session_id)
    except ADKNotAvailableError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    # ─── LLM Narrative Display ────────────────────────────────────────────────
    # Iterate classifications and display the LLM-generated clinical narrative
    # for each variant, showcasing the inference client's contribution.
    if report.classifications:
        print(f"\n{PREFIX_LLM} ── LLM-Generated Clinical Narratives ──")
        for cls in report.classifications:
            classification_label = (
                cls.classification.value if cls.classification else "Unavailable"
            )
            print(f"{PREFIX_LLM} [{cls.gene}] Classification: {classification_label}")
            if cls.clinical_narrative:
                print(f"{PREFIX_LLM}   Narrative: {cls.clinical_narrative}")
            else:
                print(f"{PREFIX_LLM}   Narrative: (none generated)")
            print()

    # ─── Agent Event Summary ──────────────────────────────────────────────────
    # Log a summary of agent dispatch/response events. The actual per-message
    # dispatch and response logs are emitted by the MessageBus logger at INFO
    # level during pipeline execution (above). Here we recap the routing.
    if report.classifications:
        print(f"\n{PREFIX_AGENT} ── Agent Communication Events ──")
        for cls in report.classifications:
            # Dispatch event: SupervisorAgent → SpecialistAgent
            print(
                f"{PREFIX_AGENT} DISPATCH: message_type=CLASSIFY_VARIANT "
                f"sender=SupervisorAgent recipient={cls.gene}Agent"
            )
            # Response event: SpecialistAgent → SupervisorAgent
            classification_label = (
                cls.classification.value if cls.classification else "Unavailable"
            )
            print(
                f"{PREFIX_AGENT} RESPONSE: message_type=CLASSIFICATION_RESULT "
                f"sender={cls.gene}Agent classification={classification_label}"
            )
        print()

    # ─── Report Preview ───────────────────────────────────────────────────────
    # Print first 40 lines of the markdown report for a quick in-terminal preview.
    if report.markdown_summary:
        print_report_preview(report.markdown_summary)

    # ─── Write Reports to Disk ────────────────────────────────────────────────
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "report.json"
    md_path = output_dir / "report.md"

    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )
    md_path.write_text(report.markdown_summary, encoding="utf-8")

    # ─── Pipeline Summary Statistics ──────────────────────────────────────────
    # Print summary stats last so they appear after all agent/narrative output,
    # giving the reviewer a clear quantitative overview of what was processed.
    print("\n── Pipeline Summary ──")
    print("PharmaGenomics Advisor demo completed")
    print(f"Runtime: {args.runtime}")
    print(f"Input VCF: {args.vcf}")
    print(f"Variants analyzed: {len(report.variant_summary)}")
    print(f"Classifications: {len(report.classifications)}")
    print(f"Drug recommendations: {len(report.drug_recommendations)}")
    print(f"Literature bundles: {len(report.literature_evidence)}")
    print(f"Warnings: {len(report.warnings)}")
    print(f"JSON report: {json_path}")
    print(f"Markdown report: {md_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
