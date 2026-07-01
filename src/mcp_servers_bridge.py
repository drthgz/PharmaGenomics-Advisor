"""Async bridge helpers for local knowledge lookups.

This module intentionally avoids importing FastMCP server wrappers so the
pipeline can run in lightweight environments where FastMCP is not installed.
"""

from __future__ import annotations

import os
import httpx

from src.models import Variant

_EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
_TIMEOUT_SECONDS = 15.0


async def lookup_clinvar(variant: Variant) -> dict:
    """Lookup ClinVar evidence using NCBI E-utilities."""
    if os.getenv("ENABLE_CLINVAR_ONLINE", "false").lower() != "true":
        return {"status": "disabled", "error": "ClinVar online lookup disabled", "results": []}

    if not variant.gene:
        return {"status": "error", "error": "Missing gene", "results": []}

    chrom = variant.chromosome.replace("chr", "").replace("Chr", "")
    search_term = f"{variant.gene}[gene] AND {chrom}[chr]"

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            search_resp = await client.get(
                f"{_EUTILS_BASE}/esearch.fcgi",
                params={"db": "clinvar", "term": search_term, "retmode": "json", "retmax": 3},
            )
            search_resp.raise_for_status()
            ids = search_resp.json().get("esearchresult", {}).get("idlist", [])

            if not ids:
                return {
                    "status": "no records found",
                    "gene": variant.gene,
                    "position": variant.position,
                    "results": [],
                }

            summary_resp = await client.get(
                f"{_EUTILS_BASE}/esummary.fcgi",
                params={"db": "clinvar", "id": ",".join(ids), "retmode": "json"},
            )
            summary_resp.raise_for_status()
            summary_data = summary_resp.json().get("result", {})

            results: list[dict] = []
            for uid in ids:
                entry = summary_data.get(uid)
                if not entry:
                    continue
                clin_sig = entry.get("clinical_significance", {})
                results.append(
                    {
                        "uid": uid,
                        "title": entry.get("title", ""),
                        "clinical_significance": clin_sig.get("description", "unknown"),
                        "review_status": clin_sig.get("review_status", "unknown"),
                    }
                )

            return {
                "status": "success",
                "gene": variant.gene,
                "position": variant.position,
                "results": results,
            }
    except Exception as exc:
        return {"status": "error", "error": str(exc), "results": []}


async def lookup_cpic_guidelines(gene: str) -> dict:
    """Lookup CPIC recommendations from local seeded data."""
    gene_upper = gene.strip().upper()
    data = [
        {
            "gene": "BRCA1",
            "drug": "Olaparib",
            "recommendation": "recommended",
            "cpic_level": "A",
            "url": "https://cpicpgx.org/guidelines/",
            "contraindications": [],
        },
        {
            "gene": "BRCA2",
            "drug": "Olaparib",
            "recommendation": "recommended",
            "cpic_level": "A",
            "url": "https://cpicpgx.org/guidelines/",
            "contraindications": [],
        },
        {
            "gene": "EGFR",
            "drug": "Osimertinib",
            "recommendation": "recommended",
            "cpic_level": "A",
            "url": "https://cpicpgx.org/guidelines/",
            "contraindications": ["T790M resistance mutation without osimertinib sensitivity"],
        },
        {
            "gene": "EGFR",
            "drug": "Gefitinib",
            "recommendation": "alternative therapy",
            "cpic_level": "A",
            "url": "https://cpicpgx.org/guidelines/",
            "contraindications": ["T790M resistance mutation"],
        },
    ]
    results = [item for item in data if item["gene"] == gene_upper]
    if not results:
        return {"status": "no records found", "gene": gene_upper, "results": []}
    return {
        "status": "success",
        "gene": gene_upper,
        "guideline_count": len(results),
        "results": results,
    }


async def lookup_pharmgkb_annotations(gene: str) -> dict:
    """Lookup PharmGKB annotations from local seeded data."""
    gene_upper = gene.strip().upper()
    data = [
        {
            "gene": "EGFR",
            "variant": "L858R",
            "drug": "Osimertinib",
            "evidence_level": "1A",
        },
        {
            "gene": "EGFR",
            "variant": "Exon 19 deletion",
            "drug": "Osimertinib",
            "evidence_level": "1A",
        },
        {
            "gene": "TP53",
            "variant": "R248W",
            "drug": "Cisplatin",
            "evidence_level": "2A",
        },
    ]
    results = [item for item in data if item["gene"] == gene_upper]
    if not results:
        return {"status": "no records found", "gene": gene_upper, "results": []}
    return {
        "status": "success",
        "gene": gene_upper,
        "annotation_count": len(results),
        "results": results,
    }
