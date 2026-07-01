"""ClinVar MCP Server — Exposes variant clinical significance via NCBI E-utilities.

This server provides a tool endpoint for querying ClinVar, the NIH public database
of variant-disease relationships. Agents call this to get existing pathogenicity
classifications for known variants.

Run standalone: python -m mcp_servers.clinvar_server
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import httpx
from fastmcp import FastMCP

mcp = FastMCP("clinvar-server")

# NCBI E-utilities base URL
EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
TIMEOUT_SECONDS = 30.0


@mcp.tool()
async def clinvar_variant_lookup(
    gene: str,
    chromosome: str,
    position: int,
    ref: str,
    alt: str,
) -> dict:
    """Look up a variant's clinical significance in the ClinVar database.

    Queries NCBI E-utilities REST API to find existing pathogenicity classifications
    for a specific genomic variant.

    Args:
        gene: Gene symbol (e.g., "BRCA1")
        chromosome: Chromosome identifier (e.g., "chr17" or "17")
        position: Genomic position (1-based)
        ref: Reference allele (e.g., "A")
        alt: Alternate allele (e.g., "G")

    Returns:
        Dict containing clinical_significance, review_status, submission_count,
        or error information if the lookup failed.
    """
    # Validate required fields
    missing = []
    if not gene:
        missing.append("gene")
    if not chromosome:
        missing.append("chromosome")
    if not position:
        missing.append("position")
    if not ref:
        missing.append("ref")
    if not alt:
        missing.append("alt")

    if missing:
        return {
            "status": "error",
            "error": f"Missing required parameters: {', '.join(missing)}",
            "results": [],
        }

    # Normalize chromosome (remove 'chr' prefix for NCBI)
    chrom = chromosome.replace("chr", "").replace("Chr", "")

    # Build search query
    search_term = f"{gene}[gene] AND {chrom}[chr]"

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            # Step 1: Search ClinVar for matching variants
            search_resp = await client.get(
                f"{EUTILS_BASE}/esearch.fcgi",
                params={
                    "db": "clinvar",
                    "term": search_term,
                    "retmode": "json",
                    "retmax": 5,
                },
            )
            search_resp.raise_for_status()
            search_data = search_resp.json()

            id_list = search_data.get("esearchresult", {}).get("idlist", [])

            if not id_list:
                return {
                    "status": "no records found",
                    "gene": gene,
                    "chromosome": chromosome,
                    "position": position,
                    "results": [],
                }

            # Step 2: Fetch variant summaries
            summary_resp = await client.get(
                f"{EUTILS_BASE}/esummary.fcgi",
                params={
                    "db": "clinvar",
                    "id": ",".join(id_list[:5]),
                    "retmode": "json",
                },
            )
            summary_resp.raise_for_status()
            summary_data = summary_resp.json()

            # Parse results
            results = []
            doc_sums = summary_data.get("result", {})
            for uid in id_list[:5]:
                if uid in doc_sums:
                    entry = doc_sums[uid]
                    results.append({
                        "uid": uid,
                        "title": entry.get("title", ""),
                        "clinical_significance": entry.get(
                            "clinical_significance", {}).get("description", "unknown"
                        ),
                        "review_status": entry.get("clinical_significance", {}).get(
                            "review_status", "unknown"
                        ),
                        "gene_sort": entry.get("gene_sort", ""),
                    })

            return {
                "status": "success",
                "gene": gene,
                "chromosome": chromosome,
                "position": position,
                "submission_count": len(results),
                "results": results,
            }

    except httpx.TimeoutException:
        return {
            "status": "error",
            "error": f"NCBI E-utilities did not respond within {TIMEOUT_SECONDS}s",
            "results": [],
        }
    except httpx.HTTPStatusError as e:
        return {
            "status": "error",
            "error": f"NCBI API returned HTTP {e.response.status_code}",
            "results": [],
        }
    except Exception as e:
        return {
            "status": "error",
            "error": f"Unexpected error: {str(e)}",
            "results": [],
        }


if __name__ == "__main__":
    mcp.run()
