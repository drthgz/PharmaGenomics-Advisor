# Implementation Plan: PharmaGenomics Advisor

## Overview

This plan implements the PharmaGenomics Advisor multi-agent precision medicine pipeline using Google ADK 2.0, FastMCP servers, Ollama for local inference, and ChromaDB for RAG. Tasks are ordered for maximum deliverability within the 11-day capstone timeline: core infrastructure first, then agent logic, then integration and polish. Each task is sized for 1-3 hours.

## Tasks

- [ ] 1. Project scaffolding, data models, and configuration
  - [ ] 1.1 Create project directory structure and configuration files
    - Create `pyproject.toml` with pinned dependencies (google-adk, fastmcp, pydantic, chromadb, hypothesis, pytest, pytest-asyncio, pytest-cov, sentence-transformers, httpx)
    - Create directory structure: `src/parsers/`, `src/security/`, `src/pipeline/`, `agents/brca_agent/`, `agents/egfr_agent/`, `agents/tp53_agent/`, `agents/pgx_advisor/`, `agents/literature_rag/`, `mcp_servers/`, `tests/unit/`, `tests/integration/`, `tests/properties/`, `data/cpic/`, `data/pharmgkb/`, `data/sample_vcf/`
    - Create `agent.yaml` for Agents CLI compatibility
    - Create `.env.example` with configurable values (OLLAMA_PORT, PHI_CLINICAL_USE, DATA_PERSISTENCE)
    - _Requirements: 10.1, 7.6, 11.3_

  - [ ] 1.2 Implement Pydantic data models and enums
    - Create `src/models.py` with all data models from design: `Variant`, `ParseResult`, `VariantClassification`, `DrugRecommendation`, `LiteratureCitation`, `LiteratureResult`, `ClinicalReport`, `AuditRecord`, `ValidationResult`, `SecurityConfig`, `ProvenanceMetadata`
    - Create all enums: `ACMGClassification`, `ConfidenceLevel`, `TherapeuticRelevance`, `FunctionalStatus`, `RouteStatus`, `RecommendationAction`
    - Create custom exception hierarchy: `PipelineError`, `VCFFormatError`, `VCFEmptyError`, `VCFTooLargeError`, `SecurityValidationError`, `MCPTimeoutError`, `AgentTimeoutError`, `OllamaUnavailableError`
    - _Requirements: 1.5, 3.1, 3.2, 3.3, 4.4, 5.3, 8.3, 9.1_

  - [ ]* 1.3 Write property test for Clinical Report JSON round-trip
    - **Property 18: Clinical Report JSON Round-Trip**
    - **Validates: Requirements 9.5**
    - Use Hypothesis strategies to generate valid `ClinicalReport` objects and verify `to_json → from_json → to_json` produces identical JSON

- [ ] 2. VCF Parser implementation
  - [ ] 2.1 Implement VCF parser core logic
    - Create `src/parsers/vcf_parser.py` with `VCFParser` class
    - Implement `parse(file_path)` method: read file, validate header, parse each variant record extracting CHROM, POS, ID, REF, ALT, QUAL, FILTER, INFO fields
    - Implement `parse_line(line, line_num)` method for single record parsing with validation
    - Implement `format_variant(variant)` method for converting `Variant` back to VCF string
    - Enforce 10,000 variant limit, raise `VCFTooLargeError` if exceeded
    - Raise `VCFFormatError` with field name and line number for malformed records
    - Raise `VCFEmptyError` for files with zero variant records
    - _Requirements: 1.1, 1.3, 1.4, 1.5, 1.8_

  - [ ] 2.2 Implement gene annotation extraction and variant routing
    - Implement INFO/ANN field parsing to extract gene names from VCF annotations
    - Set `route_status` to "routed" for variants in BRCA1, BRCA2, EGFR, TP53
    - Set `route_status` to "unrouted" for all other gene annotations
    - Implement `route_variants(parse_result)` function mapping gene → agent destination
    - _Requirements: 1.2, 1.7_

  - [ ]* 2.3 Write property tests for VCF parser
    - **Property 1: VCF Parse-Format-Parse Round-Trip**
    - **Validates: Requirements 1.5, 1.6**
    - Generate random valid VCF lines, verify parse → format → parse preserves fields

  - [ ]* 2.4 Write property tests for variant routing and error reporting
    - **Property 2: Variant Routing Correctness**
    - **Validates: Requirements 1.2, 1.7, 2.2**
    - **Property 3: VCF Format Validation Error Reporting**
    - **Validates: Requirements 1.3**
    - Verify routing logic and that malformed input produces errors with field name and line number

