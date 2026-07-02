# AI Agents & Multi-Agent Systems

> This document explains the AI and software engineering concepts used in the PharmaGenomics Advisor. Written for someone comfortable with basic programming (Python) but new to AI agent architectures.

## Table of Contents

1. [What is an AI Agent?](#what-is-an-ai-agent)
2. [Large Language Models (LLMs)](#large-language-models-llms)
3. [From Chatbot to Agent](#from-chatbot-to-agent)
4. [Multi-Agent Systems](#multi-agent-systems)
5. [Google Agent Development Kit (ADK) 2.0](#google-agent-development-kit-adk-20)
6. [Model Context Protocol (MCP)](#model-context-protocol-mcp)
7. [Retrieval-Augmented Generation (RAG)](#retrieval-augmented-generation-rag)
8. [Running Models Locally with Ollama](#running-models-locally-with-ollama)
9. [Agents CLI](#agents-cli)
10. [How These Concepts Fit Together](#how-these-concepts-fit-together)

---

## What is an AI Agent?

An AI agent is a program that can:
1. **Perceive** — Take in information from its environment
2. **Reason** — Decide what to do based on that information
3. **Act** — Execute actions to achieve a goal

The key difference from a regular program is **autonomy**. A regular function does exactly what you coded. An agent decides *which* functions to call and in what order, based on the situation.

### Simple Example

```python
# Regular program (hardcoded logic)
def analyze_variant(variant):
    clinvar_result = lookup_clinvar(variant)
    classification = apply_rules(clinvar_result)
    return classification

# Agent-based approach (LLM decides the plan)
def agent_analyze_variant(variant):
    # The LLM sees the variant and available tools,
    # then decides which to call and in what order
    plan = llm.think(f"Classify {variant}. Tools: clinvar_lookup, literature_search, acmg_rules")
    results = execute_plan(plan)  # Agent picks its own path
    return results
```

### Why Agents Over Regular Code?

For simple, predictable tasks, regular code is better. Agents shine when:
- The problem has many possible paths (variant interpretation has hundreds of decision points)
- New information changes the approach (ClinVar has new data? Skip manual classification)
- The task requires natural language reasoning (synthesizing literature)
- You want the system to handle edge cases gracefully without coding every one

---

## Large Language Models (LLMs)

### What is an LLM?

A Large Language Model is a neural network trained on massive amounts of text that can generate and understand natural language. Think of it as a very sophisticated autocomplete that understands context.

Key models in this project:
- **MedGemma** — Google's medical-specialized model (trained on medical text and images)
- **Gemma 4** — Google's general-purpose open model (Apache 2.0 license, runs locally)

### How LLMs Work (Simplified)

1. You give the model a **prompt** (text input)
2. The model predicts what text should come next based on patterns learned during training
3. It generates a **response** token by token

For our use case, we structure prompts to get clinical reasoning:

```
System: You are a molecular pathologist specializing in BRCA variants.
        Classify variants using ACMG/AMP criteria.

User: Classify BRCA1 c.185A>G (chr17:41234470 A>G)
      ClinVar says: Pathogenic (3 submissions, 2-star review)
      Population frequency: Absent in gnomAD

Assistant: Based on the evidence:
         - PVS1: Null variant in gene where LOF is known mechanism
         - PM2: Absent from population databases
         - PP5: Multiple ClinVar submissions agree on Pathogenic
         Classification: Pathogenic (High confidence)
```

### Inference

"Running inference" means sending a prompt to the model and getting a response. It's the act of *using* the trained model (as opposed to *training* it, which requires massive compute).

---

## From Chatbot to Agent

A chatbot just talks. An agent acts. The key upgrade is **tool use** (also called "function calling").

### Tool Use / Function Calling

Modern LLMs can be taught to recognize when they need external information and request it by "calling a function." The flow:

```
1. User asks: "Is BRCA1 c.185A>G pathogenic?"
2. LLM thinks: "I need ClinVar data to answer this properly"
3. LLM outputs: CALL clinvar_lookup(gene="BRCA1", position=41234470, ref="A", alt="G")
4. System executes the function, gets results
5. LLM receives results and generates final answer with evidence
```

The LLM never directly accesses the database. It requests the call, your code executes it safely, and feeds results back. This is the foundation of agent architectures.

### The Agent Loop

```
while goal_not_achieved:
    observation = get_current_state()
    thought = llm.reason(observation, goal, available_tools)
    if thought.is_final_answer:
        return thought.answer
    action = thought.next_action
    result = execute_tool(action)
    update_state(result)
```

---

## Multi-Agent Systems

### Why Multiple Agents?

A single agent trying to do everything (parse VCFs, classify variants, recommend drugs, find literature) would need an enormous prompt and would struggle with context. Instead, we split responsibilities:

```
Supervisor Agent
├── VCF Parser (not an LLM — just code)
├── BRCA Agent (specialized in BRCA1/2 biology)
├── EGFR Agent (specialized in EGFR/TKI therapy)
├── TP53 Agent (specialized in tumor suppressors)
├── PGx Drug Advisor (specialized in pharmacogenomics)
└── Literature RAG Agent (specialized in evidence retrieval)
```

### Benefits of Multi-Agent Architecture

1. **Specialization** — Each agent has a focused system prompt with domain expertise
2. **Parallelism** — Classify multiple variants simultaneously
3. **Modularity** — Add new gene agents without touching existing ones
4. **Reliability** — One agent failing doesn't crash the whole pipeline
5. **Testability** — Test each agent independently

### Communication Pattern

Our agents communicate through a **supervisor** pattern:

```
User submits VCF
    → Supervisor receives request
    → Supervisor dispatches to gene agents (parallel)
    → Gene agents return classifications
    → Supervisor dispatches pathogenic variants to PGx agent
    → PGx agent returns drug recommendations
    → Supervisor dispatches to Literature agent
    → Literature agent returns evidence
    → Supervisor assembles final report
```

---

## Google Agent Development Kit (ADK) 2.0

### What is ADK?

ADK is Google's open-source framework for building AI agents. Version 2.0 (released May 2026) introduced a **graph-based workflow API** that makes multi-agent systems easier to build and reason about.

### Key Concepts

#### Graph Workflows

Instead of spaghetti if/else logic, you define agent execution as a directed graph:

```python
from google.adk import Workflow
from google.adk import workflow as wf

# Define the pipeline as a workflow graph
pipeline = Workflow(
    name="pharmagenomics_pipeline",
    edges=[
        (wf.START, parse_vcf_node),
        (parse_vcf_node, classify_node),
        (classify_node, pgx_node),
        (pgx_node, rag_node),
        (rag_node, report_node),
    ],
)
```

#### Agent Definition

```python
from google.adk import Agent

brca_agent = Agent(
    name="BRCA_Agent",
    model="medgemma",  # Which LLM to use
    system_prompt="You are a molecular pathologist specializing in BRCA1/2...",
    tools=[clinvar_lookup, acmg_classify],  # Available tools
)
```

#### Sub-Agent Delegation

The supervisor can delegate to specialized agents:

```python
supervisor = Agent(
    name="Supervisor",
    model="gemma4:12b",
    sub_agents=[brca_agent, egfr_agent, tp53_agent, pgx_agent, rag_agent],
    system_prompt="Route variants to the appropriate specialist agent..."
)
```

### Why ADK Over Custom Code?

- Built-in session management and state
- Automatic tool schema generation
- Testing and evaluation framework (agents-cli)
- Deployment support (Cloud Run, Agent Engine)
- Standardized patterns that other developers understand

---

## Model Context Protocol (MCP)

### What is MCP?

MCP is a standard protocol (like HTTP for web pages) that defines how AI agents connect to external data sources and tools. Think of it as a "USB port" for AI — any agent can plug into any MCP server.

### The Problem MCP Solves

Without MCP, every agent framework has its own way of connecting to tools. Your ClinVar integration for ADK wouldn't work with LangChain or CrewAI. MCP creates one standard:

```
Any MCP Client (ADK, LangChain, etc.)
    ↕ (standard MCP protocol)
Any MCP Server (ClinVar, CPIC, PharmGKB, etc.)
```

### How MCP Servers Work

An MCP server exposes **tools** that agents can call. Each tool has:
- A **name** (e.g., "clinvar_variant_lookup")
- A **description** (what it does — the LLM reads this to decide when to use it)
- An **input schema** (what parameters it accepts)
- An **output format** (what it returns)

### Our MCP Servers

We build three MCP servers:

#### 1. ClinVar MCP Server
```python
@mcp_server.tool()
def clinvar_variant_lookup(gene: str, chromosome: str, position: int, ref: str, alt: str):
    """Look up variant clinical significance in ClinVar database.
    Returns pathogenicity classification, review status, and submission count."""
    # Calls NCBI E-utilities REST API
    response = requests.get(f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/...")
    return parse_clinvar_response(response)
```

#### 2. CPIC MCP Server
```python
@mcp_server.tool()
def cpic_gene_drug_guidelines(gene: str):
    """Get CPIC pharmacogenomic guidelines for a gene.
    Returns drug interactions, dosing recommendations, and evidence levels."""
    # Reads from local cached JSON files (no external API needed)
    guidelines = load_cpic_data(gene)
    return guidelines
```

#### 3. PharmGKB MCP Server
```python
@mcp_server.tool()
def pharmgkb_annotations(gene: str):
    """Get PharmGKB clinical annotations for a gene.
    Returns drug associations, evidence levels, and phenotype categories."""
    # Reads from local cached TSV files
    annotations = load_pharmgkb_data(gene)
    return annotations
```

### MCP in ADK

ADK 2.0 has native MCP support. You connect an MCP server as a tool source:

```python
from google.adk.tools import MCPToolset

clinvar_tools = MCPToolset(server_command="python mcp_servers/clinvar_server.py")

pgx_agent = Agent(
    name="PGx_Drug_Advisor",
    tools=[clinvar_tools, cpic_tools, pharmgkb_tools]
)
```

---

## Retrieval-Augmented Generation (RAG)

### The Problem

LLMs are trained on data up to a cutoff date. They can't access new papers published last month. They also hallucinate — confidently stating things that aren't true.

### The Solution: RAG

RAG combines retrieval (searching documents) with generation (LLM reasoning):

```
1. User query: "Evidence for osimertinib in EGFR L858R?"
2. RETRIEVE: Search a database of medical papers for relevant ones
3. AUGMENT: Feed the retrieved papers into the LLM's prompt
4. GENERATE: LLM synthesizes an answer using ONLY the provided evidence
```

### Vector Stores and Embeddings

**The core idea:** Convert text into numbers (vectors) that capture meaning. Similar texts get similar vectors.

```
"BRCA1 pathogenic variant" → [0.82, 0.15, 0.91, ...]  (768 numbers)
"BRCA2 harmful mutation"   → [0.80, 0.17, 0.89, ...]  (similar numbers!)
"Recipe for chocolate cake"→ [0.02, 0.95, 0.11, ...]  (very different!)
```

**How retrieval works:**
1. **Index time:** Embed all your documents into vectors, store in a vector database
2. **Query time:** Embed the user's question into a vector
3. **Search:** Find the stored vectors closest to the query vector (cosine similarity)
4. **Return:** The documents attached to those vectors are your relevant results

### Our RAG Implementation

```python
# At setup time: embed and store medical literature
for paper in pubmed_abstracts:
    embedding = embed_model.encode(paper.abstract)
    vector_store.add(embedding, metadata=paper)

# At query time: find relevant papers
query = f"EGFR L858R osimertinib efficacy"
query_embedding = embed_model.encode(query)
results = vector_store.search(query_embedding, top_k=5, min_score=0.5)
```

### Why Local RAG?

- **Privacy:** Patient variant data never leaves the machine
- **Speed:** No network latency for document retrieval
- **Cost:** No API charges for embedding or search
- **Offline:** Works without internet (useful for air-gapped clinical environments)

---

## Running Models Locally with Ollama

### What is Ollama?

Ollama is a tool that lets you run LLMs on your own computer. No cloud, no API keys, no per-token billing. You download a model and run it locally.

### How It Works

```bash
# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Pull a model (downloads it to your machine)
ollama pull medgemma

# Run it (starts a local API server on port 11434)
ollama serve
```

Once running, it exposes an OpenAI-compatible API:

```python
import requests

response = requests.post("http://localhost:11434/api/generate", json={
    "model": "medgemma",
    "prompt": "Classify this BRCA1 variant..."
})
```

### Model Sizes and Hardware

| Model | Parameters | RAM Needed | Good For |
|-------|-----------|------------|----------|
| MedGemma 4B | 4 billion | ~8 GB | Medical reasoning (our primary) |
| Gemma 4 12B | 12 billion | ~7 GB (4-bit) | General reasoning, function calling |
| MedGemma 27B | 27 billion | ~16 GB (4-bit) | Best medical quality (if you have the RAM) |

### Why Ollama for This Project?

1. **Zero API keys** — Clone repo, pull model, run. No accounts anywhere.
2. **Privacy** — Patient data never leaves the machine
3. **Free** — No per-token costs. Run as many queries as your hardware allows.
4. **Reproducible** — Same model version = same results (no cloud model updates breaking things)

---

## Agents CLI

### What is Agents CLI?

Agents CLI (command-line interface) is Google's tool for managing the agent development lifecycle. It's like `npm` for Node.js or `cargo` for Rust, but for AI agents.

### Key Commands

```bash
# Scaffold a new agent project
agents create my-agent

# Run your agent locally (with hot-reload)
agents run

# Run tests
agents test

# Lint your agent configuration
agents lint

# Deploy to cloud
agents deploy
```

### Project Structure

Agents CLI expects a specific layout:

```
pharmagenomics-advisor/
├── agent.yaml          # Agent configuration (name, model, tools)
├── agents/
│   ├── supervisor/
│   │   └── agent.yaml
│   ├── brca_agent/
│   │   └── agent.yaml
│   ├── egfr_agent/
│   │   └── agent.yaml
│   ├── tp53_agent/
│   │   └── agent.yaml
│   ├── pgx_advisor/
│   │   └── agent.yaml
│   └── literature_rag/
│       └── agent.yaml
├── tools/              # MCP server definitions
│   ├── clinvar/
│   ├── cpic/
│   └── pharmgkb/
├── tests/              # Agent test cases
│   ├── test_brca.py
│   ├── test_pgx.py
│   └── test_pipeline.py
└── data/               # Local knowledge bases
    ├── cpic_guidelines.json
    └── pharmgkb_annotations.tsv
```

### Why Use Agents CLI?

- **Standardization** — Other developers immediately understand your project structure
- **Testing** — Built-in framework for testing agent behavior
- **Evaluation** — Measure agent quality with metrics
- **Deployment** — One command to deploy to Google Cloud
- **Capstone requirement** — Demonstrates "Agent skills" concept for competition scoring

---

## How These Concepts Fit Together

Here's the full picture of how every concept connects in our system:

```
┌────────────────────────────────────────────────────────────────┐
│                    PharmaGenomics Advisor                        │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              ADK 2.0 Graph Workflow                        │   │
│  │                                                            │   │
│  │  VCF Input → Parse → Classify → Drug Rec → Literature     │   │
│  │      │          │        │          │          │           │   │
│  │      ▼          ▼        ▼          ▼          ▼           │   │
│  │   [Code]    [Agents]  [Agents]   [Agent]    [Agent]        │   │
│  │              ↕    ↕      ↕          ↕                      │   │
│  │           [MCP Servers]  │    [MCP Servers]                │   │
│  │           ClinVar ←──────┘    CPIC, PharmGKB               │   │
│  └──────────────────────────────────────────────────────────┘   │
│                              │                                    │
│                              ▼                                    │
│                    ┌──────────────────┐                           │
│                    │  Ollama (Local)  │                           │
│                    │  MedGemma / Gemma│                           │
│                    │  No API Keys     │                           │
│                    └──────────────────┘                           │
│                                                                  │
│  Security: PHI detection │ Audit logs │ Input validation         │
│  Managed by: Agents CLI (scaffold, test, deploy)                 │
└────────────────────────────────────────────────────────────────┘
```

### Data Flow (End to End)

1. **User submits VCF file** → Parsed by code (no LLM needed)
2. **Variants dispatched** → Supervisor routes to gene-specific agents
3. **Gene agents classify** → Each calls ClinVar MCP, then reasons with MedGemma
4. **Pathogenic variants** → Sent to PGx Drug Advisor
5. **PGx agent recommends** → Calls CPIC and PharmGKB MCP servers
6. **Literature agent** → Searches local vector store (RAG) for supporting evidence
7. **Report generated** → JSON + Markdown, with full provenance and audit trail

### Course Concepts Demonstrated

| Concept | Where in Our Project |
|---------|---------------------|
| Multi-agent system (ADK) | Supervisor + 5 specialized agents |
| MCP Server | ClinVar, CPIC, PharmGKB servers |
| Security features | PHI detection, audit logging, input validation |
| Agent skills (Agents CLI) | Project structure, testing, deployment |
| Deployability | Docker/Cloud Run packaging |
