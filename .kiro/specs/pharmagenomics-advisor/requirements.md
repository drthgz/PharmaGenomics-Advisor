# Requirements Document

## Introduction

PharmaGenomics Advisor is a Multi-Agent Precision Medicine Pipeline built as a capstone project for the Kaggle 5-Day AI Agents Intensive Vibe Coding competition. The system extends a prior cancer genomics variant interpretation project into a complete clinical decision support pipeline: from variant parsing through ACMG classification to pharmacogenomics-informed drug recommendations and treatment plans.

The pipeline uses Google ADK 2.0 graph workflows, MCP servers for external knowledge bases (ClinVar, CPIC, PharmGKB), runs fully locally via Ollama (zero API keys), and incorporates PHI security guardrails and Agents CLI lifecycle management.

## Glossary

- **Supervisor_Agent**: The top-level ADK 2.0 graph workflow agent that orchestrates all specialized sub-agents and controls pipeline execution flow
- **BRCA_Agent**: A specialized sub-agent responsible for interpreting BRCA1/BRCA2 gene variants associated with hereditary breast/ovarian cancer
- **EGFR_Agent**: A specialized sub-agent responsible for interpreting EGFR gene variants associated with non-small-cell lung cancer
- **TP53_Agent**: A specialized sub-agent responsible for interpreting TP53 tumor suppressor gene variants associated with Li-Fraumeni syndrome and multiple cancers
- **PGx_Drug_Advisor**: A specialized sub-agent that maps classified variants to pharmacogenomics-informed drug recommendations using CPIC guidelines
- **Literature_RAG_Agent**: A specialized sub-agent that retrieves and synthesizes relevant biomedical literature to provide evidence-based context for recommendations
- **MCP_Server**: A Model Context Protocol server that exposes external knowledge bases as tool endpoints accessible to agents
- **ClinVar_MCP**: An MCP server providing access to ClinVar variant clinical significance data via NCBI E-utilities
- **CPIC_MCP**: An MCP server providing access to Clinical Pharmacogenetics Implementation Consortium guidelines for gene-drug interactions
- **PharmGKB_MCP**: An MCP server providing access to PharmGKB pharmacogenomics clinical annotations
- **VCF**: Variant Call Format — a standard bioinformatics file format for storing gene sequence variations
- **ACMG_Classification**: American College of Medical Genetics classification system for variant pathogenicity (Pathogenic, Likely Pathogenic, VUS, Likely Benign, Benign)
- **ADK**: Google Agent Development Kit version 2.0 — framework for building multi-agent systems with graph-based workflows
- **Ollama**: A local large language model runtime that enables inference without external API calls
- **PHI**: Protected Health Information — sensitive patient data requiring security controls under healthcare regulations
- **PGx**: Pharmacogenomics — the study of how genes affect individual drug responses
- **Agents_CLI**: Google Agents Command Line Interface for agent lifecycle management (creation, testing, deployment)
- **Vector_Store**: A local embedding-based document store used by the Literature_RAG_Agent to retrieve relevant biomedical abstracts via semantic similarity search
- **Pipeline**: The end-to-end processing flow from VCF input through variant classification to drug recommendations and treatment plan output
- **Clinical_Report**: The unified JSON output document produced by the Supervisor_Agent at the end of a pipeline run, containing all findings, evidence, and metadata

## Requirements

### Requirement 1: VCF Variant Parsing and Validation

**User Story:** As a clinical genomicist, I want to submit VCF files containing patient variants, so that the system can extract and validate variant data for downstream analysis.

#### Acceptance Criteria

1. WHEN a VCF file is submitted, THE Pipeline SHALL parse all variant records and extract chromosome, position, reference allele, alternate allele, and quality fields, completing parsing within 30 seconds for files containing up to 10,000 variant records
2. WHEN a VCF file contains variants annotated in the INFO or ANN field as belonging to BRCA1, BRCA2, EGFR, or TP53 genes, THE Pipeline SHALL route those variants to the corresponding specialized agent (BRCA_Agent for BRCA1/BRCA2, EGFR_Agent for EGFR, TP53_Agent for TP53)
3. IF a submitted file does not conform to VCF 4.x format specification, THEN THE Pipeline SHALL return a validation error indicating the malformed field name and line number where parsing failed
4. IF a VCF file contains zero parseable variant records, THEN THE Pipeline SHALL return an error stating no variants were found in the submitted file
5. THE VCF_Parser SHALL format parsed variant data back into valid VCF record strings conforming to VCF 4.x column structure (CHROM, POS, ID, REF, ALT, QUAL, FILTER, INFO)
6. THE VCF_Parser SHALL produce identical values for chromosome, position, reference allele, alternate allele, and quality fields when a valid VCF record is parsed, formatted, and parsed again (round-trip equivalence)
7. IF a VCF file contains variants not annotated as belonging to BRCA1, BRCA2, EGFR, or TP53, THEN THE Pipeline SHALL include those variants in the parsed output with a status of "unrouted" and exclude them from specialized agent dispatch
8. IF a submitted VCF file exceeds 10,000 variant records, THEN THE Pipeline SHALL reject the file with an error indicating the variant count exceeds the maximum supported limit

