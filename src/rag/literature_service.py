"""Lightweight local literature retrieval service.

Provides deterministic citation bundles for demo/runtime use without requiring
a vector database bootstrap step.
"""

from __future__ import annotations

from src.models import DrugRecommendation, LiteratureCitation, LiteratureResult


class LiteratureService:
    """Generate local literature evidence bundles from seeded citation data."""

    def __init__(self):
        self._catalog = _build_catalog()

    def retrieve(self, recommendations: list[DrugRecommendation]) -> list[LiteratureResult]:
        """Return evidence blocks for each recommendation."""
        results: list[LiteratureResult] = []

        for rec in recommendations:
            key = (rec.gene.upper(), rec.drug_name.lower())
            citations = self._catalog.get(key, _fallback_citations(rec))
            citations = sorted(citations, key=lambda c: (c.relevance_score, c.year), reverse=True)[:5]
            synthesis = _synthesize(rec, citations)
            results.append(
                LiteratureResult(
                    citations=citations,
                    synthesis_paragraph=synthesis,
                    status="success" if citations else "limited literature evidence",
                    query=f"{rec.gene} {rec.variant} {rec.drug_name}",
                )
            )

        return results


def _build_catalog() -> dict[tuple[str, str], list[LiteratureCitation]]:
    return {
        ("EGFR", "osimertinib"): [
            LiteratureCitation(
                title="Osimertinib in Untreated EGFR-Mutated Advanced NSCLC",
                authors="Soria JC et al.",
                journal="New England Journal of Medicine",
                year=2018,
                doi="10.1056/NEJMoa1713137",
                relevance_score=0.95,
                evidence_summary="Phase III evidence showed improved progression-free survival over first-generation TKIs in EGFR-mutated NSCLC.",
            ),
            LiteratureCitation(
                title="Overall Survival with Osimertinib in Untreated EGFR-Mutated NSCLC",
                authors="Ramalingam SS et al.",
                journal="New England Journal of Medicine",
                year=2020,
                doi="10.1056/NEJMoa1913662",
                relevance_score=0.93,
                evidence_summary="Final overall survival analysis reinforced first-line osimertinib benefit in common sensitizing EGFR mutations.",
            ),
        ],
        ("BRCA1", "olaparib"): [
            LiteratureCitation(
                title="PARP Inhibition in Patients with BRCA-Mutated Advanced Breast Cancer",
                authors="Robson M et al.",
                journal="New England Journal of Medicine",
                year=2017,
                doi="10.1056/NEJMoa1706450",
                relevance_score=0.91,
                evidence_summary="Demonstrated improved outcomes with olaparib in germline BRCA-mutated advanced breast cancer.",
            )
        ],
        ("BRCA2", "olaparib"): [
            LiteratureCitation(
                title="Olaparib for Metastatic Castration-Resistant Prostate Cancer",
                authors="de Bono J et al.",
                journal="New England Journal of Medicine",
                year=2020,
                doi="10.1056/NEJMoa1911440",
                relevance_score=0.89,
                evidence_summary="Showed meaningful radiographic progression-free survival benefit in homologous recombination repair-mutated disease including BRCA2.",
            )
        ],
    }


def _fallback_citations(rec: DrugRecommendation) -> list[LiteratureCitation]:
    return [
        LiteratureCitation(
            title=f"Clinical evidence review for {rec.gene}-{rec.drug_name}",
            authors="Curated Demo Dataset",
            journal="Internal Evidence Bundle",
            year=2026,
            doi="",
            relevance_score=0.62,
            evidence_summary="No specific seeded citation was available; this recommendation should be validated with a focused PubMed search before clinical use.",
        )
    ]


def _synthesize(rec: DrugRecommendation, citations: list[LiteratureCitation]) -> str:
    if not citations:
        return (
            "Limited literature evidence was available from the local corpus. "
            "Perform manual PubMed review before acting on this recommendation."
        )

    top_year = max(c.year for c in citations)
    return (
        f"Local literature retrieval found {len(citations)} supporting citation(s) for "
        f"{rec.gene} and {rec.drug_name}. The most recent evidence in this bundle is from {top_year}. "
        "Use this as directional support and confirm with current guideline updates."
    )
