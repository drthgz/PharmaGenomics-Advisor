#!/usr/bin/env python3
"""CLI demo entrypoint for PharmaGenomics Advisor."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.pipeline.orchestrator import PipelineOrchestrator


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
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    orchestrator = PipelineOrchestrator(check_ollama=args.check_ollama)
    report = orchestrator.run(vcf_path=args.vcf, session_id=args.session_id)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "report.json"
    md_path = output_dir / "report.md"

    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )
    md_path.write_text(report.markdown_summary, encoding="utf-8")

    print("PharmaGenomics Advisor demo completed")
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
