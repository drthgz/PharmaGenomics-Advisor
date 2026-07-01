"""Core data models for the PharmaGenomics Advisor pipeline.

All models use Pydantic v2 for runtime validation, JSON schema generation,
and round-trip serialization guarantees.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ─── Enums ───────────────────────────────────────────────────────────────────


class ACMGClassification(str, Enum):
    """ACMG/AMP 5-tier variant pathogenicity classification."""

    PATHOGENIC = "Pathogenic"
    LIKELY_PATHOGENIC = "Likely Pathogenic"
    VUS = "VUS"
    LIKELY_BENIGN = "Likely Benign"
    BENIGN = "Benign"


class ConfidenceLevel(str, Enum):
    """Confidence level for agent classifications."""

    HIGH = "High"
    MODERATE = "Moderate"
    LOW = "Low"


class TherapeuticRelevance(str, Enum):
    """EGFR-specific therapeutic relevance annotation."""

    TKI_SENSITIVE = "TKI-sensitive"
    TKI_RESISTANT = "TKI-resistant"
    UNKNOWN = "unknown therapeutic relevance"


class FunctionalStatus(str, Enum):
    """TP53-specific functional status annotation."""

    GAIN_OF_FUNCTION = "gain-of-function"
    LOSS_OF_FUNCTION = "loss-of-function"
    UNDETERMINED = "undetermined"


class RouteStatus(str, Enum):
    """Whether a variant was routed to a specialized agent."""

    ROUTED = "routed"
    UNROUTED = "unrouted"


class RecommendationAction(str, Enum):
    """Drug recommendation action type."""

    AVOID = "avoid"
    DOSE_ADJUSTMENT = "dose adjustment"
    STANDARD_DOSING = "standard dosing"
    ALTERNATIVE_THERAPY = "alternative therapy"
    RECOMMENDED = "recommended"


class VariantType(str, Enum):
    """Type of genetic variant."""

    MISSENSE = "missense"
    NONSENSE = "nonsense"
    FRAMESHIFT = "frameshift"
    SILENT = "silent"
    SPLICE = "splice"
    DELETION = "deletion"
    INSERTION = "insertion"
    UNKNOWN = "unknown"


# ─── Core Data Models ────────────────────────────────────────────────────────


class Variant(BaseModel):
    """A parsed VCF variant record."""

    chromosome: str = Field(..., description="e.g., chr17")
    position: int = Field(..., gt=0, description="1-based genomic position")
    id: str = Field(default=".", description="Variant identifier or '.'")
    ref_allele: str = Field(..., min_length=1, description="Reference allele")
    alt_allele: str = Field(..., min_length=1, description="Alternate allele")
    quality: float = Field(default=0.0, ge=0.0, description="Phred-scaled quality score")
    filter_status: str = Field(default=".", description="Filter status (PASS, ., or filter name)")
    info: dict = Field(default_factory=dict, description="INFO field key-value pairs")
    gene: Optional[str] = Field(default=None, description="Gene symbol from annotation")
    variant_type: VariantType = Field(default=VariantType.UNKNOWN)
    hgvs: Optional[str] = Field(default=None, description="HGVS nomenclature")
    route_status: RouteStatus = Field(default=RouteStatus.UNROUTED)


class ParseResult(BaseModel):
    """Result of VCF file parsing."""

    variants: list[Variant]
    total_count: int
    routed_count: int
    unrouted_count: int
    parse_duration_ms: float = Field(default=0.0)


class VariantClassification(BaseModel):
    """ACMG classification result from a gene-specific agent."""

    gene: str
    variant_description: str = Field(..., description="Human-readable variant description")
    chromosome: str
    position: int
    ref_allele: str
    alt_allele: str
    classification: Optional[ACMGClassification] = Field(
        default=None, description="None if agent was unavailable"
    )
    confidence: Optional[ConfidenceLevel] = None
    evidence_references: list[str] = Field(default_factory=list)
    therapeutic_relevance: Optional[TherapeuticRelevance] = Field(
        default=None, description="EGFR-specific: TKI sensitivity"
    )
    functional_status: Optional[FunctionalStatus] = Field(
        default=None, description="TP53-specific: gain/loss of function"
    )
    data_sources_queried: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class DrugRecommendation(BaseModel):
    """A single pharmacogenomics drug recommendation."""

    drug_name: str
    gene: str
    variant: str
    action: RecommendationAction
    evidence_level: str = Field(..., description="CPIC level: A, B, C, D")
    guideline_source_url: str = Field(default="")
    contraindications: list[str] = Field(default_factory=list)


class LiteratureCitation(BaseModel):
    """A retrieved biomedical literature citation."""

    title: str
    authors: str
    journal: str
    year: int
    doi: str = Field(default="")
    relevance_score: float = Field(..., ge=0.0, le=1.0)
    evidence_summary: str = Field(..., max_length=500)


class LiteratureResult(BaseModel):
    """Complete literature evidence result for a variant-drug combination."""

    citations: list[LiteratureCitation] = Field(default_factory=list)
    synthesis_paragraph: str = Field(default="", max_length=1500)
    status: str = Field(default="success")
    query: str = Field(default="")


class ProvenanceMetadata(BaseModel):
    """Provenance tracking for each finding in the clinical report."""

    source_agent: str
    data_sources_queried: list[str] = Field(default_factory=list)
    confidence: Optional[ConfidenceLevel] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ClinicalReport(BaseModel):
    """Unified clinical report — the final pipeline output."""

    report_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    pipeline_version: str = Field(default="0.1.0")
    total_execution_time_seconds: float = Field(default=0.0)

    # Content sections
    variant_summary: list[Variant] = Field(default_factory=list)
    classifications: list[VariantClassification] = Field(default_factory=list)
    drug_recommendations: list[DrugRecommendation] = Field(default_factory=list)
    literature_evidence: list[LiteratureResult] = Field(default_factory=list)

    # Metadata
    provenance: list[ProvenanceMetadata] = Field(default_factory=list)
    warnings: list[dict] = Field(default_factory=list)

    # Human-readable summary
    markdown_summary: str = Field(default="")


class AuditRecord(BaseModel):
    """Immutable audit log entry for agent invocations."""

    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    agent_name: str
    action_type: str
    input_hash: str = Field(..., pattern=r"^[a-f0-9]{64}$")
    output_hash: str = Field(..., pattern=r"^[a-f0-9]{64}$")


# ─── Security Models ─────────────────────────────────────────────────────────


class ValidationResult(BaseModel):
    """Result of security validation checks."""

    is_valid: bool
    error_message: Optional[str] = None
    rejected_reason: Optional[str] = None


class SecurityConfig(BaseModel):
    """Security layer configuration (loaded from environment)."""

    phi_detection_enabled: bool = True
    clinical_use_mode: bool = False
    rate_limit_requests: int = 100
    rate_limit_window_seconds: int = 60
    max_input_chars: int = 10_000
    data_persistence_enabled: bool = False
    audit_log_path: str = "audit.log"
    ollama_host: str = "http://localhost"
    ollama_port: int = 11434
    ollama_model: str = "medgemma"