- [ ] 3. Security layer implementation
  - [ ] 3.1 Implement input validator and PHI detector
    - Create `src/security/input_validator.py` with regex patterns for SQL injection, prompt injection, and command injection detection
    - Create `src/security/phi_detector.py` with patterns for names, dates of birth, and MRN numbers
    - Implement `SecurityConfig` loading from environment variables (`PHI_CLINICAL_USE` env var controls PHI acceptance)
    - Enforce 10,000 character input size limit
    - _Requirements: 8.1, 8.2, 8.5_

  - [ ] 3.2 Implement rate limiter and audit logger
    - Create `src/security/rate_limiter.py` with sliding window rate limiting (100 requests/60 seconds per session), returning HTTP 429 with retry-after header when exceeded
    - Create `src/security/audit_logger.py` with append-only logging: ISO 8601 timestamp, agent name, action type, SHA-256 input hash, SHA-256 output hash
    - _Requirements: 8.3, 8.6_

  - [ ] 3.3 Implement composable SecurityLayer middleware chain
    - Create `src/security/layer.py` with `SecurityLayer` class composing all security components
    - Implement `validate(input_data, session_id)` method running checks in order: size → injection → PHI → rate limit
    - Wire audit logger to record all agent invocations
    - Implement data persistence control (in-memory only by default, configurable via flag)
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_

  - [ ]* 3.4 Write property tests for security layer
    - **Property 13: Injection Pattern Detection**
    - **Validates: Requirements 8.1**
    - **Property 14: PHI Detection and Refusal**
    - **Validates: Requirements 8.2**
    - **Property 15: Audit Log Completeness**
    - **Validates: Requirements 8.3**
    - **Property 16: Input Size Limit Enforcement**
    - **Validates: Requirements 8.5**
    - **Property 17: Rate Limit Enforcement**
    - **Validates: Requirements 8.6**

- [ ] 4. Checkpoint - Core infrastructure validated
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 5. MCP Servers implementation
  - [ ] 5.1 Implement ClinVar MCP server
    - Create `mcp_servers/clinvar_server.py` using FastMCP 2.0
    - Implement `clinvar_variant_lookup(gene, chromosome, position, ref, alt)` tool
    - Query NCBI E-utilities REST API with 30-second timeout via httpx
    - Transform XML response to structured JSON (clinical significance, review status, submission count)
    - Handle timeout → return structured error indicating upstream service failure
    - Handle malformed query → return structured error indicating missing parameters
    - Handle no matching records → return empty results with "no records found" status
    - _Requirements: 6.1, 6.4, 6.7, 6.8, 6.9_

  - [ ] 5.2 Implement CPIC MCP server
    - Create `mcp_servers/cpic_server.py` using FastMCP 2.0
    - Implement `cpic_gene_drug_guidelines(gene)` tool
    - Serve from locally cached CPIC JSON data files in `data/cpic/`
    - Return recommendation strength and phenotype-based dosing
    - Handle malformed query and no records found cases
    - _Requirements: 6.2, 6.5, 6.7, 6.9_

  - [ ] 5.3 Implement PharmGKB MCP server
    - Create `mcp_servers/pharmgkb_server.py` using FastMCP 2.0
    - Implement `pharmgkb_annotations(gene)` tool accepting gene name or variant ID
    - Serve from locally cached PharmGKB TSV data files in `data/pharmgkb/`
    - Return evidence level, drug associations, phenotype categories
    - Handle malformed query and no records found cases
    - _Requirements: 6.3, 6.6, 6.7, 6.9_

  - [ ]* 5.4 Write property tests for MCP servers
    - **Property 11: MCP Malformed Query Rejection**
    - **Validates: Requirements 6.7**
    - **Property 12: MCP Empty Results for No Matches**
    - **Validates: Requirements 6.9**
    - Generate queries with missing required fields, verify structured error response

