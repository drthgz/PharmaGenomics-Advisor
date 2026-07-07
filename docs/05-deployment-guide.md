# Deployment & Demo Guide

> How to set up, run, and demonstrate the PharmaGenomics Advisor system. Covers local development, Docker deployment, and preparing the Kaggle capstone submission.

## Table of Contents

1. [Quick Start (5 Minutes)](#quick-start-5-minutes)
2. [Detailed Local Setup](#detailed-local-setup)
3. [Docker Deployment](#docker-deployment)
4. [Running the Demo](#running-the-demo)
5. [Preparing the Kaggle Submission](#preparing-the-kaggle-submission)
6. [Troubleshooting](#troubleshooting)

---

## Quick Start (5 Minutes)

```bash
# 1. Clone the repository
git clone https://github.com/drthgz/pharmagenomics-advisor.git
cd pharmagenomics-advisor

# 2. Run the setup script (installs Ollama + pulls model + installs deps)
bash scripts/setup.sh

# 3. Run the demo
python3 scripts/demo.py
```

That's it. No API keys. No cloud accounts. No configuration.

---

## Detailed Local Setup

### Step 1: System Requirements Check

| Requirement | Minimum | Recommended |
|------------|---------|-------------|
| OS | Windows 10, macOS 12, Ubuntu 20.04 | Latest |
| RAM | 16 GB | 32 GB |
| Disk | 10 GB free | 20 GB free |
| GPU | None (CPU works) | NVIDIA with 8+ GB VRAM |
| Python | 3.10 | 3.11 or 3.12 |
| Internet | Required for setup + ClinVar | Required for setup + ClinVar |

### Step 2: Install Ollama

**Linux/macOS:**
```bash
curl -fsSL https://ollama.com/install.sh | sh
```

**Windows:**
Download from https://ollama.com/download and run the installer.

**Verify:**
```bash
ollama --version
# Expected: ollama version 0.x.x
```

### Step 3: Pull the Model

```bash
# Option A: MedGemma (medical-specialized, recommended)
ollama pull medgemma
# Download size: ~4.7 GB, RAM usage: ~8 GB

# Option B: Gemma 4 12B (better function calling, larger)
ollama pull gemma4:12b
# Download size: ~7 GB, RAM usage: ~7 GB at 4-bit

# Verify model is available
ollama list
```

### Step 4: Clone and Install Python Dependencies

```bash
git clone https://github.com/drthgz/pharmagenomics-advisor.git
cd pharmagenomics-advisor

python3 -m pip install --upgrade pip
python3 -m pip install -e ".[dev]"
```

### Step 5: Download Knowledge Base Data

```bash
# Download CPIC guidelines (free, no account)
python scripts/download_cpic_data.py

# Download PharmGKB annotations (free, no account for basic data)
python scripts/download_pharmgkb.py

# Index literature for RAG (uses pre-bundled abstracts)
python scripts/index_literature.py
```

### Step 6: Verify Installation

```bash
# Run the test suite
python3 -m pytest tests/ -v

# Run a quick pipeline test
python3 scripts/demo.py --runtime local
python3 scripts/demo.py --runtime adk
```

---

## Docker Deployment

### Build the Image

```dockerfile
# Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Install Ollama
RUN curl -fsSL https://ollama.com/install.sh | sh

# Copy project
COPY . .

# Install Python dependencies
RUN pip install -e .

# Download data
RUN python scripts/download_cpic_data.py
RUN python scripts/download_pharmgkb.py

# Expose port for MCP servers
EXPOSE 8000

# Start script pulls model and runs
CMD ["bash", "docker-entrypoint.sh"]
```

### Build and Run

```bash
docker build -t pharmagenomics-advisor .
docker run -it --gpus all -p 8000:8000 pharmagenomics-advisor
```

### Docker Compose (Full Stack)

```yaml
# docker-compose.yml
version: '3.8'
services:
  ollama:
    image: ollama/ollama:latest
    ports:
      - "11434:11434"
    volumes:
      - ollama_data:/root/.ollama
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
  
  advisor:
    build: .
    depends_on:
      - ollama
    environment:
      - OLLAMA_HOST=http://ollama:11434
    ports:
      - "8000:8000"

volumes:
  ollama_data:
```

---

## Running the Demo

### Full Pipeline Demo (For Video Recording)

```bash
# Start with a clear terminal
clear

echo "=== PharmaGenomics Advisor Demo ==="
echo "Multi-Agent Precision Medicine Pipeline"
echo ""

# Show the sample VCF file
echo "1. Input: Sample VCF with cancer variants"
cat data/samples/sample_variants.vcf | head -20
echo ""

# Run the pipeline
echo "2. Running pipeline..."
python3 scripts/demo.py

# Optional: storytelling scenario (resistant EGFR + unrouted KRAS)
python3 scripts/demo.py --vcf data/samples/sample_variants_storytelling.vcf

# Show the output report
echo "3. Clinical Report:"
cat output/report.md
echo "4. Official HTML Report: output/report.html"
```

### Sample VCF for Demo

```vcf
##fileformat=VCFv4.2
##INFO=<ID=Gene,Number=1,Type=String,Description="Gene name">
##INFO=<ID=Type,Number=1,Type=String,Description="Variant type">
#CHROM	POS	ID	REF	ALT	QUAL	FILTER	INFO
chr17	41234470	.	A	G	99	PASS	Gene=BRCA1;Type=missense;HGVS=c.185A>G
chr7	55259515	.	T	G	95	PASS	Gene=EGFR;Type=missense;HGVS=c.2573T>G;Note=L858R
chr17	7578406	.	C	T	88	PASS	Gene=TP53;Type=missense;HGVS=c.743G>A;Note=R248W
```

### Expected Demo Output

```
=== PharmaGenomics Advisor — Clinical Report ===

Variants Analyzed: 3
Execution Time: 47.2 seconds

--- VARIANT 1: BRCA1 c.185A>G ---
Classification: Pathogenic (High confidence)
Evidence: ClinVar Pathogenic (3 submissions), ACMG criteria PVS1+PM2
Drug Recommendations:
  • Olaparib (PARP inhibitor) — Recommended for BRCA1-deficient tumors
    Evidence Level: A | Source: CPIC

--- VARIANT 2: EGFR L858R ---
Classification: Pathogenic (High confidence)  
Therapeutic Relevance: TKI-sensitive
Drug Recommendations:
  • Osimertinib — Recommended first-line targeted therapy
    Evidence Level: A | Source: PharmGKB
  • Gefitinib — Alternative TKI option
    Evidence Level: A | Source: PharmGKB

--- VARIANT 3: TP53 R248W ---
Classification: Pathogenic (High confidence)
Functional Status: Gain-of-function
Drug Recommendations:
  • No established pharmacogenomic guideline found for this variant
  • Impact: No gene-drug recommendation was generated
  • Recommended action: review NCCN/ESMO guidance + trial eligibility + tumor board

--- LITERATURE EVIDENCE ---
5 papers retrieved (relevance scores: 0.89, 0.85, 0.82, 0.78, 0.71)
Synthesis: Evidence strongly supports osimertinib as first-line therapy 
for EGFR L858R mutations in NSCLC, with response rates of 70-80%...

--- WARNINGS ---
pgx/TP53: No established pharmacogenomic guideline found for this variant
Impact: No gene-drug recommendation was generated
Recommended action: review NCCN/ESMO guidance + trial eligibility + tumor board
```

---

## Preparing the Kaggle Submission

### Deliverables Checklist

- [ ] **Public GitHub Repository**
  - README with setup instructions
  - All source code with comments
  - Sample VCF files
  - Architecture diagrams
  - No API keys or secrets committed

- [ ] **Kaggle Writeup** (≤2,500 words)
  - Problem statement
  - Solution architecture
  - Implementation highlights
  - Results and demo
  - Course concepts demonstrated

- [ ] **YouTube Video** (≤5 minutes)
  - Problem introduction (30 sec)
  - Architecture walkthrough (60 sec)
  - Live demo (2-3 min)
  - Impact and closing (30 sec)

- [ ] **Track Selection:** Agents for Good

### Video Recording Tips

1. Use a screen recorder (OBS Studio is free)
2. Increase terminal font size to 18+
3. Clear your terminal before recording
4. Pre-pull the Ollama model (don't make viewers watch a download)
5. Have architecture diagrams ready as images
6. Practice the demo flow once before recording
7. Keep it under 5 minutes (judges watch many videos)

### Writing the Kaggle Writeup

Structure suggestion:
```
Title: PharmaGenomics Advisor — Multi-Agent Precision Medicine Pipeline

1. Problem Statement (300 words)
   - Cancer genomics bottleneck
   - Time and cost of manual interpretation
   - Accessibility gap

2. Solution Overview (400 words)
   - Multi-agent architecture
   - PGx drug recommendations (what's new)
   - Local-first design

3. Technical Architecture (500 words)
   - ADK 2.0 graph workflow
   - MCP servers (ClinVar, CPIC, PharmGKB)
   - Security and guardrails

4. Implementation Highlights (500 words)
   - Ollama integration (zero API keys)
   - Agent specialization strategy
   - RAG for literature evidence

5. Course Concepts Demonstrated (400 words)
   - Multi-agent (ADK) ✓
   - MCP Server ✓
   - Security ✓
   - Agents CLI ✓
   - Deployability ✓

6. Results & Impact (400 words)
   - Demo results
   - Time savings
   - Accessibility improvement
```

---

## Troubleshooting

### "Ollama not found"

```bash
# Check if Ollama is installed
which ollama  # Linux/macOS
where ollama  # Windows

# If not found, reinstall
curl -fsSL https://ollama.com/install.sh | sh
```

### "Model not found"

```bash
# List available models
ollama list

# Pull the model if missing
ollama pull medgemma
```

### "Connection refused" (Ollama not running)

```bash
# Start Ollama service
ollama serve

# Or run in background
ollama serve &
```

### "Out of memory" (OOM)

```bash
# Use a smaller model
ollama pull medgemma  # 4B is smaller than gemma4:12b

# Or use CPU-only mode (slower but works)
OLLAMA_NUM_GPU=0 ollama serve
```

### "ClinVar MCP timeout"

This is expected when NCBI servers are slow. The pipeline will:
1. Continue with local-only classification
2. Flag results as "limited evidence"
3. Still produce a valid report

### "Vector store empty"

```bash
# Re-index the literature
python scripts/index_literature.py

# Verify index
python -c "import chromadb; c = chromadb.PersistentClient('data/literature/vectordb'); print(c.get_collection('pubmed_abstracts').count())"
```

### Common Python Issues

```bash
# Wrong Python version
python3 --version  # Must be 3.10+

# Missing dependencies
python3 -m pip install -e ".[dev]"

# ADK runtime missing
python3 -m pip install "google-adk>=2.0.0"
```
