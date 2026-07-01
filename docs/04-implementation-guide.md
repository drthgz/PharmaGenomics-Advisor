# Implementation Guide

> Step-by-step guide for implementing the PharmaGenomics Advisor from scratch. Written so that a college-level CS student with basic Python experience can follow along.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Phase 1: Environment Setup](#phase-1-environment-setup)
3. [Phase 2: VCF Parser](#phase-2-vcf-parser)
4. [Phase 3: MCP Servers](#phase-3-mcp-servers)
5. [Phase 4: Gene Classification Agents](#phase-4-gene-classification-agents)
6. [Phase 5: PGx Drug Advisor](#phase-5-pgx-drug-advisor)
7. [Phase 6: Literature RAG](#phase-6-literature-rag)
8. [Phase 7: Supervisor & Graph Workflow](#phase-7-supervisor--graph-workflow)
9. [Phase 8: Security Layer](#phase-8-security-layer)
10. [Phase 9: Clinical Report Generation](#phase-9-clinical-report-generation)
11. [Phase 10: Testing & Demo](#phase-10-testing--demo)

---

## Prerequisites

### Skills Needed

- Python 3.10+ (functions, classes, async, type hints)
- Basic understanding of REST APIs (GET/POST, JSON responses)
- Command line comfort (running scripts, installing packages)
- Git basics (clone, commit, push)

### Hardware Requirements

- **Minimum:** 16 GB RAM, any modern CPU (for MedGemma 4B via Ollama)
- **Recommended:** 16+ GB RAM, NVIDIA GPU with 8+ GB VRAM (faster inference)
- **Disk:** ~10 GB free (model weights + data)

### Software Requirements

- Python 3.10+
- Ollama (LLM runtime)
- Git
- A code editor (VS Code recommended)

---

## Phase 1: Environment Setup

### Step 1: Install Ollama

```bash
# Linux/macOS
curl -fsSL https://ollama.com/install.sh | sh

# Windows: Download from https://ollama.com/download

# Verify installation
ollama --version
```

### Step 2: Pull the LLM Model

```bash
# Pull MedGemma (medical-specialized, ~4.7 GB download)
ollama pull medgemma

# OR pull Gemma 4 12B (general purpose, better function calling)
ollama pull gemma4:12b

# Verify the model is available
ollama list
```

### Step 3: Create Project Structure

```bash
mkdir pharmagenomics-advisor
cd pharmagenomics-advisor

# Create directory structure
mkdir -p agents/{supervisor,brca_agent,egfr_agent,tp53_agent,pgx_advisor,literature_rag}
mkdir -p src/{pipeline,parsers,security,rag}
mkdir -p mcp_servers
mkdir -p data/{cpic,pharmgkb,literature,samples}
mkdir -p tests/{unit,integration,properties}
mkdir -p scripts
mkdir -p docs
```

### Step 4: Set Up Python Environment

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate

pip install google-adk>=2.0.0
pip install ollama
pip install chromadb
pip install sentence-transformers
pip install httpx
pip install pytest pytest-asyncio
pip install pydantic
```

### Step 5: Verify Ollama Connection

```python
# test_ollama.py — Run this to verify everything works
import ollama

response = ollama.generate(
    model="medgemma",
    prompt="What is the ACMG classification for a BRCA1 frameshift variant?"
)
print(response['response'])
```

---

## Phase 2: VCF Parser

### What We're Building

A parser that reads VCF files and produces structured `Variant` objects. No LLM involved — this is pure deterministic code.

### The Variant Data Model

```python
# src/parsers/vcf_parser.py
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class VariantType(Enum):
    MISSENSE = "missense"
    NONSENSE = "nonsense"
    FRAMESHIFT = "frameshift"
    SILENT = "silent"
    SPLICE = "splice"
    UNKNOWN = "unknown"


class RouteStatus(Enum):
    ROUTED = "routed"
    UNROUTED = "unrouted"


@dataclass
class Variant:
    chromosome: str
    position: int
    id: str
    ref_allele: str
    alt_allele: str
    quality: float
    filter_status: str
    info: dict
    gene: Optional[str] = None
    variant_type: VariantType = VariantType.UNKNOWN
    hgvs: Optional[str] = None
    route_status: RouteStatus = RouteStatus.UNROUTED
```

### Parsing Logic

```python
SUPPORTED_GENES = {"BRCA1", "BRCA2", "EGFR", "TP53"}
MAX_VARIANTS = 10_000


def parse_vcf(file_path: str) -> list[Variant]:
    """Parse a VCF file into a list of Variant objects.
    
    Raises:
        VCFFormatError: If the file doesn't conform to VCF 4.x spec
        VCFEmptyError: If no variant records are found
        VCFTooLargeError: If variant count exceeds MAX_VARIANTS
    """
    variants = []
    
    with open(file_path, 'r') as f:
        for line_num, line in enumerate(f, 1):
            if line.startswith('#'):
                continue  # Skip header lines
            
            fields = line.strip().split('\t')
            if len(fields) < 8:
                raise VCFFormatError(f"Line {line_num}: expected 8+ fields, got {len(fields)}")
            
            variant = Variant(
                chromosome=fields[0],
                position=int(fields[1]),
                id=fields[2],
                ref_allele=fields[3],
                alt_allele=fields[4],
                quality=float(fields[5]) if fields[5] != '.' else 0.0,
                filter_status=fields[6],
                info=parse_info_field(fields[7])
            )
            
            # Extract gene from INFO field
            variant.gene = extract_gene(variant.info)
            
            # Determine routing
            if variant.gene in SUPPORTED_GENES:
                variant.route_status = RouteStatus.ROUTED
            
            variants.append(variant)
            
            if len(variants) > MAX_VARIANTS:
                raise VCFTooLargeError(f"File exceeds {MAX_VARIANTS} variants")
    
    if not variants:
        raise VCFEmptyError("No variant records found")
    
    return variants
```

### Round-Trip Property (Key Correctness Check)

```python
def format_variant_to_vcf(variant: Variant) -> str:
    """Convert a Variant object back to a VCF line string."""
    info_str = format_info_field(variant.info)
    return f"{variant.chromosome}\t{variant.position}\t{variant.id}\t" \
           f"{variant.ref_allele}\t{variant.alt_allele}\t{variant.quality}\t" \
           f"{variant.filter_status}\t{info_str}"


# The round-trip property: parse → format → parse should give equivalent objects
# This is tested with property-based testing (hypothesis library)
```

---

## Phase 3: MCP Servers

### What We're Building

Three standalone Python servers that expose genomics databases as MCP tool endpoints.

### ClinVar MCP Server (External API)

```python
# mcp_servers/clinvar_server.py
from mcp.server import Server
from mcp.types import Tool
import httpx

app = Server("clinvar-server")

@app.tool()
async def clinvar_variant_lookup(
    gene: str,
    chromosome: str, 
    position: int,
    ref: str,
    alt: str
) -> dict:
    """Look up a variant's clinical significance in ClinVar.
    
    Args:
        gene: Gene symbol (e.g., "BRCA1")
        chromosome: Chromosome (e.g., "chr17")
        position: Genomic position
        ref: Reference allele
        alt: Alternate allele
    
    Returns:
        Clinical significance, review status, and submission count
    """
    # Build NCBI E-utilities query
    search_term = f"{gene}[gene] AND {chromosome.replace('chr','')}[chr] AND {position}[chrpos]"
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Step 1: Search for the variant
        search_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        search_resp = await client.get(search_url, params={
            "db": "clinvar",
            "term": search_term,
            "retmode": "json"
        })
        
        ids = search_resp.json().get("esearchresult", {}).get("idlist", [])
        
        if not ids:
            return {"status": "no records found", "results": []}
        
        # Step 2: Fetch variant details
        fetch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
        fetch_resp = await client.get(fetch_url, params={
            "db": "clinvar",
            "id": ",".join(ids[:5]),
            "retmode": "json"
        })
        
        return parse_clinvar_response(fetch_resp.json())

if __name__ == "__main__":
    app.run()
```

### CPIC MCP Server (Local Data)

```python
# mcp_servers/cpic_server.py
from mcp.server import Server
import json
from pathlib import Path

app = Server("cpic-server")

# Load CPIC data at startup
CPIC_DATA = json.loads(Path("data/cpic/guidelines.json").read_text())

@app.tool()
async def cpic_gene_drug_guidelines(gene: str) -> dict:
    """Get CPIC pharmacogenomic guidelines for a specific gene.
    
    Args:
        gene: Gene symbol (e.g., "CYP2C19", "BRCA1")
    
    Returns:
        List of gene-drug guidelines with recommendation strength 
        and phenotype-based dosing information
    """
    gene_upper = gene.upper()
    guidelines = [g for g in CPIC_DATA if g["gene"] == gene_upper]
    
    if not guidelines:
        return {"status": "no records found", "results": []}
    
    return {
        "status": "success",
        "gene": gene_upper,
        "guideline_count": len(guidelines),
        "results": guidelines
    }

if __name__ == "__main__":
    app.run()
```

### PharmGKB MCP Server (Local Data)

```python
# mcp_servers/pharmgkb_server.py
from mcp.server import Server
import csv
from pathlib import Path

app = Server("pharmgkb-server")

# Load PharmGKB annotations at startup
PHARMGKB_DATA = load_pharmgkb_tsv("data/pharmgkb/annotations.tsv")

@app.tool()
async def pharmgkb_annotations(gene: str) -> dict:
    """Get PharmGKB clinical annotations for a gene.
    
    Args:
        gene: Gene symbol or variant ID
    
    Returns:
        Clinical annotations including evidence level, 
        drug associations, and phenotype categories
    """
    results = [a for a in PHARMGKB_DATA if a["gene"] == gene.upper()]
    
    if not results:
        return {"status": "no records found", "results": []}
    
    return {
        "status": "success", 
        "gene": gene.upper(),
        "annotation_count": len(results),
        "results": results
    }

if __name__ == "__main__":
    app.run()
```

---

## Phase 4: Gene Classification Agents

### Agent Definition Pattern

Each gene agent follows the same pattern:

```python
# Example: agents/brca_agent/agent.yaml
name: BRCA_Agent
model: medgemma
description: "Classifies BRCA1/BRCA2 variants using ACMG/AMP criteria"
tools:
  - clinvar_variant_lookup
system_prompt: |
  You are a molecular pathologist specializing in BRCA1 and BRCA2 variants 
  associated with hereditary breast and ovarian cancer syndrome.
  
  For each variant you receive, you must:
  1. Query ClinVar for existing classifications
  2. Apply ACMG/AMP criteria to classify the variant
  3. Return a structured classification
  
  Classification must be one of: Pathogenic, Likely Pathogenic, VUS, 
  Likely Benign, Benign.
  
  Confidence must be one of: High, Moderate, Low.
  
  Always provide at least one supporting evidence reference.
  
  BRCA-specific considerations:
  - Frameshift and nonsense variants in BRCA1/2 are typically Pathogenic (PVS1)
  - RING domain (BRCA1 aa 1-109) and BRCT domain (aa 1650-1863) are critical
  - Variants absent from gnomAD support pathogenicity (PM2)
```

### Agent Response Format

```python
@dataclass
class VariantClassification:
    gene: str
    variant: str
    classification: str          # Pathogenic | Likely Pathogenic | VUS | Likely Benign | Benign
    confidence: str              # High | Moderate | Low
    evidence_references: list    # At least one citation
    therapeutic_relevance: str   # For EGFR: TKI-sensitive | TKI-resistant | unknown
    functional_status: str       # For TP53: gain-of-function | loss-of-function | undetermined
    clinvar_data: dict           # Raw ClinVar response (if available)
    data_sources_queried: list   # Which MCP servers were called
    limitations: list            # Any flags (e.g., "ClinVar unavailable")
```

---

## Phase 5: PGx Drug Advisor

### What It Does

Takes classified variants and returns drug recommendations:

```
Input: EGFR L858R, Pathogenic, TKI-sensitive
Output: [
  {drug: "Osimertinib", action: "recommended first-line", evidence: "A"},
  {drug: "Gefitinib", action: "alternative", evidence: "A"},
  {drug: "Erlotinib", action: "alternative", evidence: "A"}
]
```

### Decision Flow

```python
async def generate_drug_recommendations(classification: VariantClassification) -> list[DrugRecommendation]:
    recommendations = []
    
    # Only process actionable variants
    if classification.classification not in ("Pathogenic", "Likely Pathogenic"):
        return []
    
    # Check CPIC guidelines
    cpic_results = await cpic_mcp.cpic_gene_drug_guidelines(classification.gene)
    for guideline in cpic_results.get("results", []):
        recommendations.append(DrugRecommendation(
            drug_name=guideline["drug"],
            gene=classification.gene,
            variant=classification.variant,
            action=guideline["recommendation"],
            evidence_level=guideline["cpic_level"],
            source_url=guideline["url"],
            contraindications=guideline.get("contraindications", [])
        ))
    
    # For EGFR with therapeutic relevance, also check PharmGKB
    if classification.gene == "EGFR" and classification.therapeutic_relevance == "TKI-sensitive":
        pharmgkb_results = await pharmgkb_mcp.pharmgkb_annotations(classification.gene)
        # Process targeted therapy annotations...
    
    # Sort by evidence level (A > B > C > D)
    recommendations.sort(key=lambda r: r.evidence_level)
    
    # Cap at 10 per variant
    return recommendations[:10]
```

---

## Phase 6: Literature RAG

### Building the Vector Store

```python
# scripts/index_literature.py
from sentence_transformers import SentenceTransformer
import chromadb
import json

# Load embedding model (small, fast, ~90 MB)
embed_model = SentenceTransformer("all-MiniLM-L6-v2")

# Create local vector store
client = chromadb.PersistentClient(path="data/literature/vectordb")
collection = client.get_or_create_collection("pubmed_abstracts")

# Load pre-downloaded abstracts
with open("data/literature/pubmed_abstracts.json") as f:
    abstracts = json.load(f)

# Embed and store
for i, paper in enumerate(abstracts):
    text = f"{paper['title']} {paper['abstract']}"
    embedding = embed_model.encode(text).tolist()
    
    collection.add(
        ids=[str(i)],
        embeddings=[embedding],
        metadatas=[{
            "title": paper["title"],
            "authors": paper["authors"],
            "journal": paper["journal"],
            "year": paper["year"],
            "doi": paper["doi"]
        }],
        documents=[text]
    )

print(f"Indexed {len(abstracts)} papers")
```

### Querying the Vector Store

```python
# src/rag/vector_store.py
def search_literature(query: str, top_k: int = 5, min_score: float = 0.5) -> list[dict]:
    """Search for relevant literature using semantic similarity.
    
    Args:
        query: Natural language query (e.g., "EGFR L858R osimertinib efficacy")
        top_k: Maximum number of results
        min_score: Minimum cosine similarity threshold
    
    Returns:
        List of papers with metadata and relevance scores
    """
    query_embedding = embed_model.encode(query).tolist()
    
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k
    )
    
    # Filter by minimum score and format results
    papers = []
    for i, (doc, metadata, distance) in enumerate(zip(
        results["documents"][0],
        results["metadatas"][0], 
        results["distances"][0]
    )):
        score = 1 - distance  # Convert distance to similarity
        if score >= min_score:
            papers.append({
                "title": metadata["title"],
                "authors": metadata["authors"],
                "journal": metadata["journal"],
                "year": metadata["year"],
                "doi": metadata["doi"],
                "relevance_score": round(score, 3)
            })
    
    return papers
```

---

## Phase 7: Supervisor & Graph Workflow

### ADK 2.0 Graph Definition

```python
# src/pipeline/graph.py
from google.adk import Graph, Agent
from google.adk.tools import MCPToolset

# Create the pipeline graph
pipeline = Graph(name="pharmagenomics_pipeline")

# Define nodes
pipeline.add_node("input_validation", validate_and_parse_vcf)
pipeline.add_node("variant_classification", classify_variants_parallel)
pipeline.add_node("drug_recommendations", generate_drug_recs)
pipeline.add_node("literature_evidence", retrieve_evidence)
pipeline.add_node("report_generation", assemble_report)

# Define edges (execution flow)
pipeline.add_edge("input_validation", "variant_classification")
pipeline.add_edge("variant_classification", "drug_recommendations")
pipeline.add_edge("drug_recommendations", "literature_evidence")
pipeline.add_edge("literature_evidence", "report_generation")
```

### Supervisor Logic

```python
# src/pipeline/supervisor.py
async def classify_variants_parallel(variants: list[Variant]) -> list[VariantClassification]:
    """Dispatch variants to gene-specific agents in parallel."""
    import asyncio
    
    tasks = []
    for variant in variants:
        if variant.route_status == RouteStatus.UNROUTED:
            continue
        
        agent = get_agent_for_gene(variant.gene)
        tasks.append(classify_with_timeout(agent, variant, timeout=60))
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    classifications = []
    for result in results:
        if isinstance(result, Exception):
            # Log failure, mark as unavailable
            classifications.append(create_unavailable_result(result))
        else:
            classifications.append(result)
    
    return classifications
```

---

## Phase 8: Security Layer

### Input Validation

```python
# src/security/input_validator.py
import re

INJECTION_PATTERNS = [
    r"(?i)(SELECT|INSERT|UPDATE|DELETE|DROP|UNION)\s",  # SQL
    r"(?i)(ignore\s+(previous|above)\s+instructions)",   # Prompt injection
    r"[;|`$]\s*(rm|cat|curl|wget)\s",                    # Command injection
]

def validate_input(text: str) -> tuple[bool, str]:
    """Check input for injection patterns and size limits.
    
    Returns:
        (is_valid, error_message)
    """
    if len(text) > 10_000:
        return False, "Input exceeds 10,000 character limit"
    
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, text):
            return False, f"Input rejected: potentially malicious pattern detected"
    
    return True, ""
```

### Audit Logging

```python
# src/security/audit_log.py
import hashlib
import json
from datetime import datetime, timezone

def log_agent_invocation(agent_name: str, action: str, input_data: str, output_data: str):
    """Append an immutable audit record."""
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent": agent_name,
        "action": action,
        "input_hash": hashlib.sha256(input_data.encode()).hexdigest(),
        "output_hash": hashlib.sha256(output_data.encode()).hexdigest()
    }
    
    with open("audit.log", "a") as f:
        f.write(json.dumps(record) + "\n")
```

---

## Phase 9: Clinical Report Generation

### Report Structure

```python
# src/pipeline/report.py
@dataclass
class ClinicalReport:
    # Header
    report_id: str
    generated_at: str  # ISO 8601
    pipeline_version: str
    total_execution_time_seconds: float
    
    # Content
    variant_summary: list[dict]
    classifications: list[VariantClassification]
    drug_recommendations: list[DrugRecommendation]
    literature_evidence: list[dict]
    
    # Metadata
    provenance: list[dict]  # Per-finding source tracking
    warnings: list[dict]    # Degraded results, timeouts, etc.
    
    def to_json(self) -> str:
        """Serialize to JSON (must be round-trip safe)."""
        return json.dumps(asdict(self), indent=2, default=str)
    
    def to_markdown(self) -> str:
        """Generate human-readable clinical summary (≤1000 words)."""
        # ... generate markdown sections ...
```

---

## Phase 10: Testing & Demo

### Property-Based Tests

```python
# tests/properties/test_vcf_roundtrip.py
from hypothesis import given, strategies as st

@given(st.text(alphabet="ATCG", min_size=1, max_size=50))
def test_vcf_roundtrip(allele):
    """Parsing → formatting → parsing produces equivalent variant."""
    variant = Variant(
        chromosome="chr17", position=41234470,
        ref_allele="A", alt_allele=allele, ...
    )
    vcf_line = format_variant_to_vcf(variant)
    reparsed = parse_vcf_line(vcf_line)
    
    assert reparsed.chromosome == variant.chromosome
    assert reparsed.position == variant.position
    assert reparsed.ref_allele == variant.ref_allele
    assert reparsed.alt_allele == variant.alt_allele
```

### Demo Script

```python
# scripts/demo.py
"""End-to-end demonstration: VCF → Clinical Report in ~5 minutes."""

import asyncio
from src.pipeline.graph import pipeline

async def main():
    print("=" * 60)
    print("PharmaGenomics Advisor — End-to-End Demo")
    print("=" * 60)
    
    # Run the full pipeline on sample data
    report = await pipeline.run(input_file="data/samples/sample_variants.vcf")
    
    # Display results
    print(f"\nVariants analyzed: {len(report.variant_summary)}")
    print(f"Classifications: {len(report.classifications)}")
    print(f"Drug recommendations: {len(report.drug_recommendations)}")
    print(f"Literature citations: {len(report.literature_evidence)}")
    print(f"\nExecution time: {report.total_execution_time_seconds:.1f}s")
    print(f"\nReport saved to: output/report.json")
    print(f"Summary saved to: output/report.md")

if __name__ == "__main__":
    asyncio.run(main())
```
