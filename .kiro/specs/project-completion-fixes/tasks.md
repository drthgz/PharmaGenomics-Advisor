# Implementation Plan: Project Completion Fixes

## Overview

This plan addresses the five integration gaps in the PharmaGenomics Advisor multi-agent system: wiring Ollama LLM inference into specialist agents, fixing ADK API compatibility, implementing real agent-to-agent communication with message passing, creating a Dockerfile for reproducible deployment, and adding a property-based test for the VCF parser. Each task builds incrementally on prior work, starting with data models and infrastructure, then wiring components together, and ending with integration testing.

## Tasks

- [x] 1. Add data models and infrastructure for agent messaging and LLM inference
  - [x] 1.1 Add AgentMessage model and MessageType enum to `src/models.py`
    - Add `MessageType` enum with values CLASSIFY_REQUEST, CLASSIFY_RESPONSE, ERROR
    - Add `AgentMessage` Pydantic model with fields: message_type, sender, recipient, payload (dict), timestamp (datetime with UTC default)
    - Add `clinical_narrative` optional field (str, max_length=2000, default="") to the existing `VariantClassification` model
    - _Requirements: 3.4, 1.3, 1.6_

  - [x] 1.2 Create LLM Inference Client module `src/inference/ollama_client.py`
    - Create `src/inference/__init__.py` with `LLMInferenceClient` export
    - Implement `LLMInferenceClient` class with `__init__(self, model: str | None = None, timeout: float = 30.0)`
    - Read OLLAMA_MODEL env var; default to "medgemma" if unset or empty
    - Implement `generate_narrative(classification: VariantClassification) -> str`
    - Validate that gene, classification, evidence_references, and therapeutic_relevance are all present and non-empty before calling Ollama; return immediately without HTTP call if any is missing
    - Call `ollama.chat()` with a structured prompt including the four required fields
    - Truncate response to 2000 characters maximum
    - On any failure (ConnectionError, timeout, HTTP error, empty response): log WARNING and return placeholder string `"{gene} - {classification} - LLM-generated narrative unavailable"`
    - Enforce 30-second timeout on the Ollama HTTP call
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.7_

  - [x] 1.3 Write property tests for LLM Inference Client
    - **Property 1: Prompt validation guards LLM calls**
    - **Property 2: Narrative truncation bound**
    - **Validates: Requirements 1.2, 1.3**
    - Create `tests/properties/test_llm_inference.py`
    - Use Hypothesis to generate random VariantClassification objects with missing/empty fields
    - Mock `ollama.chat` and verify it is never called when required fields are missing
    - Generate random strings of 1-10000 chars as Ollama responses, verify output ≤ 2000 chars
    - Mark with `@pytest.mark.property` and `@settings(max_examples=100)`

