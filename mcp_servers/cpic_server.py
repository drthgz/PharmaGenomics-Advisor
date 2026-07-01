"""CPIC MCP Server — Exposes pharmacogenomics gene-drug guidelines.

Serves from locally cached CPIC JSON data files. No external API required.
CPIC (Clinical Pharmacogenetics Implementation Consortium) provides evidence-based
guidelines for translating genetic test results into prescribing decisions.

Run standalone: python -m mcp_servers.cpic_server
"""

from __future__ import annotations

import json
from pathlib import Path

from fastmcp import FastMCP

mcp = FastMCP("cpic-server")

# Load CPIC data at module import time
DATA_PATH = Path(__file__).parent.parent / "data" / "cpic" / "guidelines.json"
CPIC_DATA: list[dict] = []


def _load_cpic_data() -> list[dict]:
    """Load CPIC guidelines from local JSON cache."""
    global CPIC_DATA
    if DATA_PATH.exists():
        CPIC_DATA = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    else:
        # Provide sample data for demo purposes
        CPIC_DATA = _get_sample_cpic_data()
    return CPIC_DATA


def _get_sample_cpic_data() -> list[dict]:
    """Return sample CPIC guidelines for demonstration."""
    return [
        {
            "gene": "BRCA1",
            "drug": "Olaparib",
            "recommendation": "recommended",
            "cpic_level": "A",
            "phenotype": "BRCA1/2 pathogenic variant carrier",
            "dosing": "Standard dose",
            "url": "https://cpicpgx.org/guidelines/",
            "contraindications": [],
        },
        {
            "gene": "BRCA1",
            "drug": "Rucaparib",
            "recommendation": "alternative therapy",
            "cpic_level": "A",
            "phenotype": "BRCA1/2 pathogenic variant carrier",
            "dosing": "Standard dose",
            "url": "https://cpicpgx.org/guidelines/",
            "contraindications": [],
        },
        {
            "gene": "BRCA2",
            "drug": "Olaparib",
            "recommendation": "recommended",
            "cpic_level": "A",
            "phenotype": "BRCA1/2 pathogenic variant carrier",
            "dosing": "Standard dose",
            "url": "https://cpicpgx.org/guidelines/",
            "contraindications": [],
        },
        {
            "gene": "EGFR",
            "drug": "Osimertinib",
            "recommendation": "recommended",
            "cpic_level": "A",
            "phenotype": "EGFR TKI-sensitive mutation",
            "dosing": "80mg once daily",
            "url": "https://cpicpgx.org/guidelines/",
            "contraindications": ["T790M resistance mutation without osimertinib sensitivity"],
        },
        {
            "gene": "EGFR",
            "drug": "Gefitinib",
            "recommendation": "alternative therapy",
            "cpic_level": "A",
            "phenotype": "EGFR TKI-sensitive mutation",
            "dosing": "250mg once daily",
            "url": "https://cpicpgx.org/guidelines/",
            "contraindications": ["T790M resistance mutation"],
        },
        {
            "gene": "EGFR",
            "drug": "Erlotinib",
            "recommendation": "alternative therapy",
            "cpic_level": "A",
            "phenotype": "EGFR TKI-sensitive mutation",
            "dosing": "150mg once daily",
            "url": "https://cpicpgx.org/guidelines/",
            "contraindications": ["T790M resistance mutation"],
        },
        {
            "gene": "CYP2C19",
            "drug": "Clopidogrel",
            "recommendation": "avoid",
            "cpic_level": "A",
            "phenotype": "Poor metabolizer",
            "dosing": "Use alternative antiplatelet (prasugrel, ticagrelor)",
            "url": "https://cpicpgx.org/guidelines/cpic-guideline-for-clopidogrel/",
            "contraindications": ["Poor CYP2C19 metabolism"],
        },
        {
            "gene": "CYP2D6",
            "drug": "Codeine",
            "recommendation": "avoid",
            "cpic_level": "A",
            "phenotype": "Ultra-rapid metabolizer",
            "dosing": "Use alternative analgesic (non-tramadol opioid or non-opioid)",
            "url": "https://cpicpgx.org/guidelines/cpic-guideline-for-codeine/",
            "contraindications": ["Ultra-rapid CYP2D6 metabolism — risk of toxicity"],
        },
    ]


# Load data on import
_load_cpic_data()


@mcp.tool()
async def cpic_gene_drug_guidelines(gene: str) -> dict:
    """Get CPIC pharmacogenomic guidelines for a specific gene.

    Returns all gene-drug interaction guidelines including recommendation strength,
    phenotype-based dosing, and evidence level.

    Args:
        gene: Gene symbol (e.g., "BRCA1", "CYP2C19", "EGFR")

    Returns:
        Dict with matching guidelines or "no records found" status.
    """
    if not gene:
        return {
            "status": "error",
            "error": "Missing required parameter: gene",
            "results": [],
        }

    gene_upper = gene.strip().upper()
    guidelines = [g for g in CPIC_DATA if g.get("gene", "").upper() == gene_upper]

    if not guidelines:
        return {
            "status": "no records found",
            "gene": gene_upper,
            "results": [],
        }

    return {
        "status": "success",
        "gene": gene_upper,
        "guideline_count": len(guidelines),
        "results": guidelines,
    }


if __name__ == "__main__":
    mcp.run()
