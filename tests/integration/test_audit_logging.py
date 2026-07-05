"""Integration tests for pipeline audit logging."""

from __future__ import annotations

from pathlib import Path

from src.pipeline.orchestrator import PipelineOrchestrator
from src.security.audit_logger import AuditLogger


def test_pipeline_writes_audit_log_for_agent_invocations(monkeypatch, tmp_path):
    """Pipeline should hash-log core agent invocations."""

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

    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "audit.log"))
    monkeypatch.setattr("src.pipeline.orchestrator.lookup_clinvar", fake_clinvar)
    monkeypatch.setattr("src.pipeline.orchestrator.lookup_cpic_guidelines", fake_cpic)
    monkeypatch.setattr("src.pipeline.orchestrator.lookup_pharmgkb_annotations", fake_pharmgkb)

    orchestrator = PipelineOrchestrator(check_ollama=False)
    orchestrator.run(
        vcf_path=Path("data/samples/sample_variants.vcf"),
        session_id="audit-test",
    )

    records = AuditLogger(str(tmp_path / "audit.log")).read_log()
    agent_names = {record.agent_name for record in records}

    assert "supervisor" in agent_names
    assert "brca_agent" in agent_names
    assert "egfr_agent" in agent_names
    assert "tp53_agent" in agent_names
    assert "pgx_advisor" in agent_names
    assert "literature_rag" in agent_names