### Requirement 2: Multi-Agent Supervisor Orchestration

**User Story:** As a clinical genomicist, I want the system to automatically coordinate specialist agents to analyze my variants, so that I receive comprehensive results without manually managing each analysis step.

#### Acceptance Criteria

1. THE Supervisor_Agent SHALL implement an ADK 2.0 graph workflow that defines execution order: VCF parsing → variant classification → drug recommendation → literature evidence → treatment plan synthesis
2. WHEN a set of validated variants is ready for classification, THE Supervisor_Agent SHALL dispatch each variant to the appropriate gene-specific agent (BRCA_Agent, EGFR_Agent, or TP53_Agent) based on gene annotation, and SHALL exclude variants whose gene is not among the supported set (BRCA1, BRCA2, EGFR, TP53), recording excluded variants with the reason "unsupported gene" in the final report
3. WHEN all gene-specific agents have returned classifications, THE Supervisor_Agent SHALL dispatch pathogenic and likely pathogenic variants to the PGx_Drug_Advisor for drug recommendation, and SHALL include VUS, Likely Benign, and Benign classifications in the final report without drug recommendation processing
4. WHEN drug recommendations are generated, THE Supervisor_Agent SHALL dispatch them to the Literature_RAG_Agent for evidence contextualization
5. IF a sub-agent fails to respond within 60 seconds or returns an error response, THEN THE Supervisor_Agent SHALL retry the request once, and IF the retry also fails or times out within 60 seconds, THEN THE Supervisor_Agent SHALL log the failure reason, mark that agent's result as unavailable, and continue the pipeline with remaining results
6. THE Supervisor_Agent SHALL produce a unified clinical report combining all sub-agent outputs into a single structured JSON document

### Requirement 3: Gene-Specific Variant Classification

**User Story:** As a clinical genomicist, I want variants classified according to ACMG/AMP guidelines by gene-specialized agents, so that classifications reflect gene-specific biology and clinical evidence.

#### Acceptance Criteria

1. WHEN the BRCA_Agent receives a BRCA1 or BRCA2 variant, THE BRCA_Agent SHALL classify the variant using ACMG/AMP 5-tier criteria (Pathogenic, Likely Pathogenic, VUS, Likely Benign, Benign)
2. WHEN the EGFR_Agent receives an EGFR variant, THE EGFR_Agent SHALL classify the variant using ACMG/AMP 5-tier criteria and annotate therapeutic relevance as one of: "TKI-sensitive", "TKI-resistant", "unknown therapeutic relevance"
3. WHEN the TP53_Agent receives a TP53 variant, THE TP53_Agent SHALL classify the variant using ACMG/AMP 5-tier criteria and annotate functional status as one of: "gain-of-function", "loss-of-function", "undetermined"
4. WHEN classifying a variant, each gene-specific agent SHALL query the ClinVar_MCP server to retrieve existing clinical significance assertions, with a timeout of 30 seconds per query
5. THE gene-specific agents SHALL include confidence level (High, Moderate, Low) and at least one supporting evidence reference with each classification
6. IF the ClinVar_MCP server is unreachable or does not respond within 30 seconds, THEN the gene-specific agent SHALL classify using local knowledge only and flag the result as "limited evidence — ClinVar unavailable"
7. IF a gene-specific agent receives a variant whose gene does not match its specialization, THEN the agent SHALL reject the request with an error indicating a gene mismatch

### Requirement 4: Pharmacogenomics Drug Recommendation

**User Story:** As a clinical pharmacist, I want to receive evidence-based drug recommendations informed by a patient's genetic variants, so that I can optimize drug selection and dosing.

#### Acceptance Criteria

