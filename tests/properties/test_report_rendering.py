"""Property-based tests for report rendering.

Tests validate that:
- Property 3: Clinical narrative inclusion in report (Requirement 1.6)
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st
from hypothesis.strategies import composite

from src.pipeline.orchestrator import render_markdown_report
from src.models import (
    ClinicalReport,
    VariantClassification,
    ACMGClassification,
    ConfidenceLevel,
    Variant,
)


# ─── Strategies ──────────────────────────────────────────────────────────────

# Printable characters for narrative content (no control chars to avoid markdown issues)
_printable_text = st.text(
    min_size=1,
    max_size=200,
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "S", "Z")),
).filter(lambda s: len(s.strip()) > 0)

_acmg_values = st.sampled_from(list(ACMGClassification))
_confidence_values = st.sampled_from(list(ConfidenceLevel))
_gene_names = st.sampled_from(["BRCA1", "BRCA2", "EGFR", "TP53"])


@composite
def variant_classification_with_narrative(draw):
    """Generate a VariantClassification with a non-empty clinical_narrative."""
    gene = draw(_gene_names)
    classification = draw(_acmg_values)
    confidence = draw(_confidence_values)
    narrative = draw(_printable_text)

    return VariantClassification(
        gene=gene,
        variant_description=f"{gene} chr17:41245466 A>T",
        chromosome="chr17",
        position=41245466,
        ref_allele="A",
        alt_allele="T",
        classification=classification,
        confidence=confidence,
        evidence_references=["ClinVar: Pathogenic (reviewed)"],
        clinical_narrative=narrative,
    )


@composite
def clinical_report_with_narratives(draw):
    """Generate a ClinicalReport containing classifications with non-empty narratives."""
    classifications = draw(
        st.lists(variant_classification_with_narrative(), min_size=1, max_size=5)
    )

    report = ClinicalReport(
        classifications=classifications,
    )
    return report


# ─── Property Tests ──────────────────────────────────────────────────────────


# Feature: project-completion-fixes, Property 3: Clinical narrative inclusion in report
class TestClinicalNarrativeInclusionInReport:
    """**Validates: Requirements 1.6**

    For any ClinicalReport containing VariantClassification objects with non-empty
    clinical_narrative fields, the rendered markdown_summary SHALL contain each
    clinical narrative text.
    """

    @pytest.mark.property
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(report=clinical_report_with_narratives())
    def test_rendered_markdown_contains_all_clinical_narratives(self, report):
        """Each clinical narrative must appear in the rendered markdown summary."""
        markdown = render_markdown_report(report)

        for classification in report.classifications:
            assert classification.clinical_narrative in markdown, (
                f"Clinical narrative not found in markdown: "
                f"'{classification.clinical_narrative[:50]}...'"
            )
