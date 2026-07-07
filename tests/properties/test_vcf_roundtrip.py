"""Property-based tests for the VCF parser round-trip property.

Tests validate that:
- Property 6: VCF parser round-trip (Requirement 5.2)
"""

# Feature: project-completion-fixes, Property 6: VCF parser round-trip

from __future__ import annotations

import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.strategies import composite

from src.models import Variant, VariantType, RouteStatus
from src.parsers.vcf_parser import format_variant_to_vcf, parse_vcf_line


# ─── Reserved INFO keys that trigger gene/type/hgvs extraction ────────────────

RESERVED_INFO_KEYS = frozenset({
    "Gene", "gene", "GENE",
    "ANN",
    "Type", "type", "TYPE", "VariantType",
    "HGVS", "hgvs",
})

# ─── Custom Strategies ────────────────────────────────────────────────────────

# Alphanumeric characters for INFO keys/values (no semicolons, equals, whitespace)
_alphanum_chars = st.characters(
    whitelist_categories=("L", "N"),
    whitelist_characters="_",
)

# INFO key strategy: 1-20 alphanumeric characters, no reserved keys
_info_key = st.text(
    alphabet=_alphanum_chars,
    min_size=1,
    max_size=20,
).filter(lambda k: k not in RESERVED_INFO_KEYS)

# INFO value strategy: 1-50 alphanumeric characters (string values only, no booleans)
_info_value = st.text(
    alphabet=_alphanum_chars,
    min_size=1,
    max_size=50,
)

# INFO dict strategy: 0-10 entries with valid keys and string values
_info_dict = st.dictionaries(
    keys=_info_key,
    values=_info_value,
    min_size=0,
    max_size=10,
)

# Allele characters
_allele_alphabet = st.sampled_from(["A", "T", "C", "G", "N"])

# Chromosome: 1-10 characters (alphanumeric, common patterns like chr1, X, MT)
_chromosome = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N")),
    min_size=1,
    max_size=10,
)

# Position: 1 to 2,147,483,647
_position = st.integers(min_value=1, max_value=2_147_483_647)

# Alleles: 1-50 characters from {A, T, C, G, N}
_allele = st.text(
    alphabet=_allele_alphabet,
    min_size=1,
    max_size=50,
)

# Quality: floats between 0.0 and 99999.0
_quality = st.floats(min_value=0.0, max_value=99999.0, allow_nan=False, allow_infinity=False)

# Filter status: common VCF filter values
_filter_status = st.sampled_from(["PASS", ".", "LowQual", "q10"])

# Variant ID
_variant_id = st.sampled_from([".", "rs123", "var1"])


@composite
def valid_variants(draw):
    """Custom composite strategy generating valid Variant objects for round-trip testing.

    Constraints:
    - Chromosomes: 1-10 character alphanumeric strings
    - Positions: integers between 1 and 2,147,483,647
    - Alleles: strings of 1-50 characters from {A, T, C, G, N}
    - Quality scores: floats between 0.0 and 99999.0
    - INFO field: 0-10 entries, keys 1-20 chars (no semicolons/equals/whitespace),
      values 1-50 chars (no semicolons/equals/whitespace), no boolean flags,
      no reserved keys that trigger gene/type/hgvs extraction
    """
    chromosome = draw(_chromosome)
    position = draw(_position)
    variant_id = draw(_variant_id)
    ref_allele = draw(_allele)
    alt_allele = draw(_allele)
    quality = draw(_quality)
    filter_status = draw(_filter_status)
    info = draw(_info_dict)

    return Variant(
        chromosome=chromosome,
        position=position,
        id=variant_id,
        ref_allele=ref_allele,
        alt_allele=alt_allele,
        quality=quality,
        filter_status=filter_status,
        info=info,
        gene=None,
        variant_type=VariantType.UNKNOWN,
        hgvs=None,
        route_status=RouteStatus.UNROUTED,
    )


# ─── Property Test ────────────────────────────────────────────────────────────


class TestVCFParserRoundTrip:
    """**Validates: Requirements 5.2**

    For any valid Variant object, calling format_variant_to_vcf() then
    parse_vcf_line() on the result SHALL produce a Variant with all core
    VCF fields equal to the original.
    """

    @pytest.mark.property
    @settings(max_examples=100)
    @given(variant=valid_variants())
    def test_round_trip_preserves_core_fields(self, variant: Variant):
        """format_variant_to_vcf → parse_vcf_line produces equivalent Variant."""
        # Format to VCF line
        vcf_line = format_variant_to_vcf(variant)

        # Parse back
        parsed = parse_vcf_line(vcf_line, line_num=1)

        # Compare core VCF fields
        assert parsed.chromosome == variant.chromosome
        assert parsed.position == variant.position
        assert parsed.id == variant.id
        assert parsed.ref_allele == variant.ref_allele
        assert parsed.alt_allele == variant.alt_allele

        # Quality comparison: format_variant_to_vcf uses f"{quality:.1f}" for non-zero
        # values and "." for zero. This means precision is limited to 1 decimal place.
        # The round-trip expectation is that parsed quality equals the formatted value.
        if variant.quality == 0.0:
            assert parsed.quality == 0.0
        else:
            expected_quality = float(f"{variant.quality:.1f}")
            assert math.isclose(parsed.quality, expected_quality, rel_tol=1e-9), (
                f"Quality mismatch: original={variant.quality}, "
                f"expected_after_format={expected_quality}, parsed={parsed.quality}"
            )

        assert parsed.filter_status == variant.filter_status
        assert parsed.info == variant.info