- [x] 2. Implement Agent Message Bus and Specialist Agent Handlers
  - [x] 2.1 Create Message Bus module `src/agents/message_bus.py`
    - Create `src/agents/__init__.py`
    - Implement `MessageBus` class with `register_agent(name, handler)` method
    - Implement `async dispatch(message: AgentMessage, timeout: float = 60.0) -> AgentMessage`
    - Implement `async dispatch_concurrent(messages: list[AgentMessage], timeout: float = 60.0) -> list[AgentMessage]` using `asyncio.gather`
    - On timeout: return an ERROR-type AgentMessage
    - On unknown recipient: log WARNING, return ERROR AgentMessage
    - Log each dispatch and response receipt as structured audit entry with message_type, sender, recipient, timestamp
    - _Requirements: 3.1, 3.2, 3.3, 3.6, 3.7_

  - [x] 2.2 Create Specialist Agent Handlers `src/agents/handlers.py`
    - Implement `async brca_handler(msg: AgentMessage) -> AgentMessage` wrapping existing `_rule_based_acmg` logic for BRCA1/BRCA2
    - Implement `async egfr_handler(msg: AgentMessage) -> AgentMessage` wrapping existing EGFR classification + `_egfr_therapeutic_relevance`
    - Implement `async tp53_handler(msg: AgentMessage) -> AgentMessage` wrapping existing TP53 classification + `_tp53_functional_status`
    - Each handler: deserialize Variant from payload, perform classification, return CLASSIFY_RESPONSE with VariantClassification in payload
    - _Requirements: 3.1, 3.2_

  - [x] 2.3 Create Supervisor Agent Runtime `src/agents/supervisor.py`
    - Implement `SupervisorAgent` class with `__init__(self, bus: MessageBus, llm_client: LLMInferenceClient, audit_logger)`
    - Implement `async analyze_variants(self, variants: list[Variant]) -> list[VariantClassification]`
    - Route variants by gene: BRCA1/BRCA2 → brca_agent, EGFR → egfr_agent, TP53 → tp53_agent
    - Dispatch concurrently via message bus for variants targeting different genes
    - On timeout or error from specialist: fall back to rule-based classification
    - Generate clinical narrative via LLMInferenceClient for each classification
    - Preserve original variant order in returned classifications list
    - _Requirements: 3.1, 3.2, 3.3, 3.5, 3.7_

  - [x] 2.4 Write property tests for agent routing and order preservation
    - **Property 4: Gene-based routing correctness**
    - **Property 5: Order preservation in aggregation**
    - **Validates: Requirements 3.1, 3.5**
    - Create `tests/properties/test_agent_routing.py`
    - Use Hypothesis to generate random Variants with gene in {BRCA1, BRCA2, EGFR, TP53}
    - Verify AgentMessage recipient matches expected specialist agent name
    - Generate random variant lists, run through SupervisorAgent, verify output order matches input order
    - Mark with `@pytest.mark.property` and `@settings(max_examples=100)`

- [x] 3. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Fix ADK API Compatibility and Wire Agent Communication into Pipeline
  - [x] 4.1 Update `src/pipeline/adk_workflow.py` for ADK 2.x compatibility
    - Validate all required ADK symbols (Workflow, workflow.START, Runner, InMemorySessionService) exist before constructing workflow
    - If any symbol is missing, raise `ADKNotAvailableError` with the name of the missing symbol in the error message
    - Ensure the classify node integrates SupervisorAgent message-passing for variant classification
    - Verify the final event output always yields a ClinicalReport or raises ADKNotAvailableError
    - Ensure all five pipeline stages are registered as distinct callable node functions in the Workflow edge definition
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_

  - [x] 4.2 Integrate SupervisorAgent into `src/pipeline/orchestrator.py`
    - Import and instantiate MessageBus, register specialist handlers, create SupervisorAgent
    - Replace direct classification loop with `await supervisor.analyze_variants(routed_variants)`
    - Ensure clinical narratives are attached to each VariantClassification
    - Update `render_markdown_report()` to include clinical_narrative in the markdown output for each classified variant
    - Maintain fallback to existing rule-based logic if message bus dispatch fails
    - _Requirements: 1.6, 3.1, 3.5, 3.7_

  - [x] 4.3 Write unit tests for ADK workflow compatibility
    - Create/update `tests/unit/test_adk_workflow.py`
    - Test that missing ADK symbols raise ADKNotAvailableError with symbol name
    - Test that successful run returns valid ClinicalReport with populated fields
    - Test that incomplete workflow output raises ADKNotAvailableError
    - Mock ADK imports to simulate both available and unavailable scenarios
    - _Requirements: 2.1, 2.3, 2.6_

