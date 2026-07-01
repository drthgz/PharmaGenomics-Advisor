# Architecture Overview

> This document describes the technical architecture of the PharmaGenomics Advisor system — how components connect, data flows, and design decisions. Aimed at a developer who wants to understand the system well enough to implement or modify it.

## Table of Contents

1. [System Architecture Diagram](#system-architecture-diagram)
2. [Component Breakdown](#component-breakdown)
3. [Data Flow](#data-flow)
4. [Technology Stack](#technology-stack)
5. [Directory Structure](#directory-structure)
6. [Design Decisions](#design-decisions)
7. [Error Handling Strategy](#error-handling-strategy)
8. [Security Architecture](#security-architecture)

---

## System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         USER INTERFACE                                │
│                    (CLI / Demo Script / API)                          │
└────────────────────────────────┬────────────────────────────────────┘
                                 │ VCF file input
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      SECURITY LAYER                                   │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────┐               │
│  │   Input     │  │    PHI       │  │   Rate        │               │
│  │ Validation  │  │  Detection   │  │   Limiter     │               │
│  └─────────────┘  └──────────────┘  └───────────────┘               │
└────────────────────────────────┬────────────────────────────────────┘
                                 │ Validated input
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    ADK 2.0 GRAPH WORKFLOW                             │
│                                                                       │
│  ┌─────────┐    ┌──────────────┐    ┌─────────┐    ┌────────────┐  │
│  │  Parse  │───▶│   Classify   │───▶│  Drug   │───▶│ Literature │  │
│  │   VCF   │    │   Variants   │    │   Rec   │    │    RAG     │  │
│  └─────────┘    └──────┬───────┘    └────┬────┘    └─────┬──────┘  │
│       │                 │                  │               │          │
│       │          ┌──────┴──────┐          │               │          │
│       │          │  Parallel   │          │               │          │
│       │          │  Dispatch   │          │               │          │
│       │     ┌────┴────┬────┬───┴───┐     │               │          │
│       │     ▼         ▼    ▼       ▼     │               │          │
│       │  ┌──────┐ ┌──────┐ ┌──────┐     │               │          │
│       │  │ BRCA │ │ EGFR │ │ TP53 │     │               │          │
│       │  │Agent │ │Agent │ │Agent │     │               │          │
│       │  └──┬───┘ └──┬───┘ └──┬───┘     │               │          │
│       │     └────────┬┘────────┘         │               │          │
│       │              │                    │               │          │
│       │              ▼                    ▼               ▼          │
│       │     ┌──────────────┐    ┌──────────────┐  ┌────────────┐   │
│       │     │  PGx Drug    │    │  PGx Drug    │  │  Vector    │   │
│       │     │  Advisor     │    │  Advisor     │  │  Store     │   │
│       │     └──────────────┘    └──────────────┘  └────────────┘   │
│       │                                                              │
│       ▼                         REPORT ASSEMBLY                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                    Clinical Report Generator                   │   │
│  │              (JSON + Markdown with provenance)                 │   │
│  └──────────────────────────────────────────────────────────────┘   │
└────────────────────────────────┬────────────────────────────────────┘
                                 │
          ┌──────────────────────┼──────────────────────┐
          ▼                      ▼                      ▼
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│   ClinVar MCP    │  │    CPIC MCP      │  │  PharmGKB MCP    │
│   (NCBI API)     │  │  (Local JSON)    │  │  (Local TSV)     │
└──────────────────┘  └──────────────────┘  └──────────────────┘
          │
          ▼
┌──────────────────┐
│  NCBI E-utils    │
│  (External API)  │
└──────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                      INFERENCE LAYER                                  │
│                                                                       │
│              ┌────────────────────────────┐                          │
│              │     Ollama (localhost)      │                          │
│              │  ┌──────────────────────┐  │                          │
│              │  │  MedGemma 4B or      │  │                          │
│              │  │  Gemma 4 12B         │  │                          │
│              │  └──────────────────────┘  │                          │
│              └────────────────────────────┘                          │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                      OBSERVABILITY                                    │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────┐               │
│  │ Audit Log   │  │  Execution   │  │   Error       │               │
│  │ (append)    │  │  Metrics     │  │   Tracking    │               │
│  └─────────────┘  └──────────────┘  └───────────────┘               │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Component Breakdown

### 1. VCF Parser (Pure Code — No LLM)

**Purpose:** Parse VCF files into structured variant objects.

**Why no LLM?** VCF parsing is deterministic — the format is well-defined. Using an LLM here would add latency and unreliability for zero benefit.

```python
@dataclass
class Variant:
    chromosome: str      # e.g., "chr17"
    position: int        # e.g., 41234470
    ref_allele: str      # e.g., "A"
    alt_allele: str      # e.g., "G"
    quality: float       # e.g., 99.0
    gene: str            # e.g., "BRCA1"
    variant_type: str    # e.g., "missense"
    hgvs: str           # e.g., "NM_007294.3:c.185A>G"
```

### 2. Supervisor Agent (ADK 2.0 Graph)

**Purpose:** Orchestrate the entire pipeline. Routes variants to the right agents, handles failures, assembles results.

**Key responsibilities:**
- Define execution graph (ordering)
- Route variants by gene
- Handle timeouts and retries
- Aggregate results into final report

### 3. Gene-Specific Agents (BRCA, EGFR, TP53)

**Purpose:** Classify variants using ACMG criteria with gene-specific knowledge.

**Each agent has:**
- A specialized system prompt with gene-specific biology
- Access to ClinVar MCP for evidence lookup
- Structured output format for classification results

**Why separate agents per gene?** Each gene has unique biology:
- BRCA: Focus on DNA repair domain disruption
- EGFR: Focus on kinase domain activation, TKI sensitivity
- TP53: Focus on DNA-binding domain, gain vs. loss of function

### 4. PGx Drug Advisor Agent

**Purpose:** Translate variant classifications into drug recommendations.

**Decision logic:**
```
IF variant is Pathogenic or Likely Pathogenic:
    Query CPIC for gene-drug guidelines
    IF gene is EGFR and variant is TKI-sensitive:
        Query PharmGKB for targeted therapy options
    Return structured drug recommendations
ELSE:
    Skip (no drug rec needed for VUS/Benign)
```

### 5. Literature RAG Agent

**Purpose:** Find and synthesize published evidence supporting recommendations.

**Components:**
- Embedding model (converts text → vectors)
- Vector store (stores and searches embeddings)
- Synthesis prompt (generates summary from retrieved papers)

### 6. MCP Servers (ClinVar, CPIC, PharmGKB)

**Purpose:** Expose knowledge bases as standardized tool endpoints.

| Server | Data Source | Network Required? |
|--------|------------|-------------------|
| ClinVar MCP | NCBI E-utilities API | Yes (external API) |
| CPIC MCP | Local JSON cache | No |
| PharmGKB MCP | Local TSV cache | No |

### 7. Clinical Report Generator

**Purpose:** Assemble all agent outputs into a unified, reviewable document.

**Outputs:**
- `report.json` — Machine-readable, structured data
- `report.md` — Human-readable markdown for clinical review

---

## Data Flow

### Happy Path (Everything Works)

```
1. VCF file submitted
   → Security layer validates (no PHI, no injection, size OK)
   → VCF parser extracts variants

2. Supervisor receives parsed variants
   → Routes BRCA1 variant to BRCA_Agent
   → Routes EGFR variant to EGFR_Agent
   → Routes TP53 variant to TP53_Agent
   → (parallel execution)

3. Each gene agent:
   → Calls ClinVar MCP (gets existing classifications)
   → Reasons with MedGemma (applies ACMG criteria)
   → Returns: classification + confidence + evidence

4. Supervisor collects classifications
   → Filters: only Pathogenic and Likely Pathogenic proceed
   → Sends to PGx Drug Advisor

5. PGx Drug Advisor:
   → Calls CPIC MCP (gene-drug guidelines)
   → Calls PharmGKB MCP (clinical annotations)
   → Returns: drug recommendations ordered by evidence

6. Literature RAG Agent:
   → Embeds query (variant + drug combination)
   → Searches vector store (top 5 papers, score > 0.5)
   → Synthesizes evidence summary (≤200 words)

7. Report Generator:
   → Assembles all results
   → Adds provenance metadata
   → Writes JSON + Markdown files
   → Logs to audit trail
```

### Degraded Path (Something Fails)

```
ClinVar MCP timeout (>30s):
  → Gene agent classifies with local knowledge only
  → Flags result as "limited evidence"
  → Pipeline continues

PGx Drug Advisor can't reach CPIC:
  → Uses local cached guidelines
  → Flags as "limited evidence — external source unavailable"
  → Pipeline continues

Literature vector store unavailable:
  → Returns "literature search unavailable"
  → Recommends manual PubMed review
  → Pipeline continues

Gene agent timeout (>60s):
  → Supervisor retries once
  → If retry fails: marks agent result "unavailable"
  → Pipeline continues with remaining agents
```

---

## Technology Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| Language | Python 3.10+ | Ecosystem (bioinformatics + ML libraries) |
| Agent Framework | Google ADK 2.0 | Graph workflows, MCP support, Agents CLI |
| LLM Runtime | Ollama | Local, free, no API keys |
| LLM Model | MedGemma 4B / Gemma 4 12B | Medical reasoning / function calling |
| MCP Servers | Python (FastMCP) | Lightweight, easy to implement |
| Vector Store | ChromaDB or FAISS | Local, no server needed, fast |
| Embeddings | all-MiniLM-L6-v2 | Small, fast, good quality (384 dims) |
| Data Format | VCF 4.x input, JSON/MD output | Clinical standards |
| Testing | pytest + Agents CLI | Unit + integration + agent evaluation |
| Deployment | Docker / Cloud Run | Containerized, reproducible |

---

## Directory Structure

```
pharmagenomics-advisor/
├── agent.yaml                    # Root agent config (Agents CLI)
├── pyproject.toml                # Python project config + dependencies
├── README.md                     # Setup and usage documentation
├── Dockerfile                    # Container build
├── setup.sh                      # One-command setup script
│
├── agents/                       # Agent definitions
│   ├── supervisor/
│   │   ├── agent.yaml           # Supervisor config
│   │   └── prompt.md            # System prompt
│   ├── brca_agent/
│   │   ├── agent.yaml
│   │   └── prompt.md
│   ├── egfr_agent/
│   │   ├── agent.yaml
│   │   └── prompt.md
│   ├── tp53_agent/
│   │   ├── agent.yaml
│   │   └── prompt.md
│   ├── pgx_advisor/
│   │   ├── agent.yaml
│   │   └── prompt.md
│   └── literature_rag/
│       ├── agent.yaml
│       └── prompt.md
│
├── src/                          # Source code
│   ├── pipeline/
│   │   ├── __init__.py
│   │   ├── graph.py             # ADK graph workflow definition
│   │   ├── supervisor.py        # Supervisor orchestration logic
│   │   └── report.py            # Clinical report generation
│   ├── parsers/
│   │   ├── __init__.py
│   │   └── vcf_parser.py       # VCF file parsing
│   ├── security/
│   │   ├── __init__.py
│   │   ├── input_validator.py   # Injection detection
│   │   ├── phi_detector.py      # PHI pattern matching
│   │   ├── rate_limiter.py      # Request throttling
│   │   └── audit_log.py        # Immutable logging
│   └── rag/
│       ├── __init__.py
│       ├── embeddings.py        # Text → vector conversion
│       ├── vector_store.py      # ChromaDB/FAISS wrapper
│       └── literature_index.py  # PubMed abstract indexing
│
├── mcp_servers/                  # MCP server implementations
│   ├── clinvar_server.py        # ClinVar (NCBI E-utilities)
│   ├── cpic_server.py           # CPIC (local JSON)
│   └── pharmgkb_server.py      # PharmGKB (local TSV)
│
├── data/                         # Local knowledge bases
│   ├── cpic/
│   │   └── guidelines.json     # CPIC gene-drug guidelines
│   ├── pharmgkb/
│   │   └── annotations.tsv     # PharmGKB clinical annotations
│   ├── literature/
│   │   └── pubmed_abstracts.json  # Pre-indexed abstracts
│   └── samples/
│       └── sample_variants.vcf  # Demo VCF file
│
├── tests/                        # Test suite
│   ├── unit/
│   │   ├── test_vcf_parser.py
│   │   ├── test_security.py
│   │   └── test_report.py
│   ├── integration/
│   │   ├── test_mcp_servers.py
│   │   ├── test_agents.py
│   │   └── test_pipeline.py
│   └── properties/
│       ├── test_vcf_roundtrip.py
│       └── test_report_roundtrip.py
│
├── docs/                         # Documentation
│   ├── 01-biomedical-foundations.md
│   ├── 02-ai-agents-concepts.md
│   ├── 03-architecture-overview.md
│   ├── 04-implementation-guide.md
│   └── 05-deployment-guide.md
│
└── scripts/                      # Utility scripts
    ├── download_cpic_data.py    # Fetch latest CPIC guidelines
    ├── download_pharmgkb.py     # Fetch PharmGKB annotations
    ├── index_literature.py      # Build vector store from abstracts
    └── demo.py                  # End-to-end demonstration
```

---

## Design Decisions

### 1. Why Ollama Over Cloud APIs?

| Factor | Ollama (Local) | Cloud API (Gemini, etc.) |
|--------|---------------|--------------------------|
| Cost | Free | $0.01-0.10 per 1K tokens |
| Privacy | Data never leaves machine | Data sent to Google/OpenAI |
| API key required | No | Yes |
| Internet required | No (except ClinVar MCP) | Yes |
| Setup complexity | `ollama pull medgemma` | Account + billing + key management |
| Reproducibility | Same model version always | Provider may update model |
| Competition appeal | "Zero-cost, zero-barrier" story | Less impressive for "Agents for Good" |

### 2. Why MCP Over Direct API Calls?

- **Standardization:** Any MCP client can use our servers (not locked to ADK)
- **Testability:** Mock MCP servers for testing without network
- **Course requirement:** MCP is one of the 6 concepts we must demonstrate
- **Modularity:** Swap data sources without changing agent code

### 3. Why Separate Gene Agents (Not One Universal Classifier)?

- **Prompt size:** One universal prompt would be enormous and confusing
- **Accuracy:** Specialized agents outperform general ones on domain tasks
- **Parallelism:** Classify multiple variants simultaneously
- **Extensibility:** Add CYP2D6 agent later without touching BRCA logic

### 4. Why Local CPIC/PharmGKB Data (Not Live APIs)?

- CPIC doesn't have a public REST API — data is published as downloadable files
- PharmGKB's API requires registration and has rate limits
- Local caching means zero-latency queries and offline capability
- We version-pin the data at build time for reproducibility

---

## Error Handling Strategy

### Cascading Graceful Degradation

The system is designed so that failures reduce quality but never crash the pipeline:

```
Level 1: Full capability (all services available)
  → Complete report with all evidence

Level 2: Partial degradation (ClinVar unreachable)
  → Classification still works (local knowledge)
  → Report flags "limited evidence"

Level 3: Major degradation (Ollama slow/overloaded)
  → Timeouts trigger retries (1 retry per agent)
  → Timed-out agents marked "unavailable"
  → Report generated with available results

Level 4: Critical failure (Ollama not running)
  → Pipeline refuses to start
  → Clear error message with fix instructions
```

---

## Security Architecture

```
┌──────────────────────────────────────────┐
│            INPUT BOUNDARY                 │
│                                           │
│  1. Size check (≤10,000 chars)           │
│  2. Injection pattern matching            │
│     - SQL: SELECT, DROP, UNION           │
│     - Prompt: "ignore instructions"       │
│     - Command: ; rm, | cat, $(...)       │
│  3. PHI detection                         │
│     - Name patterns (First Last)          │
│     - DOB patterns (MM/DD/YYYY)          │
│     - MRN patterns (alphanumeric IDs)    │
│  4. Rate limiting (100 req/min)           │
└──────────────────────────────────────────┘
                    │
                    ▼ (only clean data passes)
┌──────────────────────────────────────────┐
│          PROCESSING BOUNDARY              │
│                                           │
│  - All data in-memory only               │
│  - No disk writes unless opted in        │
│  - Agent isolation (each has own scope)  │
└──────────────────────────────────────────┘
                    │
                    ▼
┌──────────────────────────────────────────┐
│          AUDIT BOUNDARY                   │
│                                           │
│  Every agent call logged:                │
│  - ISO 8601 timestamp                    │
│  - Agent name                            │
│  - Action type                           │
│  - SHA-256(input)                        │
│  - SHA-256(output)                       │
│  - Append-only (immutable)               │
└──────────────────────────────────────────┘
```

**Important note:** This is a demonstration project, not a production clinical system. The security measures show awareness of healthcare data handling best practices, but a real deployment would require HIPAA compliance review, penetration testing, and regulatory approval.
