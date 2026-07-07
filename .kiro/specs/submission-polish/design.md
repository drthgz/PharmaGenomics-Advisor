# Design Document: Submission Polish

## Overview

This design covers eight coordinated polish tasks to maximize the PharmaGenomics Advisor's hackathon submission score. The changes span infrastructure (Dockerfile, docker-compose), documentation (README), developer experience (demo script, inline comments), error handling (ADK graceful fallback), and verification (test suite green pass). All changes are additive or corrective — no new architectural layers are introduced.

## Architecture

The existing architecture remains unchanged. This polish pass touches the following layers:

```
┌─────────────────────────────────────────────────────────────────────┐
│  Presentation Layer                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────────────┐ │
│  │ demo.py CLI  │  │ README.md    │  │ docker-compose.yml        │ │
│  └──────────────┘  └──────────────┘  └───────────────────────────┘ │
├─────────────────────────────────────────────────────────────────────┤
│  Agent Layer                                                         │
│  ┌──────────────────┐  ┌──────────────┐  ┌──────────────────────┐ │
│  │ SupervisorAgent  │  │ MessageBus   │  │ Specialist Handlers  │ │
│  └──────────────────┘  └──────────────┘  └──────────────────────┘ │
├─────────────────────────────────────────────────────────────────────┤
│  Inference Layer                                                     │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │ LLMInferenceClient (ollama_client.py)                          │ │
│  └────────────────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────────────┤
│  Pipeline Layer                                                      │
│  ┌──────────────────────┐  ┌────────────────────────────────────┐ │
│  │ PipelineOrchestrator │  │ ADKWorkflowRunner                  │ │
│  └──────────────────────┘  └────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────────────┤
│  Security Layer                                                      │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │ SecurityLayer (validator → PHI → rate limiter → audit)         │ │
│  └────────────────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────────────┤
│  Infrastructure                                                      │
│  ┌────────────────────┐  ┌──────────────────────────────────────┐ │
│  │ Dockerfile         │  │ Ollama (local LLM server)            │ │
│  └────────────────────┘  └──────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

## Components and Interfaces

### Components

| Component | File | Responsibility |
|---|---|---|
| Dockerfile Model-Pull Script | `Dockerfile` | Background Ollama start, poll readiness, pull model, clean kill |
| Docker Compose Config | `docker-compose.yml` | Single-service orchestration with build args and volume mount |
| Demo Script | `scripts/demo.py` | CLI entrypoint with logging, agent event display, report preview |
| ADK Workflow Runner | `src/pipeline/adk_workflow.py` | ADK-backed execution with clean error wrapping |
| SupervisorAgent | `src/agents/supervisor.py` | Route variants to specialists, aggregate results |
| MessageBus | `src/agents/message_bus.py` | Async message dispatch with timeout handling |
| LLMInferenceClient | `src/inference/ollama_client.py` | Ollama chat calls for clinical narratives |
| PipelineOrchestrator | `src/pipeline/orchestrator.py` | End-to-end pipeline coordination |
| SecurityLayer | `src/security/layer.py` | Input validation, PHI detection, rate limiting |

### Interfaces

```python
# Demo script formatting interface (new helper functions)
def format_agent_event(message: AgentMessage) -> str:
    """Format an agent message as a log line with emoji prefix."""
    ...

def format_narrative_output(gene: str, classification: str, narrative: str) -> str:
    """Format LLM narrative with gene/classification header."""
    ...

def print_report_preview(markdown: str, max_lines: int = 40) -> None:
    """Print first N lines of markdown report to stdout."""
    ...
```

```python
# ADK error interface (unchanged, messages standardized)
class ADKNotAvailableError(RuntimeError):
    """Message format: 'ADK runtime not available. Install with: ...'
    or 'Missing ADK symbol: X. The installed google-adk version may be incompatible.'
    """
```

## Component Designs

### 1. Dockerfile Model-Pull Fix

**Current Problem:** The existing `RUN` step uses `cat /tmp/ollama.pid` which is unreliable — Ollama doesn't write a PID file by default. The `sleep 5` is a race condition.

**Design:**

Replace the model-pull `RUN` with a shell script approach:

```dockerfile
RUN set -e && \
    ollama serve & \
    OLLAMA_PID=$! && \
    echo "Waiting for Ollama to start (PID: $OLLAMA_PID)..." && \
    for i in $(seq 1 30); do \
        if curl -sf http://localhost:11434 > /dev/null 2>&1; then \
            break; \
        fi; \
        if [ "$i" -eq 30 ]; then \
            echo "ERROR: Ollama failed to start within 30 seconds" && exit 1; \
        fi; \
        sleep 1; \
    done && \
    echo "Ollama ready. Pulling model: ${OLLAMA_MODEL}" && \
    ollama pull ${OLLAMA_MODEL} && \
    kill -SIGTERM $OLLAMA_PID && \
    wait $OLLAMA_PID || true
