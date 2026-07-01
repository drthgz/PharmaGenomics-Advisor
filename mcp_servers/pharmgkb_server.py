"""PharmGKB MCP Server — Exposes pharmacogenomics clinical annotations.

Serves from locally cached PharmGKB data. No external API required.
PharmGKB catalogs drug-gene associations, clinical annotations,
and dosing guidelines from published studies.

Run standalone: python -m mcp_servers.pharmgkb_server
"""

from __future__ import annotations

import csv
from pathlib import Path

from fastmcp import FastMCP

mcp = FastMCP("pharmgkb-server")

# Load PharmGKB data at module import time
DATA_PATH = Path(__file__).parent.parent / "data" / "pharmgkb" / "annotations.tsv"
PHARMGKB_DATA: list[dict] = []


def _load_pharmgkb_data() -> list[dict]:
    """Load PharmGKB annotations from local TSV cache."""
    global PHARMGKB_DATA
    if DATA_PATH.exists():
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            PHARMGKB_DATA = list(reader)
    else:
        PHARMGKB_DATA = _get_sample_pharmgkb_data()
    return PHARMGKB_DATA


def _get_sample_pharmgkb_data() -> list[dict]:
    """Return sample PharmGKB annotations for demonstration."""
    return [
        {
            "gene": "EGFR",
            "variant": "L858R",
            "drug": "Osimertinib",
            "evidence_level": "1A",
            "phenotype_category": "Efficacy",
            "association": "Response to targeted therapy",
            "description": "EGFR L858R mutation confers sensitivity to EGFR tyrosine kinase inhibitors. Osimertinib is the preferred first-line agent.",
        },
        {
            "gene": "EGFR",
            "variant": "Exon 19 deletion",
            "drug": "Osimertinib",
            "evidence_level": "1A",
            "phenotype_category": "Efficacy",
            "association": "Response to targeted therapy",
            "description": "EGFR exon 19 deletions confer sensitivity to osimertinib with response rates of 70-80%.",
        },
        {
            "gene": "EGFR",
            "variant": "T790M",
            "drug": "Osimertinib",
            "evidence_level": "1A",
            "phenotype_category": "Efficacy",
            "association": "Overcomes resistance",
            "description": "T790M resistance mutation is specifically targeted by third-generation TKI osimertinib.",
        },
        {
            "gene": "EGFR",
            "variant": "L858R",
            "drug": "Gefitinib",
            "evidence_level": "1A",
            "phenotype_category": "Efficacy",
            "association": "Response to targeted therapy",
            "description": "First-generation EGFR TKI with established efficacy for L858R mutations.",
        },
        {
            "gene": "BRCA1",
            "variant": "Pathogenic",
            "drug": "Olaparib",
            "evidence_level": "1A",
            "phenotype_category": "Efficacy",
            "association": "Response to PARP inhibitor",
            "description": "BRCA1 pathogenic variants predict response to PARP inhibitor therapy via synthetic lethality.",
        },
        {
            "gene": "BRCA2",
            "variant": "Pathogenic",
            "drug": "Olaparib",
            "evidence_level": "1A",
            "phenotype_category": "Efficacy",
            "association": "Response to PARP inhibitor",
            "description": "BRCA2 pathogenic variants predict response to PARP inhibitor therapy.",
        },
        {
            "gene": "TP53",
            "variant": "R248W",
            "drug": "Cisplatin",
            "evidence_level": "2A",
            "phenotype_category": "Toxicity/ADR",
            "association": "Resistance to chemotherapy",
            "description": "TP53 gain-of-function mutations like R248W may confer resistance to DNA-damaging chemotherapy.",
        },
    ]


# Load data on import
_load_pharmgkb_data()


@mcp.tool()
async def pharmgkb_annotations(gene: str) -> dict:
    """Get PharmGKB clinical annotations for a gene.

    Returns drug associations, evidence levels, and phenotype categories
    from the PharmGKB knowledge base.

    Args:
        gene: Gene symbol (e.g., "EGFR", "BRCA1") or variant ID

    Returns:
        Dict with matching annotations or "no records found" status.
    """
    if not gene:
        return {
            "status": "error",
            "error": "Missing required parameter: gene",
            "results": [],
        }

    gene_upper = gene.strip().upper()
    annotations = [a for a in PHARMGKB_DATA if a.get("gene", "").upper() == gene_upper]

    if not annotations:
        return {
            "status": "no records found",
            "gene": gene_upper,
            "results": [],
        }

    return {
        "status": "success",
        "gene": gene_upper,
        "annotation_count": len(annotations),
        "results": annotations,
    }


if __name__ == "__main__":
    mcp.run()
