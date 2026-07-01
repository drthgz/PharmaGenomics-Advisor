"""Ollama connectivity and model availability verification.

Checks at pipeline startup that Ollama is running and the required model is pulled.
Provides clear error messages with fix instructions.
"""

from __future__ import annotations

import os

import httpx

from src.exceptions import OllamaModelNotFoundError, OllamaUnavailableError


def get_ollama_config() -> tuple[str, int, str]:
    """Read Ollama configuration from environment.

    Returns:
        (host, port, model_name)
    """
    host = os.getenv("OLLAMA_HOST", "http://localhost")
    port = int(os.getenv("OLLAMA_PORT", "11434"))
    model = os.getenv("OLLAMA_MODEL", "medgemma")
    return host, port, model


def check_ollama_ready(host: str | None = None, port: int | None = None, model: str | None = None) -> None:
    """Verify Ollama is running and the required model is available.

    Call this at pipeline startup. Raises clear errors if something is wrong.

    Args:
        host: Ollama host URL (default from env or http://localhost)
        port: Ollama port (default from env or 11434)
        model: Required model name (default from env or medgemma)

    Raises:
        OllamaUnavailableError: Ollama is not running at the specified address.
        OllamaModelNotFoundError: Required model is not pulled.
    """
    if host is None or port is None or model is None:
        env_host, env_port, env_model = get_ollama_config()
        host = host or env_host
        port = port or env_port
        model = model or env_model

    base_url = f"{host}:{port}"

    # Check connectivity (10-second timeout as per requirements)
    try:
        response = httpx.get(f"{base_url}/api/tags", timeout=10.0)
        response.raise_for_status()
    except (httpx.ConnectError, httpx.TimeoutException):
        raise OllamaUnavailableError(host=host, port=port)
    except httpx.HTTPStatusError:
        raise OllamaUnavailableError(host=host, port=port)

    # Check model availability
    data = response.json()
    available_models = [m.get("name", "") for m in data.get("models", [])]
    # Match model name (with or without tag)
    model_found = any(
        model in m or m.startswith(f"{model}:") for m in available_models
    )

    if not model_found:
        raise OllamaModelNotFoundError(model_name=model)

    print(f"✓ Ollama ready at {base_url} with model '{model}'")
