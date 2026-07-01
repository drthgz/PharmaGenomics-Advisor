"""Custom exception hierarchy for the PharmaGenomics Advisor pipeline.

Exceptions are organized by pipeline stage for clear error identification and handling.
"""


class PipelineError(Exception):
    """Base exception for all pipeline errors."""

    pass


# ─── VCF Parsing Errors ──────────────────────────────────────────────────────


class VCFFormatError(PipelineError):
    """VCF file does not conform to VCF 4.x format specification."""

    def __init__(self, field_name: str, line_number: int, message: str = ""):
        self.field_name = field_name
        self.line_number = line_number
        detail = f"Line {line_number}, field '{field_name}': {message}" if message else (
            f"Line {line_number}, field '{field_name}': malformed"
        )
        super().__init__(detail)


class VCFEmptyError(PipelineError):
    """VCF file contains zero parseable variant records."""

    def __init__(self, message: str = "No variant records found in the submitted file"):
        super().__init__(message)


class VCFTooLargeError(PipelineError):
    """VCF file exceeds the maximum supported variant count."""

    def __init__(self, count: int, max_count: int = 10_000):
        self.count = count
        self.max_count = max_count
        super().__init__(
            f"File contains {count} variants, exceeding the maximum supported limit of {max_count}"
        )


# ─── Security Errors ─────────────────────────────────────────────────────────


class SecurityValidationError(PipelineError):
    """Input failed security validation checks."""

    def __init__(self, reason: str, pattern_type: str = "unknown"):
        self.reason = reason
        self.pattern_type = pattern_type
        super().__init__(f"Security validation failed ({pattern_type}): {reason}")


class RateLimitExceededError(PipelineError):
    """Session has exceeded the rate limit."""

    def __init__(self, retry_after_seconds: int):
        self.retry_after_seconds = retry_after_seconds
        super().__init__(
            f"Rate limit exceeded. Retry after {retry_after_seconds} seconds."
        )


# ─── MCP Server Errors ───────────────────────────────────────────────────────


class MCPTimeoutError(PipelineError):
    """MCP server did not respond within the configured timeout."""

    def __init__(self, server_name: str, timeout_seconds: float):
        self.server_name = server_name
        self.timeout_seconds = timeout_seconds
        super().__init__(
            f"MCP server '{server_name}' timed out after {timeout_seconds}s"
        )


class MCPQueryError(PipelineError):
    """MCP server returned an error for a query."""

    def __init__(self, server_name: str, message: str):
        self.server_name = server_name
        super().__init__(f"MCP server '{server_name}' error: {message}")


# ─── Agent Errors ────────────────────────────────────────────────────────────


class AgentTimeoutError(PipelineError):
    """Sub-agent did not respond within the configured timeout."""

    def __init__(self, agent_name: str, timeout_seconds: float):
        self.agent_name = agent_name
        self.timeout_seconds = timeout_seconds
        super().__init__(
            f"Agent '{agent_name}' timed out after {timeout_seconds}s"
        )


class GeneMismatchError(PipelineError):
    """A variant was sent to an agent that doesn't handle its gene."""

    def __init__(self, expected_genes: list[str], received_gene: str):
        self.expected_genes = expected_genes
        self.received_gene = received_gene
        super().__init__(
            f"Gene mismatch: agent handles {expected_genes}, received '{received_gene}'"
        )


# ─── Infrastructure Errors ───────────────────────────────────────────────────


class OllamaUnavailableError(PipelineError):
    """Ollama service is not reachable."""

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        super().__init__(
            f"Ollama is not running at {host}:{port}. "
            f"Start it with: ollama serve"
        )


class OllamaModelNotFoundError(PipelineError):
    """Required model is not available in Ollama."""

    def __init__(self, model_name: str):
        self.model_name = model_name
        super().__init__(
            f"Model '{model_name}' is not available. "
            f"Pull it with: ollama pull {model_name}"
        )
