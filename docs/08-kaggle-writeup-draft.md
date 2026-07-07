# PharmaGenomics Advisor

**Multi-Agent Precision Medicine Pipeline: From Tumor Variants to Actionable Drug Recommendations**

Track: Agents for Good

## 1. Problem Statement

Cancer genomic interpretation is slow, expensive, and difficult to scale. A clinical team often needs to process VCF data, classify variants, review treatment relevance, check published evidence, and produce a report with provenance. In many settings this can take days to weeks.

The challenge is not just one model call. It is an orchestration problem: routing each variant to the right specialist logic, querying multiple knowledge sources, and preserving traceability under strict safety constraints.

PharmaGenomics Advisor addresses this by building a local-first, multi-agent pipeline that turns a VCF file into structured clinical outputs in minutes.

## 2. Why Agents

This problem is naturally decomposed into specialized responsibilities:

- VCF parsing and routing
- Gene-specific interpretation (BRCA/EGFR/TP53)
- Pharmacogenomic recommendation synthesis
- Literature evidence retrieval and summarization
- Final report assembly with provenance

A single monolithic prompt is hard to control and audit. Agent-style orchestration improves modularity, error isolation, and explainability.

## 3. Solution Overview

Input:

- VCF file with annotated variants

Output:

- ACMG-style classifications
- Drug recommendations with evidence levels
- Literature citation bundles and synthesis
- Unified JSON, Markdown, and official-style HTML reports with warnings/provenance

Execution model:

- Local deterministic pipeline runtime (`--runtime local`)
- ADK runtime path (`--runtime adk`) with a Google ADK Workflow + Runner

## 4. Architecture and Technical Design

Core components:

- `src/parsers/vcf_parser.py`: robust parsing + routing
- `src/security/*`: input validation, PHI checks, rate limiting, audit logging
- `src/pipeline/orchestrator.py`: deterministic pipeline orchestration
- `src/pipeline/adk_workflow.py`: ADK Workflow/Runner execution path
- `mcp_servers/*.py`: ClinVar, CPIC, and PharmGKB tool endpoints
- `src/rag/literature_service.py`: local literature evidence layer

Workflow stages:

1. Validate and parse VCF
2. Route supported genes to specialist logic
3. Classify variants with confidence and limitations
4. Generate pharmacogenomic recommendations
5. Retrieve literature evidence bundles
6. Assemble clinical report with provenance

## 5. Course Concepts Demonstrated

This project demonstrates at least three required concepts from the course:

1. Agent / Multi-agent system (ADK) — Code
- ADK Workflow + Runner path implemented in `src/pipeline/adk_workflow.py`

2. MCP Server — Code
- ClinVar/CPIC/PharmGKB MCP server implementations in `mcp_servers/`

3. Security features — Code
- PHI detection, injection checks, rate limiting, audit logging in `src/security/`

Additional concepts also demonstrated:

- Agent skills / Agents CLI style structure (`agent.yaml`, `agents/*`)
- Deployability (setup scripts + reproducible CLI demo)

## 6. Implementation Highlights

### 6.1 Local-first operation

The project is designed to run without mandatory cloud credentials. This keeps costs low and supports reproducible demos.

### 6.2 Dual runtime strategy

- `--runtime local` for deterministic baseline behavior
- `--runtime adk` for explicit ADK workflow execution

### 6.3 Robust failure handling

The pipeline returns useful reports even when some sources are unavailable, and records warnings for degraded paths.
Warnings are rendered in audience-friendly language with:

- message
- impact
- recommended action

### 6.4 Storytelling scenario

A second sample VCF includes:

- EGFR T790M resistant case
- KRAS unrouted gene case
- BRCA1 actionable case

This makes the demo show both positive and edge-case behavior.

## 7. Demo Walkthrough

Suggested demo commands:

```bash
python3 scripts/demo.py --runtime local
python3 scripts/demo.py --runtime adk --vcf data/samples/sample_variants_storytelling.vcf
```

Artifacts to show:

- `output/.../report.json`
- `output/.../report.md`
- `output/.../report.html`

What to highlight in the video:

- Variant counts and routed/unrouted behavior
- Recommendation generation from MCP-backed evidence
- Warning/provenance transparency with actionable guidance
- Runtime switch (`local` vs `adk`) proving integration depth

Recommended media (generated in `docs/assets/`):

- `kaggle-cover.png`
- `pipeline-architecture.png`
- `report-preview.png`
- `youtube-thumbnail.png`

## 8. Results

Current validation:

- Full test suite passes
- Both local and ADK runtime paths execute end-to-end
- Outputs are generated as structured JSON + readable Markdown + stakeholder HTML

This demonstrates operational correctness and reproducibility in a capstone context.

## 9. Safety, Privacy, and Responsible Use

This repository includes safety guardrails:

- Input validation for suspicious patterns
- PHI detection controls
- Rate limiting and audit records

Important disclaimer:

- This is an educational/research prototype and not a substitute for licensed clinical decision support.
- All treatment recommendations require professional review and current guideline confirmation.

## 10. Limitations and Future Improvements

Current limitations:

- Literature layer is lightweight and seeded for reproducible demos
- Some recommendation logic is intentionally simplified

Planned improvements:

- Deeper retrieval stack with benchmarked retrieval quality
- Expanded gene panels and guideline mappings
- Optional web UI for clinician-friendly interaction
- Stronger evaluation metrics and regression datasets

## 11. Why This Fits Agents for Good

PharmaGenomics Advisor targets a healthcare interpretation bottleneck where speed, consistency, and transparency matter. By making a local-first, explainable pipeline accessible, it can help teams prototype precision medicine workflows in resource-constrained settings.

## 12. Reproducibility

```bash
bash scripts/setup.sh
python3 -m pytest tests -v
python3 scripts/demo.py --runtime adk --vcf data/samples/sample_variants_storytelling.vcf
python3 scripts/generate_media_assets.py
```

If you are reviewing this from GitHub, all setup and demo instructions are documented in `README.md` and `docs/05-deployment-guide.md`.