1. WHEN the PGx_Drug_Advisor receives a pathogenic or likely pathogenic variant classification, THE PGx_Drug_Advisor SHALL query the CPIC_MCP server for applicable gene-drug interaction guidelines within 30 seconds
2. WHEN CPIC guidelines are found for a variant, THE PGx_Drug_Advisor SHALL return drug name, recommended action (avoid, dose adjustment, standard dosing, alternative therapy), and CPIC evidence level for each applicable gene-drug pair, up to a maximum of 10 recommendations per variant
3. WHEN the PGx_Drug_Advisor receives an EGFR variant annotated with therapeutic relevance by the EGFR_Agent, THE PGx_Drug_Advisor SHALL query the PharmGKB_MCP server for targeted therapy clinical annotations
4. THE PGx_Drug_Advisor SHALL return recommendations in a structured JSON format containing: drug name, gene, variant, recommendation action, evidence level, guideline source URL, and contraindications, ordered by evidence level from strongest to weakest
5. IF no CPIC or PharmGKB guidelines exist for a given variant, THEN THE PGx_Drug_Advisor SHALL return a "no established pharmacogenomic guideline" status with suggested next steps including: referral to genetic counselor, manual literature review, and clinical trial eligibility search
6. IF the CPIC_MCP or PharmGKB_MCP server does not respond within 30 seconds, THEN THE PGx_Drug_Advisor SHALL report the service unavailability, flag recommendations as "limited evidence — external source unavailable", and provide recommendations from local cached guidelines only

### Requirement 5: Literature RAG Evidence Retrieval

**User Story:** As a clinical genomicist, I want each recommendation supported by relevant biomedical literature, so that I can verify the evidence basis and communicate findings to patients.

#### Acceptance Criteria

1. WHEN the Literature_RAG_Agent receives a drug recommendation and variant classification, THE Literature_RAG_Agent SHALL retrieve the top 5 most relevant biomedical abstracts from the local vector store, ranked by cosine similarity score (range 0.0 to 1.0) with a minimum threshold of 0.5
2. THE Literature_RAG_Agent SHALL rank retrieved literature by relevance score as primary criterion and publication year as secondary criterion, prioritizing publications within the last 5 years
3. THE Literature_RAG_Agent SHALL return for each citation: title, authors, journal, year, DOI, relevance score, and a 2-3 sentence evidence summary
4. IF the local vector store contains fewer than 3 documents with relevance score above 0.5 for a query, THEN THE Literature_RAG_Agent SHALL indicate "limited literature evidence" and suggest manual PubMed review
5. THE Literature_RAG_Agent SHALL generate a synthesis paragraph of no more than 200 words summarizing the overall evidence landscape for the variant-drug combination
6. IF the local vector store is unavailable or fails to respond within 15 seconds, THEN THE Literature_RAG_Agent SHALL return an error status indicating "literature search unavailable" and recommend manual PubMed consultation

### Requirement 6: MCP Server Implementation

**User Story:** As a developer, I want external genomics knowledge bases exposed as MCP servers, so that agents can query structured data through a standardized protocol.

#### Acceptance Criteria

1. THE ClinVar_MCP SHALL expose a tool endpoint that accepts a variant identifier (gene, chromosome, position, ref, alt) and returns ClinVar clinical significance, review status, and submission count
2. THE CPIC_MCP SHALL expose a tool endpoint that accepts a gene name and returns all CPIC gene-drug guidelines including recommendation strength and phenotype-based dosing
3. THE PharmGKB_MCP SHALL expose a tool endpoint that accepts a gene name or variant ID and returns clinical annotations including evidence level, drug associations, and phenotype categories
4. WHEN the ClinVar_MCP receives a query, THE ClinVar_MCP SHALL call NCBI E-utilities REST API with a timeout of 30 seconds and transform the XML response into structured JSON
5. THE CPIC_MCP SHALL serve guidelines from locally cached CPIC JSON data files, versioned to the latest available CPIC release at build time
6. THE PharmGKB_MCP SHALL serve annotations from locally cached PharmGKB TSV data files downloaded during project setup
7. IF an MCP server receives a malformed query missing required fields, THEN the MCP server SHALL return a structured error response indicating the missing parameters
8. IF the NCBI E-utilities API does not respond within 30 seconds or returns an HTTP error, THEN the ClinVar_MCP SHALL return a structured error response indicating the upstream service failure
9. IF a valid query returns no matching records from the data source, THEN the MCP server SHALL return an empty results array with a status of "no records found"

### Requirement 7: Local Inference via Ollama

**User Story:** As a developer deploying in restricted environments, I want the entire pipeline to run locally without external API keys or accounts, so that I can demonstrate and use the system without cloud dependencies.

#### Acceptance Criteria

1. THE Pipeline SHALL use Ollama as the sole LLM inference runtime, requiring no external API keys or cloud accounts for model inference (note: MCP servers for ClinVar require network access to NCBI APIs)
2. THE Pipeline SHALL support MedGemma or Gemma 3 models running on Ollama for all agent reasoning tasks
3. WHEN the Pipeline starts, THE Pipeline SHALL verify Ollama connectivity and model availability within 10 seconds, reporting a clear error message naming the missing model if the required model is not pulled
4. THE Pipeline SHALL provide a setup script that installs Ollama and pulls the required model with a single command
5. IF Ollama is not running when the Pipeline starts, THEN THE Pipeline SHALL display instructions for starting the Ollama service including the exact command to run
6. THE Pipeline SHALL function with Ollama running on localhost port 11434 (default) or a user-configurable port via environment variable

