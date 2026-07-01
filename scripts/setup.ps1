# PharmaGenomics Advisor — Windows Setup Script
# Usage: powershell -ExecutionPolicy Bypass -File scripts/setup.ps1

Write-Host "╔══════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║   PharmaGenomics Advisor — Setup Script          ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# 1. Check Python
Write-Host "→ Checking Python..." -ForegroundColor Yellow
try {
    $pythonVersion = python --version 2>&1
    Write-Host "  ✓ Found $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "✗ Python 3.10+ is required. Install from https://python.org" -ForegroundColor Red
    exit 1
}

# 2. Check Ollama
Write-Host ""
Write-Host "→ Checking Ollama..." -ForegroundColor Yellow
$ollamaPath = Get-Command ollama -ErrorAction SilentlyContinue
if (-not $ollamaPath) {
    Write-Host "  Ollama not found. Download from https://ollama.com/download" -ForegroundColor Red
    Write-Host "  After installing, re-run this script." -ForegroundColor Red
    exit 1
} else {
    Write-Host "  ✓ Ollama found" -ForegroundColor Green
}

# 3. Start Ollama
Write-Host ""
Write-Host "→ Checking Ollama service..." -ForegroundColor Yellow
try {
    $response = Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -TimeoutSec 5
    Write-Host "  ✓ Ollama already running" -ForegroundColor Green
} catch {
    Write-Host "  Starting Ollama..." -ForegroundColor Yellow
    Start-Process ollama -ArgumentList "serve" -NoNewWindow
    Start-Sleep -Seconds 3
    Write-Host "  ✓ Ollama started" -ForegroundColor Green
}

# 4. Pull model
Write-Host ""
Write-Host "→ Pulling MedGemma model..." -ForegroundColor Yellow
ollama pull medgemma
Write-Host "  ✓ Model ready" -ForegroundColor Green

# 5. Python dependencies (global interpreter)
Write-Host ""
Write-Host "→ Setting up Python environment..." -ForegroundColor Yellow
python -m pip install --upgrade pip -q
python -m pip install -e ".[dev]" -q
Write-Host "  ✓ Dependencies installed" -ForegroundColor Green

# 6. Create directories
Write-Host ""
Write-Host "→ Setting up data directories..." -ForegroundColor Yellow
New-Item -ItemType Directory -Force -Path data/cpic, data/pharmgkb, data/literature/vectordb, data/samples, output | Out-Null
Write-Host "  ✓ Data directories ready" -ForegroundColor Green

# 7. Verify
Write-Host ""
Write-Host "→ Verifying installation..." -ForegroundColor Yellow
python -c "from src.models import Variant; print('  ✓ Models import OK')"
python -c "from src.parsers import VCFParser; print('  ✓ Parser import OK')"

Write-Host ""
Write-Host "╔══════════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║   ✓ Setup Complete!                              ║" -ForegroundColor Green
Write-Host "║                                                  ║" -ForegroundColor Green
Write-Host "║   Python:        python                           ║" -ForegroundColor Green
Write-Host "║   Run tests:     python -m pytest tests/ -v      ║" -ForegroundColor Green
Write-Host "║   Run demo:      python scripts/demo.py          ║" -ForegroundColor Green
Write-Host "╚══════════════════════════════════════════════════╝" -ForegroundColor Green