```

Key decisions:
- `$!` captures the background PID immediately — no file-based PID storage
- `curl -sf` polling at 1-second intervals (up to 30 attempts) replaces the fragile `sleep 5`
- `kill -SIGTERM` + `wait` ensures clean reaping
- `|| true` after `wait` handles the case where the process already exited

### 2. Docker Compose File

**Location:** `docker-compose.yml` at project root.

```yaml
services:
  pharmagenomics:
    build:
      context: .
      dockerfile: Dockerfile
      args:
        OLLAMA_MODEL: ${OLLAMA_MODEL:-medgemma}
    ports:
      - "11434:11434"
    volumes:
      - ./output:/app/output
```

Design decisions:
- Single service — no multi-container orchestration needed
- Build arg uses env var with `medgemma` default for flexibility
- Volume mount enables host access to generated reports
- No `depends_on` or healthcheck needed (Ollama starts inside the container)

### 3. README Updates

Add three new sections after the existing "Architecture" section:

1. **LLM Inference Client** — describes `src/inference/ollama_client.py`, its role calling Ollama for clinical narratives, timeout/fallback behavior
2. **Multi-Agent Architecture** — subsection covering:
   - SupervisorAgent: routes variants to specialists, aggregates results
   - MessageBus: async dispatch with timeout, concurrent message handling
   - Agent-to-agent communication: structured `AgentMessage` payloads (Pydantic) with message_type, sender, recipient
3. **Property-Based Testing** — describes Hypothesis usage, `tests/properties/` directory, minimum 100 examples per property

Update the Mermaid diagram to add `SupervisorAgent`, `MessageBus`, and `LLMInferenceClient` nodes. Update the "Course Concepts Demonstrated" table.

### 4. Demo Script Enhancements

**Approach:** Add logging configuration and event callbacks to the pipeline run, then format output with emoji prefixes.

```python
# Logging configuration at module level
logging.basicConfig(level=logging.INFO, format="%(message)s")

