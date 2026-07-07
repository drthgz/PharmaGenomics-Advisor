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
        return {
            "status": "disabled",
            "error": "ClinVar online lookup disabled",
            "results": [],
            "source": "bridge_stub",
        }

    # Prefer the local MCP tool implementation when available so runtime behavior
    # aligns with the documented MCP architecture without requiring a separate process.
    try:
        from mcp_servers.clinvar_server import clinvar_variant_lookup

        result = await clinvar_variant_lookup(
            gene=variant.gene or "",
            chromosome=variant.chromosome,
            position=variant.position,
            ref=variant.ref_allele,
            alt=variant.alt_allele,
        )
        if isinstance(result, dict):
            result.setdefault("source", "mcp_tool")
            return result
    except Exception:
        # Fall back to direct lightweight implementation when MCP dependencies
        # are unavailable in the runtime image.
        pass

    if not variant.gene:
        return {"status": "error", "error": "Missing gene", "results": [], "source": "bridge_stub"}

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
                    "source": "bridge_http",
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
                "source": "bridge_http",
            }
    except Exception as exc:
        return {"status": "error", "error": str(exc), "results": [], "source": "bridge_http"}


async def lookup_cpic_guidelines(gene: str) -> dict:
    """Lookup CPIC recommendations from local seeded data."""
    try:
        from mcp_servers.cpic_server import cpic_gene_drug_guidelines

        result = await cpic_gene_drug_guidelines(gene=gene)
        if isinstance(result, dict):
            result.setdefault("source", "mcp_tool")
            return result
    except Exception:
        pass

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
        return {
            "status": "no records found",
            "gene": gene_upper,
            "results": [],
            "source": "bridge_seed",
        }
    return {
        "status": "success",
        "gene": gene_upper,
        "guideline_count": len(results),
        "results": results,
        "source": "bridge_seed",
    }


async def lookup_pharmgkb_annotations(gene: str) -> dict:
    """Lookup PharmGKB annotations from local seeded data."""
    try:
        from mcp_servers.pharmgkb_server import pharmgkb_annotations

        result = await pharmgkb_annotations(gene=gene)
        if isinstance(result, dict):
            result.setdefault("source", "mcp_tool")
            return result
    except Exception:
        pass

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
        return {
            "status": "no records found",
            "gene": gene_upper,
            "results": [],
            "source": "bridge_seed",
        }
    return {
        "status": "success",
        "gene": gene_upper,
        "annotation_count": len(results),
        "results": results,
        "source": "bridge_seed",
    }
