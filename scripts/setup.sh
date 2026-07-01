#!/bin/bash
# PharmaGenomics Advisor — One-Command Setup
# Usage: bash scripts/setup.sh
set -e

echo "╔══════════════════════════════════════════════════╗"
echo "║   PharmaGenomics Advisor — Setup Script          ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# 1. Check Python
echo "→ Checking Python..."
if ! command -v python3 &> /dev/null; then
    echo "✗ Python 3.10+ is required. Install from https://python.org"
    exit 1
fi
PYTHON_VERSION=$(python3 --version | awk '{print $2}')
echo "  ✓ Found Python $PYTHON_VERSION"

# 2. Install Ollama
echo ""
echo "→ Checking Ollama..."
if ! command -v ollama &> /dev/null; then
    echo "  Installing Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh
else
    OLLAMA_VERSION=$(ollama --version 2>/dev/null || echo "unknown")
    echo "  ✓ Ollama already installed ($OLLAMA_VERSION)"
fi

# 3. Start Ollama (if not running)
echo ""
echo "→ Starting Ollama service..."
if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    ollama serve &
    sleep 3
    echo "  ✓ Ollama started"
else
    echo "  ✓ Ollama already running"
fi

# 4. Pull model
echo ""
echo "→ Pulling MedGemma model (this may take a few minutes)..."
ollama pull medgemma
echo "  ✓ Model ready"

# 5. Create Python virtual environment
echo ""
echo "→ Setting up Python environment..."
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip -q
pip install -e ".[dev]" -q
echo "  ✓ Dependencies installed"

# 6. Download data
echo ""
echo "→ Setting up knowledge base data..."
mkdir -p data/cpic data/pharmgkb data/literature/vectordb data/samples output
# Data will be populated by the MCP servers' built-in sample data
echo "  ✓ Data directories ready"

# 7. Verify
echo ""
echo "→ Running verification..."
python3 -c "from src.models import Variant; print('  ✓ Models import OK')"
python3 -c "from src.parsers import VCFParser; print('  ✓ Parser import OK')"
python3 -c "from src.security import SecurityLayer; print('  ✓ Security import OK')"

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║   ✓ Setup Complete!                              ║"
echo "║                                                  ║"
echo "║   Activate env:  source .venv/bin/activate       ║"
echo "║   Run tests:     pytest tests/ -v                ║"
echo "║   Run demo:      python scripts/demo.py          ║"
echo "╚══════════════════════════════════════════════════╝"
