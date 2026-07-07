# Implementation Plan: Submission Polish

## Overview

Eight coordinated polish tasks to maximize the PharmaGenomics Advisor hackathon submission score. Changes span infrastructure (Dockerfile, docker-compose), documentation (README), developer experience (demo script, inline comments), error handling (ADK graceful fallback), and verification (test suite green pass). All changes are additive or corrective — no new architecture introduced.

## Tasks

- [x] 1. Fix Dockerfile model-pull PID handling
  - [x] 1.1 Replace the model-pull RUN step in `Dockerfile` with proper `$!` PID capture
    - Replace the existing `RUN ollama serve & sleep 5 ...` block
    - Start `ollama serve &` and capture PID with `OLLAMA_PID=$!`
    - Poll `http://localhost:11434` with `curl -sf` in a loop (1-second intervals, 30 attempts)
    - Fail with non-zero exit code and "Ollama failed to start" message if 30 seconds elapse
    - Execute `ollama pull ${OLLAMA_MODEL}` once API is ready
    - Send `kill -SIGTERM $OLLAMA_PID` and `wait $OLLAMA_PID || true` to reap the process
    - Remove any reference to `/tmp/ollama.pid` or file-based PID storage
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6_

- [x] 2. Add docker-compose.yml for single-command deployment
  - [x] 2.1 Create `docker-compose.yml` at project root
    - Define a single service named `pharmagenomics`
    - Build from project root Dockerfile with `OLLAMA_MODEL` build arg defaulting to "medgemma"
    - Map container port 11434 to host port 11434
    - Mount `./output:/app/output` volume for persistent report output
    - Ensure `docker compose up` builds and runs the entrypoint without manual intervention
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_

- [x] 3. Tighten ADK error messages for graceful fallback
  - [x] 3.1 Standardize error messages in `src/pipeline/adk_workflow.py`
    - Change the "package not installed" message to: "ADK runtime not available. Install with: pip install 'google-adk>=2.0.0'"
    - Change "missing symbol" messages to: "Missing ADK symbol: {name}. The installed google-adk version may be incompatible."
    - Ensure all `ImportError` and `AttributeError` in the ADK code path are wrapped in `ADKNotAvailableError`
    - No raw tracebacks should propagate from ADK import validation
    - _Requirements: 6.1, 6.2, 6.5_

  - [x] 3.2 Update ADK error handling in `scripts/demo.py`
    - Change the `except ADKNotAvailableError` block to print to stderr (not stdout)
    - Format as a single-line message: `f"ERROR: {exc}"`
    - Return exit code 2 to distinguish from other failures
    - Do NOT print a full Python traceback
    - _Requirements: 6.3, 6.4_

- [x] 4. Add detailed inline code comments to key modules
  - [x] 4.1 Add inline comments to `src/agents/supervisor.py`
    - Add 10+ inline comment lines within method bodies
    - Explain: class purpose, routing logic for dispatching to specialists, aggregation logic
    - Comments should explain "why" (rationale/design decisions), not "what"
    - _Requirements: 5.1, 5.6_

  - [x] 4.2 Add inline comments to `src/agents/message_bus.py`
    - Add 10+ inline comment lines within method bodies
    - Explain: message bus purpose, handler registration mechanism, message dispatch flow
    - _Requirements: 5.2, 5.6_

  - [x] 4.3 Add inline comments to `src/inference/ollama_client.py`
    - Add 10+ inline comment lines within method bodies
    - Explain: LLM client purpose, prompt construction, timeout/error handling, fallback behavior
    - _Requirements: 5.3, 5.6_

  - [x] 4.4 Add inline comments to `src/pipeline/orchestrator.py`
    - Add 10+ inline comment lines within method bodies
    - Explain: overall pipeline flow, purpose of each stage, report assembly logic
    - _Requirements: 5.4, 5.6_

  - [x] 4.5 Add inline comments to `src/security/layer.py`
    - Add 10+ inline comment lines within method bodies
    - Explain: security layer purpose, PHI detection logic, injection prevention, rate limiting
    - _Requirements: 5.5, 5.6_

