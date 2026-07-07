#!/bin/bash
set -e

# Start Ollama server in background
ollama serve &
OLLAMA_PID=$!

# Poll Ollama API until ready (max 30 seconds, polling every 2 seconds)
MAX_ATTEMPTS=15
ATTEMPT=0

while [ $ATTEMPT -lt $MAX_ATTEMPTS ]; do
    if curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; then
        echo "Ollama is ready"
        break
    fi
    ATTEMPT=$((ATTEMPT + 1))
    sleep 2
done

if [ $ATTEMPT -eq $MAX_ATTEMPTS ]; then
    echo "ERROR: Ollama failed to start within 30 seconds"
    exit 1
fi

# Run the demo pipeline
set +e
python scripts/demo.py --vcf data/samples/sample_variants.vcf --check-ollama
DEMO_EXIT_CODE=$?
set -e

# Handle demo exit code
if [ $DEMO_EXIT_CODE -eq 0 ]; then
    cat output/report.md
    exit 0
else
    exit $DEMO_EXIT_CODE
fi
