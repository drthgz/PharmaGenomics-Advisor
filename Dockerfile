# PharmaGenomics Advisor - Reproducible Deployment
# Multi-agent precision medicine pipeline with Ollama LLM inference

FROM python:3.10-slim

# Accept build argument for Ollama model with default
ARG OLLAMA_MODEL=medgemma

# Set working directory
WORKDIR /app

# Install system dependencies required for Ollama and Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Ollama
RUN curl -fsSL https://ollama.com/install.sh | sh

# Copy pyproject.toml first for dependency caching
COPY pyproject.toml .

# Install runtime Python dependencies (exclude dev optional-dependencies)
RUN pip install --no-cache-dir \
    "google-adk>=2.0.0" \
    "fastmcp>=2.0.0" \
    "pydantic>=2.0.0" \
    "chromadb>=0.5.0" \
    "sentence-transformers>=3.0.0" \
    "httpx>=0.27.0" \
    "ollama>=0.4.0"

# Pull the specified Ollama model during build
RUN ollama serve & \
    sleep 5 && \
    ollama pull ${OLLAMA_MODEL} && \
    kill $(cat /tmp/ollama.pid 2>/dev/null) 2>/dev/null || true

# Copy project source and data files
COPY src/ src/
COPY data/ data/
COPY scripts/ scripts/
COPY agents/ agents/
COPY docs/ docs/
COPY mcp_servers/ mcp_servers/
COPY agent.yaml .
COPY readme.md .

# Make entrypoint executable
RUN chmod +x scripts/entrypoint.sh

# Expose Ollama port
EXPOSE 11434

# Set entrypoint
ENTRYPOINT ["scripts/entrypoint.sh"]