- [x] 5. Enhance demo script output
  - [x] 5.1 Add agent event logging and LLM narrative display to `scripts/demo.py`
    - Configure logging at module level with INFO level for `src.agents.*` loggers
    - Define emoji prefix constants: `🤖` for agent events, `🧠` for LLM narratives, `📋` for report
    - After pipeline run, iterate `report.classifications` and print gene + classification + narrative with `🧠` prefix
    - Log SupervisorAgent dispatch events (message_type, sender, recipient) with `🤖` prefix
    - Log specialist agent response events (message_type, sender, classification summary) with `🤖` prefix
    - Print first 40 lines of `report.markdown_summary` as a preview with `📋` prefix
    - Print pipeline summary statistics (variants, classifications, recommendations, literature, warnings) after agent output
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_

- [x] 6. Update README for current architecture
  - [x] 6.1 Add LLM inference client section to `readme.md`
    - Describe `src/inference/ollama_client.py` module and its role calling Ollama for clinical narratives
    - Mention timeout and fallback behavior
    - _Requirements: 3.1_

  - [x] 6.2 Add multi-agent architecture section to `readme.md`
    - Describe SupervisorAgent and routing of variant analysis to specialists
    - Describe MessageBus and async AgentMessage dispatch
    - Describe agent-to-agent communication as message-passing architecture with structured Pydantic payloads
    - _Requirements: 3.2, 3.3, 3.4_

  - [x] 6.3 Add property-based testing section to `readme.md`
    - Describe Hypothesis library usage with `tests/properties/` directory reference
    - Mention minimum 100 examples per property
    - _Requirements: 3.5_

  - [x] 6.4 Update architecture diagram and course concepts table in `readme.md`
    - Add SupervisorAgent, MessageBus, and LLMInferenceClient to the architecture diagram
    - Update "Course Concepts Demonstrated" table with agent message-passing, LLM inference, property-based tests
    - _Requirements: 3.6, 3.7_

- [x] 7. Fix test suite import errors
  - [x] 7.1 Fix import paths and guard optional dependencies in test files
    - Run `pytest --collect-only tests/unit tests/properties` to identify collection errors
    - Fix any `ModuleNotFoundError` or `ImportError` in test collection
    - Ensure all test files use import paths resolvable from project root
    - Guard google-adk imports with `pytest.importorskip()` or try/except
    - Fix any source code in `src/` if tests fail due to code defects (do not modify tests)
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

  - [x] 7.2 Write property test for agent event formatting
    - **Property 1: Agent event log formatting contains required fields**
    - **Validates: Requirements 4.1, 4.2, 4.3, 4.4**

  - [x] 7.3 Write property test for report preview line count
    - **Property 2: Report preview outputs correct line count**
    - **Validates: Requirements 4.6**

  - [x] 7.4 Write property test for inline comment density
    - **Property 3: Key modules have minimum inline comment density**
    - **Validates: Requirements 5.6**

  - [x] 7.5 Write property test for ADK error wrapping
    - **Property 4: ADK import errors are always wrapped in ADKNotAvailableError**
    - **Validates: Requirements 6.2, 6.5**

- [x] 8. Final verification checkpoint
  - [x] 8.1 Run full test suite and confirm green pass
    - Execute `pytest tests/unit tests/properties -v` from project root
    - Confirm exit code 0, zero failures, zero errors
    - Confirm property-based tests run with minimum 100 Hypothesis examples
    - Confirm total execution completes within 300 seconds
    - If any test fails due to source code defect, fix the source code and re-run
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- The project uses Python throughout — all code examples and implementations are Python
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- No architectural changes — all modifications are additive or corrective

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "3.1", "4.1", "4.2", "4.3", "4.4", "4.5"] },
    { "id": 1, "tasks": ["2.1", "3.2", "5.1", "6.1", "6.2", "6.3", "6.4"] },
    { "id": 2, "tasks": ["7.1"] },
    { "id": 3, "tasks": ["7.2", "7.3", "7.4", "7.5"] },
    { "id": 4, "tasks": ["8.1"] }
  ]
}
```