### Requirement 8: PHI Security and Guardrails

**User Story:** As a healthcare compliance officer, I want the system to protect patient data and enforce security controls, so that sensitive genomic information is handled responsibly.

#### Acceptance Criteria

1. THE Pipeline SHALL validate all user inputs against injection patterns (SQL injection, prompt injection, command injection) before passing data to agents or MCP servers, rejecting inputs that match known attack signatures
2. THE Pipeline SHALL detect and refuse to process any input containing identifiable patient information (names matching common name patterns, dates of birth in standard formats, medical record numbers matching MRN patterns) unless explicitly configured for clinical use via an environment variable
3. THE Pipeline SHALL maintain an append-only audit log recording: ISO 8601 timestamp, agent name, action type, SHA-256 input hash, and SHA-256 output hash for every agent invocation
4. WHILE processing variant data, THE Pipeline SHALL keep all data in memory only and SHALL NOT persist raw genomic data to disk unless the user explicitly enables data persistence via configuration flag
5. IF an agent receives input exceeding 10,000 characters, THEN THE Pipeline SHALL reject the input with a size limit error before forwarding to the model
6. THE Pipeline SHALL enforce a rate limit of 100 requests per minute per session, returning an HTTP 429 status with retry-after header when exceeded

### Requirement 9: Clinical Report Generation

**User Story:** As a clinical genomicist, I want a unified clinical report summarizing all findings, so that I can review the complete analysis in a single document.

#### Acceptance Criteria

1. WHEN all pipeline stages complete, THE Supervisor_Agent SHALL generate a structured clinical report in JSON format containing sections: patient variant summary, ACMG classifications, drug recommendations, literature evidence, and pipeline metadata including total execution time
2. THE clinical report SHALL include a human-readable markdown summary section suitable for clinical review, limited to 1,000 words
3. THE clinical report SHALL include provenance metadata for each finding: source agent name, data sources queried (list of MCP servers called), confidence level, and ISO 8601 timestamp
4. IF any pipeline stage produced an error or degraded result, THEN THE clinical report SHALL include a warnings section listing each affected finding with its limitation description and the stage that failed
5. THE clinical report JSON schema SHALL be parseable back into component objects (round-trip property: serialize → deserialize → serialize produces identical JSON)
6. THE clinical report SHALL be written to the output directory as both a JSON file and a companion markdown file

### Requirement 10: Agents CLI Integration and Deployment

**User Story:** As a developer, I want to manage the agent lifecycle through Agents CLI, so that I can create, test, and deploy agents using standardized tooling.

#### Acceptance Criteria

1. THE Pipeline SHALL be structured as an Agents CLI compatible project with proper directory layout (agent.yaml, tools/, tests/) and configuration files
2. THE Pipeline SHALL include Agents CLI commands for: creating new agents, running agents locally, and running integration tests
3. WHEN a developer runs the test command, THE Pipeline SHALL execute all agent unit tests and report pass/fail status with coverage metrics, completing within 5 minutes for the full suite
4. THE Pipeline SHALL include a demonstration script that processes a sample VCF file through the complete pipeline and produces a clinical report within 5 minutes on hardware with at least 16GB RAM
5. THE Pipeline SHALL include a README documenting: system requirements (OS, RAM, GPU), installation steps, Ollama setup, sample usage with expected output, and architecture overview with diagrams

### Requirement 11: Capstone Deliverable Compliance

**User Story:** As a competition participant, I want the project to meet all Kaggle capstone requirements, so that my submission is eligible for judging.

#### Acceptance Criteria

1. THE Pipeline SHALL demonstrate at least 4 of the 6 course concepts: Multi-agent system (ADK), MCP Server, Security features, and Agent skills (Agents CLI)
2. THE Pipeline SHALL include documentation suitable for a Kaggle writeup of 2,500 words or fewer covering: problem statement, architecture, implementation details, and results
3. THE Pipeline SHALL be deployable from a public GitHub repository with all dependencies pinned in requirements.txt or pyproject.toml and setup instructions documented
4. THE Pipeline SHALL include a demonstration workflow completable within 5 minutes suitable for video recording, starting from a cold Ollama pull through to clinical report output
5. THE Pipeline SHALL operate in the "Agents for Good" track by addressing precision medicine accessibility through local-first, zero-cost genomic analysis