- [x] 5. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Create Dockerfile and Entrypoint for Reproducible Deployment
  - [x] 6.1 Create `Dockerfile` in project root
    - Use `python:3.10-slim` base image
    - Install all runtime dependencies from pyproject.toml (exclude dev optional-dependencies)
    - Accept `OLLAMA_MODEL` as build argument with default value "medgemma"
    - Install Ollama inside the container during build
    - Pull the model specified by OLLAMA_MODEL during build stage
    - EXPOSE port 11434
    - Copy project source and data files into container
    - _Requirements: 4.1, 4.2, 4.3_

  - [x] 6.2 Create entrypoint script `scripts/entrypoint.sh`
    - Start `ollama serve` in background
    - Poll `http://localhost:11434/api/tags` every 2 seconds, up to 30 seconds
    - If Ollama does not respond within 30 seconds: print error message and exit with code 1
    - Run `python scripts/demo.py --vcf data/samples/sample_variants.vcf --check-ollama`
    - If demo exits with code 0: print the full content of `output/report.md` to stdout, exit 0
    - If demo exits with non-zero code: exit with same non-zero code
    - _Requirements: 4.4, 4.5, 4.6, 4.7_

  - [x] 6.3 Add `.dockerignore` file
    - Exclude `.git/`, `__pycache__/`, `.env`, `output/`, `notebooks/`, `.kiro/`, `tests/`
    - Keep source, data, scripts, agents, docs, and config files
    - _Requirements: 4.1_

- [x] 7. Implement Property-Based Test for VCF Parser Round-Trip
  - [x] 7.1 Create VCF round-trip property test `tests/properties/test_vcf_roundtrip.py`
    - **Property 6: VCF parser round-trip**
    - **Validates: Requirements 5.2**
    - Implement custom `@composite` Hypothesis strategy generating valid Variant objects:
      - Chromosomes: 1-10 character strings
      - Positions: integers between 1 and 2,147,483,647
      - Alleles: strings of 1-50 characters from {A, T, C, G, N}
      - Quality scores: floats between 0.0 and 99999.0
      - INFO field: 0-10 entries, keys 1-20 chars (no semicolons/equals), values 1-50 chars (no semicolons/equals)
    - Test round-trip: `format_variant_to_vcf()` → `parse_vcf_line()` produces Variant with all fields equal to the original
    - Mark with `@pytest.mark.property`
    - Configure `@settings(max_examples=100)` or greater
    - Do NOT suppress Hypothesis shrinking behavior
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_

  - [x] 7.2 Write unit tests for LLM integration edge cases
    - Create `tests/unit/test_llm_inference.py`
    - Test fallback on ConnectionError, HTTP error, timeout, empty response
    - Test default model selection when OLLAMA_MODEL is unset
    - Test placeholder narrative contains gene name and classification value
    - _Requirements: 1.4, 1.7_

  - [x] 7.3 Write unit tests for agent message passing
    - Create `tests/unit/test_agent_message.py`
    - Test AgentMessage model validation (required fields, timestamp default)
    - Test MessageType enum values
    - Test MessageBus dispatch and timeout behavior
    - Create `tests/unit/test_supervisor.py`
    - Test supervisor timeout fallback to rule-based classification
    - Test concurrent dispatch behavior with multiple variants
    - _Requirements: 3.2, 3.4, 3.7_

  - [x] 7.4 Write property test for narrative inclusion in report
    - **Property 3: Clinical narrative inclusion in report**
    - **Validates: Requirements 1.6**
    - Create `tests/properties/test_report_rendering.py`
    - Use Hypothesis to generate ClinicalReport objects with non-empty clinical_narrative fields
    - Verify rendered markdown_summary contains each clinical narrative text
    - Mark with `@pytest.mark.property` and `@settings(max_examples=100)`

- [x] 8. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The project uses Python 3.10+ with Pydantic v2, pytest, pytest-asyncio, and Hypothesis
- All new modules follow the existing project structure and coding conventions

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2"] },
    { "id": 2, "tasks": ["1.3", "2.1"] },
    { "id": 3, "tasks": ["2.2"] },
    { "id": 4, "tasks": ["2.3"] },
    { "id": 5, "tasks": ["2.4", "4.1"] },
    { "id": 6, "tasks": ["4.2", "4.3"] },
    { "id": 7, "tasks": ["6.1", "7.1"] },
    { "id": 8, "tasks": ["6.2", "6.3", "7.2", "7.3", "7.4"] }
  ]
}
```