# Emoji prefix constants
PREFIX_AGENT = "🤖"
PREFIX_LLM = "🧠"
PREFIX_REPORT = "📋"
```

**Event display strategy:**
- Hook into the SupervisorAgent dispatch by configuring Python `logging` at INFO level with a custom filter for `src.agents.*` loggers
- After pipeline completes, print LLM narratives from each classification
- Print agent message events using the bus logger output
- Print first 40 lines of markdown report as preview
- Print summary statistics last

**Interface changes to `main()`:**
1. Configure logging before pipeline run
2. After `report = orchestrator.run(...)`:
   - Iterate `report.classifications`, print gene + classification + narrative with `🧠` prefix
   - Print pipeline summary with standard output
   - Print `report.markdown_summary.splitlines()[:40]` with `📋` prefix

### 5. Inline Comments Strategy

Each of the 5 key modules gets 10+ inline comments within function/method bodies. Comments explain:
- **Why** (rationale/design decision), not **what** (which the code already shows)
- Control flow decisions
- Error handling strategies
- Data transformation logic

Target locations per module:
- `supervisor.py`: routing logic, fallback decision, narrative generation loop
- `message_bus.py`: handler lookup, timeout wrapping, concurrent gather pattern
- `ollama_client.py`: field validation logic, prompt construction, truncation, fallback
- `orchestrator.py`: pipeline stage transitions, MCP bridge calls, recommendation deduplication
- `security/layer.py`: chain ordering rationale, early-return pattern, env parsing

### 6. ADK Error Message Cleanup

**Current state:** `_import_adk()` already raises `ADKNotAvailableError` but messages vary in format.

**Design changes:**

1. Standardize the "package not installed" message:
   ```python
   raise ADKNotAvailableError(
       "ADK runtime not available. Install with: pip install 'google-adk>=2.0.0'"
   )
   ```

2. Standardize "missing symbol" messages:
   ```python
   raise ADKNotAvailableError(
       f"Missing ADK symbol: {symbol_name}. "
       "The installed google-adk version may be incompatible."
   )
   ```

3. In `demo.py`, update the `except ADKNotAvailableError` block:
   ```python
   except ADKNotAvailableError as exc:
       print(f"ERROR: {exc}", file=sys.stderr)
       return 2
   ```

4. Wrap any remaining `ImportError` or `AttributeError` in the ADK code path with `ADKNotAvailableError`.

### 7. Test Import Fix Strategy

**Approach:** Run `pytest --collect-only` to identify any collection errors. Common issues:
- Missing `__init__.py` in test subdirectories (already present)
- Import paths assuming `src` is a package vs. project-root-relative
- Missing optional dependencies at import time (google-adk)

Fix pattern: ensure all test files that import from `src/` use paths that resolve from project root. Tests that require google-adk must guard imports with try/except or use `pytest.importorskip()`.

### 8. Verification

Final step: run `pytest tests/unit tests/properties -v` and confirm exit code 0, zero failures, zero errors.

## Data Models

No new data models are introduced. Existing models used:
- `AgentMessage` — message payload for bus communication
- `VariantClassification` — classification result with optional `clinical_narrative`
- `ClinicalReport` — final report with `markdown_summary`
- `ADKNotAvailableError` — exception for ADK unavailability

## Error Handling

| Error Scenario | Handling |
|---|---|
| Ollama fails to start in Docker build | Exit code 1 with "Ollama failed to start" message |
| google-adk not installed | `ADKNotAvailableError` with install hint, demo exits with code 2 |
| ADK symbol missing | `ADKNotAvailableError` naming the symbol + version incompatibility hint |
| ImportError/AttributeError in ADK path | Wrapped in `ADKNotAvailableError` — never propagates raw |
| Test import failures | Fixed at source; correct import paths from project root |

## Testing Strategy

**Unit Tests** (existing in `tests/unit/`):
- `test_adk_workflow.py` — verifies ADK symbol validation, error wrapping, workflow construction
- `test_agent_message.py` — verifies AgentMessage Pydantic model
- `test_llm_inference.py` — verifies LLMInferenceClient with mocked Ollama
- `test_message_bus.py` — verifies MessageBus dispatch, timeout, unknown recipient
- `test_supervisor.py` — verifies SupervisorAgent routing and fallback
- `test_security.py` — verifies SecurityLayer validation chain
- `test_vcf_parser.py` — verifies VCF parsing

**Property Tests** (existing in `tests/properties/`):
- `test_agent_routing.py` — routing correctness for any gene/variant combination
- `test_llm_inference.py` — inference client behavior for any valid/invalid classification
- `test_report_rendering.py` — report rendering for any ClinicalReport instance
- `test_vcf_roundtrip.py` — VCF parse/render roundtrip

**New verification needed:**
- After changes: run `pytest tests/unit tests/properties -v` — must exit 0
- Property tests run with minimum 100 Hypothesis examples
- No test modifications allowed — fix source if tests fail

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Agent event log formatting contains required fields

*For any* AgentMessage with a valid message_type, sender, and recipient, formatting it as a demo log line SHALL produce a string that contains the message_type value, the sender name, and the recipient name, preceded by a visual emoji prefix.

**Validates: Requirements 4.1, 4.2, 4.3, 4.4**

### Property 2: Report preview outputs correct line count

*For any* markdown report string with N lines (where N >= 0), printing the "first 40 lines" preview SHALL output exactly min(N, 40) lines of content from the report.

**Validates: Requirements 4.6**

### Property 3: Key modules have minimum inline comment density

*For any* key module file in the set {supervisor.py, message_bus.py, ollama_client.py, orchestrator.py, layer.py}, counting lines that match the pattern of inline comments within function/method bodies (lines starting with optional whitespace followed by `#`, excluding module/class docstrings) SHALL yield a count of at least 10.

**Validates: Requirements 5.6**

### Property 4: ADK import errors are always wrapped in ADKNotAvailableError

*For any* simulated failure of `importlib.import_module("google.adk")` or `importlib.import_module("google.adk.sessions")` or `getattr` returning None for required symbols (Workflow, workflow.START, Runner, InMemorySessionService), calling `_import_adk()` SHALL raise `ADKNotAvailableError` and SHALL NOT allow `ImportError` or `AttributeError` to propagate.

**Validates: Requirements 6.2, 6.5**
