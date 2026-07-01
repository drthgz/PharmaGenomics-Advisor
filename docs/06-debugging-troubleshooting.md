# Debugging & Troubleshooting Guide

> A comprehensive guide for diagnosing and fixing issues when developing, testing, or running the PharmaGenomics Advisor pipeline. Organized by symptom for quick lookup.

## Table of Contents

1. [Quick Diagnostic Checklist](#quick-diagnostic-checklist)
2. [Ollama Issues](#ollama-issues)
3. [Model Inference Issues](#model-inference-issues)
4. [VCF Parser Issues](#vcf-parser-issues)
5. [MCP Server Issues](#mcp-server-issues)
6. [Security Layer Issues](#security-layer-issues)
7. [Agent Issues](#agent-issues)
8. [RAG / Vector Store Issues](#rag--vector-store-issues)
9. [Import / Dependency Issues](#import--dependency-issues)
10. [Test Failures](#test-failures)
11. [GPU / Performance Issues](#gpu--performance-issues)
12. [Debug Tools and Techniques](#debug-tools-and-techniques)
13. [Common Error Messages Reference](#common-error-messages-reference)

---

## Quick Diagnostic Checklist

Run these in order when something isn't working:

```bash
# 1. Is Ollama running?
curl http://localhost:11434/api/tags

# 2. Is the model pulled?
ollama list

# 3. Are dependencies installed?
pip list | grep -E "google-adk|fastmcp|pydantic|chromadb"

# 4. Can Python find our modules?
python -c "from src.models import Variant; print('OK')"

# 5. Do basic tests pass?
pytest tests/unit/test_vcf_parser.py -v

# 6. Can Ollama generate a response?
python -c "import ollama; print(ollama.generate(model='medgemma', prompt='hello')['response'][:50])"
```

---

## Ollama Issues

### Symptom: "Connection refused" or "Ollama not running"

**Cause:** The Ollama service isn't started.

**Fix:**
```bash
# Start Ollama
ollama serve

# Or run in background (Linux/macOS)
ollama serve &

# Windows (PowerShell)
Start-Process ollama -ArgumentList "serve" -NoNewWindow
```

**Verify:**
```bash
curl http://localhost:11434/api/tags
# Should return JSON with model list
```

### Symptom: "Model not found" / OllamaModelNotFoundError

**Cause:** The required model hasn't been pulled yet.

**Fix:**
```bash
# Pull MedGemma
ollama pull medgemma

# Or if you prefer Gemma 4
ollama pull gemma4:12b

# Verify
ollama list
```

### Symptom: Ollama starts but model download fails

**Cause:** Network issues or insufficient disk space.

**Fix:**
```bash
# Check disk space (model needs ~5 GB)
df -h .  # Linux/macOS
# Or: Get-PSDrive C  # Windows

# Check network
curl -I https://ollama.com

# Try alternative model (smaller)
ollama pull gemma2:2b  # Only 1.5 GB, for testing
```

### Symptom: Ollama running on non-default port

**Fix:** Set the environment variable:
```bash
export OLLAMA_PORT=11435  # Linux/macOS
$env:OLLAMA_PORT = "11435"  # Windows PowerShell
```

---

## Model Inference Issues

### Symptom: Very slow responses (>2 minutes per query)

**Causes & Fixes:**

1. **No GPU detected (running on CPU)**
```bash
# Check if GPU is being used
nvidia-smi  # Should show ollama process using GPU

# If GPU not detected, check CUDA
nvcc --version

# Force GPU layers (NVIDIA)
OLLAMA_NUM_GPU=99 ollama serve
```

2. **Model too large for available VRAM**
```bash
# Check VRAM usage
nvidia-smi

# Use smaller model
ollama pull medgemma  # 4B is smallest option

# Or quantize further (if supported)
ollama run medgemma --quantize q4_0
```

3. **System running out of RAM**
```bash
# Check memory
free -h  # Linux
# Or: Get-Process ollama | Select-Object WorkingSet64  # Windows

# Reduce context size (in API calls)
# Use shorter prompts
```

### Symptom: Model gives garbage / irrelevant output

**Cause:** System prompt not being applied correctly, or model overloaded.

**Debug:**
```python
import ollama

# Test with explicit system prompt
response = ollama.chat(
    model='medgemma',
    messages=[
        {'role': 'system', 'content': 'You are a molecular pathologist. Classify variants using ACMG criteria.'},
        {'role': 'user', 'content': 'Classify BRCA1 c.185A>G. ClinVar: Pathogenic (3 submissions). Absent from gnomAD.'}
    ]
)
print(response['message']['content'])
```

### Symptom: "context length exceeded" error

**Cause:** Prompt + response exceeds model's context window.

**Fix:**
```python
# Reduce prompt length by being more concise
# MedGemma 4B has a context window that supports standard use cases
# Keep total input under 4096 tokens

# Truncate long INFO fields from VCF before sending to model
variant_info = str(variant.info)[:500]  # Limit info context
```

---

## VCF Parser Issues

### Symptom: VCFFormatError with specific field

**Debug:**
```python
from src.parsers.vcf_parser import parse_vcf_line

# Parse the problematic line
line = "your\tVCF\tline\there"
try:
    variant = parse_vcf_line(line, line_num=1)
except Exception as e:
    print(f"Error: {e}")
    # Error message will tell you the field name and line number
```

**Common causes:**
- Spaces instead of tabs (VCF requires tab separation)
- Non-numeric position field
- Invalid allele characters (only ATCGN allowed)
- Missing mandatory columns (need at least 8)

### Symptom: Gene not being detected from INFO field

**Debug:**
```python
from src.parsers.vcf_parser import _parse_info_field, _extract_gene

info_str = "your;INFO;field=here"
info = _parse_info_field(info_str)
print(f"Parsed INFO: {info}")

gene = _extract_gene(info)
print(f"Extracted gene: {gene}")
```

**Common causes:**
- Gene key not matching expected keys (we check: Gene, GENE, gene, ANN)
- SnpEff ANN format different from expected
- Gene name not uppercase in the file

### Symptom: All variants showing as "unrouted"

**Check:** Are gene annotations present in the VCF?
```bash
# Look at INFO column
head -20 your_file.vcf | cut -f8 | grep -i gene
```

If no gene annotations, you'll need to annotate the VCF first (using tools like SnpEff or VEP).

---

## MCP Server Issues

### Symptom: ClinVar MCP timeout (>30s)

**Cause:** NCBI servers are slow or rate-limiting you.

**Fix:** This is expected behavior. The pipeline will:
1. Continue with local-only classification
2. Flag result as "limited evidence — ClinVar unavailable"

**If persistent:** NCBI rate-limits unauthenticated requests to 3/second. Add a delay:
```python
import time
time.sleep(0.4)  # 400ms between requests
```

### Symptom: CPIC/PharmGKB server returns "no records found"

**Debug:**
```python
import asyncio
from mcp_servers.cpic_server import cpic_gene_drug_guidelines, CPIC_DATA

# Check what data is loaded
print(f"CPIC data entries: {len(CPIC_DATA)}")
print(f"Genes available: {set(g['gene'] for g in CPIC_DATA)}")

# Test query
result = asyncio.run(cpic_gene_drug_guidelines("BRCA1"))
print(result)
```

**If data is empty:** The data files may not exist at `data/cpic/guidelines.json`. The server falls back to built-in sample data, but if that's also empty, check that the module loaded correctly.

### Symptom: FastMCP import error

**Fix:**
```bash
pip install fastmcp>=2.0.0
```

If `fastmcp` isn't available yet in your environment, you can test the tool functions directly (without the MCP protocol wrapper):
```python
# Direct function call (bypasses MCP protocol)
result = await cpic_gene_drug_guidelines("EGFR")
```

---

## Security Layer Issues

### Symptom: Valid genomic data being rejected

**Debug:**
```python
from src.security.layer import SecurityLayer

security = SecurityLayer.from_env()
result = security.validate("your input here")
print(f"Valid: {result.is_valid}")
print(f"Reason: {result.rejected_reason}")
print(f"Error: {result.error_message}")
```

**Common false positives:**
- Scientific text containing "SELECT" (e.g., "select the appropriate therapy") → False positive on SQL injection
- Clinical notes with patient names → PHI detector triggering

**Fix for false positives:** If you're in a clinical context, enable clinical mode:
```bash
export PHI_CLINICAL_USE=true
```

### Symptom: Rate limiter blocking in tests

**Fix:** Reset the rate limiter between tests:
```python
security.rate_limiter.reset("test_session")
```

---

## Agent Issues

### Symptom: Agent returns classification=None

**Cause:** Agent timed out or errored. Check the `limitations` field:
```python
if classification.classification is None:
    print(f"Agent failed. Limitations: {classification.limitations}")
```

### Symptom: Gene mismatch error

**Cause:** A variant was routed to the wrong agent.

**Debug:**
```python
# Check the routing logic
from src.parsers.vcf_parser import SUPPORTED_GENES
print(f"Supported genes: {SUPPORTED_GENES}")
print(f"Variant gene: {variant.gene}")
```

---

## RAG / Vector Store Issues

### Symptom: "Collection not found" or empty results

**Fix:** Rebuild the vector store:
```bash
python scripts/index_literature.py
```

**Verify:**
```python
import chromadb

client = chromadb.PersistentClient(path="data/literature/vectordb")
collection = client.get_collection("pubmed_abstracts")
print(f"Documents indexed: {collection.count()}")
```

### Symptom: Low relevance scores (all < 0.5)

**Cause:** Embedding model might not be downloaded, or query is too generic.

**Debug:**
```python
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("all-MiniLM-L6-v2")
emb = model.encode("EGFR L858R osimertinib")
print(f"Embedding shape: {emb.shape}")  # Should be (384,)
```

---

## Import / Dependency Issues

### Symptom: "ModuleNotFoundError: No module named 'src'"

**Fix:** Install the project in development mode:
```bash
pip install -e .
```

Or add the project root to PYTHONPATH:
```bash
export PYTHONPATH=$PWD:$PYTHONPATH  # Linux/macOS
$env:PYTHONPATH = "$pwd;$env:PYTHONPATH"  # Windows PowerShell
```

### Symptom: "ModuleNotFoundError: No module named 'google.adk'"

**Fix:**
```bash
pip install google-adk>=2.0.0
```

If ADK 2.0 isn't available in your pip registry yet, check: https://google.github.io/adk-docs/2.0/

### Symptom: pydantic validation errors on model creation

**Cause:** Data doesn't match the model's field constraints.

**Debug:**
```python
from pydantic import ValidationError
from src.models import Variant

try:
    v = Variant(chromosome="chr17", position=-1, ref_allele="A", alt_allele="G")
except ValidationError as e:
    print(e)  # Will show which field failed and why
```

---

## Test Failures

### Running tests

```bash
# All tests
pytest tests/ -v

# Just unit tests (fast, no Ollama needed)
pytest tests/unit/ -v

# Just property tests
pytest tests/properties/ -v -m property

# With coverage
pytest tests/ --cov=src --cov-report=html

# Single test file
pytest tests/unit/test_vcf_parser.py -v
```

### Symptom: Property tests timing out

**Cause:** Hypothesis generating too many examples.

**Fix:** Reduce example count for debugging:
```python
from hypothesis import settings

@settings(max_examples=10)  # Reduce from 100 for debugging
def test_something():
    ...
```

### Symptom: Tests pass locally but fail in CI

**Common causes:**
- Ollama not available in CI → mark integration tests with `@pytest.mark.integration`
- File paths different (Windows vs Linux) → use `Path` objects
- Race conditions in rate limiter tests → reset between tests

---

## GPU / Performance Issues

### Checking GPU status

```bash
# NVIDIA GPU
nvidia-smi

# Check CUDA version
nvcc --version

# Check if PyTorch sees GPU
python -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}')"
python -c "import torch; print(f'GPU: {torch.cuda.get_device_name(0)}')" 
```

### Ollama not using GPU

```bash
# Check Ollama logs
journalctl -u ollama  # Linux systemd

# Force GPU usage
OLLAMA_NUM_GPU=99 ollama serve

# Check model is loaded on GPU
curl http://localhost:11434/api/ps
```

### Memory management

```python
# Clear GPU memory between runs (if using torch directly)
import torch
torch.cuda.empty_cache()

# Monitor memory during inference
import subprocess
result = subprocess.run(['nvidia-smi', '--query-gpu=memory.used', '--format=csv,noheader'],
                      capture_output=True, text=True)
print(f"GPU memory used: {result.stdout.strip()}")
```

---

## Debug Tools and Techniques

### 1. Interactive debugging with the notebook

The best way to debug is with the Jupyter notebook:
```bash
jupyter notebook notebooks/01_pipeline_walkthrough.ipynb
```

### 2. Logging

Add verbose logging to any module:
```python
import logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

logger.debug(f"Parsing variant at position {position}")
```

### 3. Testing MCP tools directly

```python
import asyncio

async def test_tool():
    from mcp_servers.cpic_server import cpic_gene_drug_guidelines
    result = await cpic_gene_drug_guidelines("EGFR")
    print(result)

asyncio.run(test_tool())
```

### 4. Inspecting Ollama requests/responses

```python
import ollama

# Enable verbose mode
response = ollama.generate(
    model='medgemma',
    prompt='Your prompt here',
    options={
        'temperature': 0.1,  # More deterministic
        'num_predict': 500,  # Limit output length
    }
)

# Check timing
print(f"Total duration: {response.get('total_duration', 0) / 1e9:.1f}s")
print(f"Load duration: {response.get('load_duration', 0) / 1e9:.1f}s")
print(f"Eval count: {response.get('eval_count', 0)} tokens")
```

### 5. Audit log inspection

```python
from src.security.audit_logger import AuditLogger

logger = AuditLogger("audit.log")
records = logger.read_log()
for r in records[-5:]:  # Last 5 entries
    print(f"{r.timestamp} | {r.agent_name} | {r.action_type}")
```

---

## Common Error Messages Reference

| Error Message | Cause | Quick Fix |
|--------------|-------|-----------|
| `OllamaUnavailableError: not running at http://localhost:11434` | Ollama service not started | `ollama serve` |
| `OllamaModelNotFoundError: 'medgemma'` | Model not pulled | `ollama pull medgemma` |
| `VCFFormatError: Line 5, field 'POS'` | Non-numeric position in VCF | Fix VCF file at that line |
| `VCFEmptyError` | No data rows in VCF | Add variant records after header |
| `VCFTooLargeError: exceeds 10000` | Too many variants | Split file or raise limit |
| `SecurityValidationError (sql_injection)` | Input matched SQL pattern | Remove SQL-like text |
| `SecurityValidationError (prompt_injection)` | Input matched prompt injection | Remove adversarial text |
| `RateLimitExceededError: Retry after Xs` | Too many requests | Wait or reset limiter |
| `MCPTimeoutError: 'clinvar-server' timed out` | NCBI API slow | Expected — pipeline continues |
| `GeneMismatchError: handles ['BRCA1', 'BRCA2'], received 'EGFR'` | Wrong agent for gene | Check routing logic |
| `ModuleNotFoundError: No module named 'src'` | Package not installed | `pip install -e .` |
| `pydantic.ValidationError` | Data fails model constraints | Check field types/values |
