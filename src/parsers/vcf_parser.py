"""VCF (Variant Call Format) file parser.

Parses VCF 4.x files into structured Variant objects with gene annotation
extraction and routing logic. Pure deterministic code — no LLM involved.

See docs/01-biomedical-foundations.md for VCF format explanation.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Union

from src.exceptions import VCFEmptyError, VCFFormatError, VCFTooLargeError
from src.models import ParseResult, RouteStatus, Variant, VariantType

# Genes supported by our specialist agents
SUPPORTED_GENES: set[str] = {"BRCA1", "BRCA2", "EGFR", "TP53"}

# Maximum variant count before rejection
MAX_VARIANTS: int = 10_000

# VCF mandatory columns (0-indexed)
VCF_COLUMNS = ["CHROM", "POS", "ID", "REF", "ALT", "QUAL", "FILTER", "INFO"]


class VCFParser:
    """Parse VCF 4.x files into structured Variant objects.

    Usage:
        parser = VCFParser()
        result = parser.parse("path/to/variants.vcf")
        for variant in result.variants:
            print(variant.gene, variant.route_status)
    """

    def parse(self, file_path: Union[str, Path]) -> ParseResult:
        """Parse a VCF file and return structured results.

        Args:
            file_path: Path to a VCF 4.x format file.

        Returns:
            ParseResult with all parsed variants and counts.

        Raises:
            VCFFormatError: File has malformed records (includes field name + line number).
            VCFEmptyError: File contains no variant records.
            VCFTooLargeError: File exceeds MAX_VARIANTS limit.
            FileNotFoundError: File does not exist.
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"VCF file not found: {file_path}")

        start_time = time.perf_counter()
        variants: list[Variant] = []

        with open(file_path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, start=1):
                line = line.strip()

                # Skip empty lines and header/meta lines
                if not line or line.startswith("#"):
                    continue

                variant = parse_vcf_line(line, line_num)
                variants.append(variant)

                if len(variants) > MAX_VARIANTS:
                    raise VCFTooLargeError(count=len(variants), max_count=MAX_VARIANTS)

        if not variants:
            raise VCFEmptyError()

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        routed = sum(1 for v in variants if v.route_status == RouteStatus.ROUTED)

        return ParseResult(
            variants=variants,
            total_count=len(variants),
            routed_count=routed,
            unrouted_count=len(variants) - routed,
            parse_duration_ms=elapsed_ms,
        )


def parse_vcf_line(line: str, line_num: int) -> Variant:
    """Parse a single VCF record line into a Variant object.

    Args:
        line: Tab-separated VCF record string.
        line_num: Line number in the file (for error reporting).

    Returns:
        A Variant object with routing status set.

    Raises:
        VCFFormatError: If the line is malformed.
    """
    fields = line.split("\t")

    if len(fields) < 8:
        raise VCFFormatError(
            field_name="COLUMNS",
            line_number=line_num,
            message=f"Expected at least 8 tab-separated fields, got {len(fields)}",
        )

    # Parse CHROM
    chrom = fields[0].strip()
    if not chrom:
        raise VCFFormatError(field_name="CHROM", line_number=line_num, message="Empty chromosome")

    # Parse POS (must be positive integer)
    try:
        position = int(fields[1])
        if position <= 0:
            raise ValueError("Position must be positive")
    except ValueError as e:
        raise VCFFormatError(
            field_name="POS", line_number=line_num, message=f"Invalid position: {fields[1]}"
        ) from e

    # Parse ID
    variant_id = fields[2].strip() if fields[2].strip() else "."

    # Parse REF allele
    ref = fields[3].strip().upper()
    if not ref or not all(c in "ATCGN." for c in ref):
        raise VCFFormatError(
            field_name="REF", line_number=line_num, message=f"Invalid reference allele: {fields[3]}"
        )

    # Parse ALT allele
    alt = fields[4].strip().upper()
    if not alt or not all(c in "ATCGN.,*" for c in alt):
        raise VCFFormatError(
            field_name="ALT", line_number=line_num, message=f"Invalid alternate allele: {fields[4]}"
        )

    # Parse QUAL
    qual_str = fields[5].strip()
    if qual_str == "." or qual_str == "":
        quality = 0.0
    else:
        try:
            quality = float(qual_str)
        except ValueError:
            raise VCFFormatError(
                field_name="QUAL", line_number=line_num, message=f"Invalid quality: {qual_str}"
            )

    # Parse FILTER
    filter_status = fields[6].strip() if fields[6].strip() else "."

    # Parse INFO field
    info = _parse_info_field(fields[7]) if len(fields) > 7 else {}

    # Extract gene annotation
    gene = _extract_gene(info)

    # Determine variant type
    variant_type = _determine_variant_type(info)

    # Extract HGVS if present
    hgvs = info.get("HGVS", info.get("hgvs", None))

    # Determine routing
    route_status = RouteStatus.ROUTED if gene in SUPPORTED_GENES else RouteStatus.UNROUTED

    return Variant(
        chromosome=chrom,
        position=position,
        id=variant_id,
        ref_allele=ref,
        alt_allele=alt,
        quality=quality,
        filter_status=filter_status,
        info=info,
        gene=gene,
        variant_type=variant_type,
        hgvs=hgvs,
        route_status=route_status,
    )


