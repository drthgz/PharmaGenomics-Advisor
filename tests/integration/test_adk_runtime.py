"""Integration test for ADK workflow runtime path."""

from __future__ import annotations

from pathlib import Path

from src.pipeline.adk_workflow import ADKWorkflowRunner


def test_adk_runtime_runs_on_sample_vcf(monkeypatch):
    """ADK runtime should execute full pipeline and return a report."""

    async def fake_clinvar(_variant):
        return {"status": "success", "results": []}

    async def fake_cpic(gene: str):
        data = {
            "BRCA1": [
                {
                    "gene": "BRCA1",
                    "drug": "Olaparib",
                    "recommendation": "recommended",
                    "cpic_level": "A",
                    "url": "https://cpicpgx.org/guidelines/",
                    "contraindications": [],
                }
            ],
            "EGFR": [
                {
                    "gene": "EGFR",
                    "drug": "Osimertinib",
                    "recommendation": "recommended",
                    "cpic_level": "A",
                    "url": "https://cpicpgx.org/guidelines/",
                    "contraindications": [],
                }
            ],
        }
        rows = data.get(gene, [])
        if not rows:
            return {"status": "no records found", "results": []}
        return {"status": "success", "results": rows}

    async def fake_pharmgkb(_gene: str):
        return {"status": "no records found", "results": []}

    monkeypatch.setattr("src.pipeline.orchestrator.lookup_clinvar", fake_clinvar)
    monkeypatch.setattr("src.pipeline.orchestrator.lookup_cpic_guidelines", fake_cpic)
    monkeypatch.setattr("src.pipeline.orchestrator.lookup_pharmgkb_annotations", fake_pharmgkb)

    runner = ADKWorkflowRunner(check_ollama=False)
    report = runner.run(vcf_path=Path("data/samples/sample_variants.vcf"), session_id="adk-test")

    assert len(report.variant_summary) == 3
    assert len(report.classifications) == 3
    assert len(report.drug_recommendations) >= 2
    assert report.markdown_summary.startswith("# PharmaGenomics Advisor Clinical Report")