- [ ] 6. Gene-specific classification agents
  - [ ] 6.1 Implement BRCA Agent
    - Create `agents/brca_agent/agent.py` with ADK 2.0 Agent configuration
    - Set gene-specialized system prompt for BRCA1/BRCA2 variant interpretation
    - Wire `clinvar_variant_lookup` MCP tool for evidence retrieval
    - Implement ACMG 5-tier classification logic via LLM reasoning
    - Include confidence level and evidence references in output
    - Reject variants not matching BRCA1/BRCA2 with gene mismatch error
    - Handle ClinVar unavailability: classify with local knowledge, flag "limited evidence — ClinVar unavailable"
    - _Requirements: 3.1, 3.4, 3.5, 3.6, 3.7_

  - [ ] 6.2 Implement EGFR Agent
    - Create `agents/egfr_agent/agent.py` with ADK 2.0 Agent configuration
    - Set gene-specialized system prompt for EGFR variant interpretation
    - Wire `clinvar_variant_lookup` MCP tool
    - Implement ACMG classification plus therapeutic relevance annotation (TKI-sensitive, TKI-resistant, unknown therapeutic relevance)
    - Reject variants not matching EGFR gene
    - Handle ClinVar unavailability gracefully
    - _Requirements: 3.2, 3.4, 3.5, 3.6, 3.7_

  - [ ] 6.3 Implement TP53 Agent
    - Create `agents/tp53_agent/agent.py` with ADK 2.0 Agent configuration
    - Set gene-specialized system prompt for TP53 variant interpretation
    - Wire `clinvar_variant_lookup` MCP tool
    - Implement ACMG classification plus functional status annotation (gain-of-function, loss-of-function, undetermined)
    - Reject variants not matching TP53 gene
    - Handle ClinVar unavailability gracefully
    - _Requirements: 3.3, 3.4, 3.5, 3.6, 3.7_

  - [ ]* 6.4 Write property tests for gene-specific agents
    - **Property 5: Classification Output Validity**
    - **Validates: Requirements 3.1, 3.2, 3.3, 3.5**
    - **Property 6: Gene Mismatch Rejection**
    - **Validates: Requirements 3.7**
    - Verify classification output structure and gene mismatch rejection using mocked LLM responses

- [ ] 7. PGx Drug Advisor agent
  - [ ] 7.1 Implement PGx Drug Advisor
    - Create `agents/pgx_advisor/agent.py` with ADK 2.0 Agent configuration
    - Wire CPIC MCP tool for gene-drug guideline queries
    - Wire PharmGKB MCP tool for EGFR TKI-sensitive targeted therapy annotations
    - Implement filtering: only process Pathogenic/Likely Pathogenic classifications
    - Return up to 10 recommendations per variant ordered by evidence level (A → D)
    - Return structured JSON with all required fields (drug_name, gene, variant, action, evidence_level, guideline_source_url, contraindications)
    - Handle no guidelines found: return "no established pharmacogenomic guideline" with suggested next steps
    - Handle MCP service unavailability: flag "limited evidence — external source unavailable", use local cached guidelines
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_

  - [ ]* 7.2 Write property tests for PGx Drug Advisor
    - **Property 4: Classification Filtering for Drug Recommendation**
    - **Validates: Requirements 2.3**
    - **Property 7: Drug Recommendation Output Structure and Ordering**
    - **Validates: Requirements 4.2, 4.4**
    - **Property 8: PharmGKB Query Routing**
    - **Validates: Requirements 4.3**
    - Verify only Pathogenic/Likely Pathogenic variants are processed, output structure is valid, and PharmGKB is queried only for EGFR TKI-sensitive