def format_variant_to_vcf(variant: Variant) -> str:
    """Convert a Variant object back to a VCF record string.

    Supports round-trip testing: parse → format → parse should yield equivalent objects.

    Args:
        variant: A Variant object.

    Returns:
        Tab-separated VCF record string.
    """
    info_str = _format_info_field(variant.info)
    qual_str = f"{variant.quality:.1f}" if variant.quality > 0 else "."

    return "\t".join([
        variant.chromosome,
        str(variant.position),
        variant.id,
        variant.ref_allele,
        variant.alt_allele,
        qual_str,
        variant.filter_status,
        info_str,
    ])


# ─── Private Helpers ─────────────────────────────────────────────────────────


def _parse_info_field(info_str: str) -> dict:
    """Parse VCF INFO field (semicolon-separated key=value pairs)."""
    info = {}
    info_str = info_str.strip()
    if not info_str or info_str == ".":
        return info

    for item in info_str.split(";"):
        item = item.strip()
        if "=" in item:
            key, value = item.split("=", 1)
            info[key.strip()] = value.strip()
        elif item:
            # Flag (key without value)
            info[item] = True

    return info


def _format_info_field(info: dict) -> str:
    """Format info dict back to VCF INFO string."""
    if not info:
        return "."

    parts = []
    for key, value in info.items():
        if value is True:
            parts.append(key)
        else:
            parts.append(f"{key}={value}")

    return ";".join(parts)


def _extract_gene(info: dict) -> str | None:
    """Extract gene name from INFO field annotations.

    Checks common annotation keys: Gene, GENE, gene, ANN (SnpEff format).
    """
    # Direct gene annotation
    for key in ("Gene", "GENE", "gene"):
        if key in info:
            return info[key].upper()

    # SnpEff ANN field: ANN=A|missense|...|BRCA1|...
    if "ANN" in info:
        ann_parts = str(info["ANN"]).split("|")
        if len(ann_parts) >= 4:
            return ann_parts[3].upper()

    return None


def _determine_variant_type(info: dict) -> VariantType:
    """Determine variant type from INFO field annotations."""
    for key in ("Type", "type", "TYPE", "VariantType"):
        if key in info:
            type_str = str(info[key]).lower()
            type_map = {
                "missense": VariantType.MISSENSE,
                "nonsense": VariantType.NONSENSE,
                "frameshift": VariantType.FRAMESHIFT,
                "silent": VariantType.SILENT,
                "synonymous": VariantType.SILENT,
                "splice": VariantType.SPLICE,
                "deletion": VariantType.DELETION,
                "insertion": VariantType.INSERTION,
            }
            return type_map.get(type_str, VariantType.UNKNOWN)

    return VariantType.UNKNOWN