- [ ] 8. Literature RAG Agent
  - [ ] 8.1 Set up ChromaDB vector store and embedding pipeline
    - Create `src/rag/vector_store.py` with ChromaDB persistent collection setup
    - Implement document ingestion using all-MiniLM-L6-v2 embeddings (384-dim)
    - Create `scripts/ingest_literature.py` to load sample biomedical abstracts into the vector store
    - Implement cosine similarity search with relevance score filtering (threshold ≥ 0.5)
    - _Requirements: 5.1_

  - [ ] 8.2 Implement Literature RAG Agent
    - Create `agents/literature_rag/agent.py` with ADK 2.0 Agent configuration
    - Implement `retrieve_evidence(variant, drug)` method querying ChromaDB
    - Return top 5 citations ranked by relevance (primary) and publication year (secondary, preferring last 5 years)
    - Return citation metadata: title, authors, journal, year, DOI, relevance_score, evidence_summary (2-3 sentences)
    - Generate synthesis paragraph (≤200 words) via LLM summarizing evidence landscape
    - Handle fewer than 3 results above threshold: indicate "limited literature evidence", suggest manual PubMed review
    - Handle vector store unavailability: return "literature search unavailable" within 15 seconds
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_

  - [ ]* 8.3 Write property tests for Literature RAG Agent
    - **Property 9: Literature Retrieval Filtering and Ranking**
    - **Validates: Requirements 5.1, 5.2, 5.3**
    - **Property 10: Literature Synthesis Word Limit**
    - **Validates: Requirements 5.5**
    - Verify citation count ≤ 5, scores ≥ 0.5, correct ordering, and synthesis ≤ 200 words

- [ ] 9. Checkpoint - All agents implemented
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 10. Supervisor graph workflow and pipeline orchestration
  - [ ] 10.1 Implement ADK 2.0 graph workflow
    - Create `src/pipeline/graph.py` with `Workflow` definition
    - Define execution order: validate_input → parse_vcf → route_variants → classify_parallel → filter_classifications → drug_recommendations → literature_evidence → generate_report
    - Implement parallel dispatch for gene-specific agents using `asyncio.gather`
    - Implement 60-second timeout per agent with one retry on failure
    - On double failure: log reason, mark result as "unavailable", continue pipeline
    - Implement classification filtering: forward only Pathogenic/Likely Pathogenic to PGx, include VUS/Likely Benign/Benign in report
    - Record excluded variants (unsupported gene) with reason "unsupported gene" in final report
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_

  - [ ] 10.2 Implement Ollama connectivity check and configuration
    - Create `src/infrastructure/ollama_check.py`
    - Verify Ollama connectivity and model availability within 10 seconds at startup
    - Report clear error naming the missing model if not pulled
    - Display instructions for starting Ollama service if not running
    - Support configurable port via `OLLAMA_PORT` environment variable (default 11434)
    - _Requirements: 7.1, 7.2, 7.3, 7.5, 7.6_

  - [ ]* 10.3 Write property tests for supervisor orchestration
    - **Property 22: Unified Report Contains All Sub-Agent Outputs**
    - **Validates: Requirements 2.6**
    - **Property 20: Clinical Report Warnings for Degraded Results**
    - **Validates: Requirements 9.4**
    - Verify all successful sub-agent results appear in final report and degraded stages produce warnings

- [ ] 11. Clinical report generation
  - [ ] 11.1 Implement report generator
    - Create `src/pipeline/report.py` with `ReportGenerator` class
    - Implement `generate(pipeline_state)` assembling all sub-agent outputs into `ClinicalReport`
    - Include all required sections: variant_summary, classifications, drug_recommendations, literature_evidence, pipeline metadata (total_execution_time)
    - Include provenance metadata per finding: source_agent, data_sources_queried, confidence, timestamp
    - Include warnings section for any degraded/errored pipeline stages
    - Implement `to_json(report)` and `from_json(json_str)` for round-trip serialization
    - Implement `to_markdown(report)` for human-readable summary (≤1,000 words)
    - Write output to both JSON and companion Markdown files
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6_

  - [ ]* 11.2 Write property tests for clinical report
    - **Property 18: Clinical Report JSON Round-Trip**
    - **Validates: Requirements 9.5**
    - **Property 19: Clinical Report Structure Completeness**
    - **Validates: Requirements 9.1, 9.3**
    - **Property 21: Clinical Report Markdown Word Limit**
    - **Validates: Requirements 9.2**
    - Verify round-trip JSON fidelity, structural completeness, and markdown word limit

- [ ] 12. Checkpoint - Full pipeline functional
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 13. Setup scripts, CLI integration, and demo workflow
  - [ ] 13.1 Create setup script and Ollama model pull automation
    - Create `scripts/setup.sh` (and `scripts/setup.ps1` for Windows) that installs Ollama and pulls required model with a single command
    - Include model verification step (MedGemma or Gemma 3/4 availability check)
    - Create `scripts/download_data.sh` to fetch CPIC JSON and PharmGKB TSV data files
    - _Requirements: 7.4, 10.2_

  - [ ] 13.2 Create demonstration script and sample VCF
    - Create `data/sample_vcf/sample_variants.vcf` with representative BRCA1, EGFR, and TP53 variants
    - Create `scripts/demo.py` that runs the complete pipeline on the sample VCF and writes clinical report output
    - Ensure demo completes within 5 minutes on 16GB RAM hardware
    - Create demonstration workflow suitable for video recording (cold start → report)
    - _Requirements: 10.4, 11.4_

  - [ ] 13.3 Create README and capstone documentation
    - Write comprehensive README documenting: system requirements (OS, RAM, GPU), installation steps, Ollama setup, sample usage with expected output, architecture overview with diagrams
    - Create `docs/kaggle_writeup.md` (≤2,500 words) covering problem statement, architecture, implementation, results
    - Document at least 4 course concepts demonstrated: Multi-agent system (ADK), MCP Server, Security features, Agent skills (Agents CLI)
    - _Requirements: 10.5, 11.1, 11.2, 11.3, 11.5_

- [ ] 14. Final checkpoint - Capstone complete
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design's 22 correctness properties
- Unit tests validate specific examples and edge cases
- The pipeline uses Python throughout: Pydantic v2, FastMCP 2.0, Google ADK 2.0, Hypothesis, pytest
- All LLM inference runs locally via Ollama (zero API keys for model calls; ClinVar MCP requires network)
- Tasks are ordered for deliverability: core infrastructure (days 1-3) → agents (days 4-7) → integration (days 8-9) → polish (days 10-11)

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["1.3", "2.1", "3.1"] },
    { "id": 2, "tasks": ["2.2", "3.2"] },
    { "id": 3, "tasks": ["2.3", "2.4", "3.3"] },
    { "id": 4, "tasks": ["3.4", "5.1", "5.2", "5.3"] },
    { "id": 5, "tasks": ["5.4", "6.1", "6.2", "6.3"] },
    { "id": 6, "tasks": ["6.4", "7.1"] },
    { "id": 7, "tasks": ["7.2", "8.1"] },
    { "id": 8, "tasks": ["8.2"] },
    { "id": 9, "tasks": ["8.3", "10.1", "10.2"] },
    { "id": 10, "tasks": ["10.3", "11.1"] },
    { "id": 11, "tasks": ["11.2", "13.1"] },
    { "id": 12, "tasks": ["13.2", "13.3"] }
  ]
}
```
