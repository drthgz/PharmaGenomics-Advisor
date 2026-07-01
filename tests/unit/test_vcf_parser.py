"""Unit tests for VCF parser."""

import tempfile
from pathlib import Path

import pytest

from src.exceptions import VCFEmptyError, VCFFormatError, VCFTooLargeError
from src.models import RouteStatus, VariantType
from src.parsers.vcf_parser import VCFParser, format_variant_to_vcf, parse_vcf_line


class TestParseVCFLine:
    """Test single-line VCF parsing."""

    def test_valid_simple_variant(self):
        line = "chr17\t41234470\t.\tA\tG\t99.0\tPASS\tGene=BRCA1;Type=missense"
        variant = parse_vcf_line(line, line_num=1)
        assert variant.chromosome == "chr17"
        assert variant.position == 41234470
        assert variant.ref_allele == "A"
        assert variant.alt_allele == "G"
        assert variant.quality == 99.0
        assert variant.filter_status == "PASS"
        assert variant.gene == "BRCA1"
        assert variant.route_status == RouteStatus.ROUTED

    def test_unrouted_gene(self):
        line = "chr1\t100000\t.\tC\tT\t50.0\tPASS\tGene=KRAS;Type=missense"
        variant = parse_vcf_line(line, line_num=1)
        assert variant.gene == "KRAS"
        assert variant.route_status == RouteStatus.UNROUTED

    def test_missing_quality(self):
        line = "chr7\t55259515\t.\tT\tG\t.\tPASS\tGene=EGFR"
        variant = parse_vcf_line(line, line_num=1)
        assert variant.quality == 0.0
        assert variant.gene == "EGFR"
        assert variant.route_status == RouteStatus.ROUTED

    def test_too_few_fields(self):
        with pytest.raises(VCFFormatError) as exc_info:
            parse_vcf_line("chr17\t100\tA\tG", line_num=5)
        assert "5" in str(exc_info.value)
        assert "COLUMNS" in str(exc_info.value)

    def test_invalid_position(self):
        line = "chr17\tNOTNUMBER\t.\tA\tG\t99\tPASS\t."
        with pytest.raises(VCFFormatError) as exc_info:
            parse_vcf_line(line, line_num=3)
        assert "POS" in str(exc_info.value)
        assert "3" in str(exc_info.value)


class TestVCFParser:
    """Test full file parsing."""

    def _write_vcf(self, lines: list[str]) -> Path:
        """Write lines to a temp VCF file."""
        tf = tempfile.NamedTemporaryFile(mode="w", suffix=".vcf", delete=False)
        tf.write("\n".join(lines))
        tf.close()
        return Path(tf.name)

    def test_parse_sample_file(self):
        lines = [
            "##fileformat=VCFv4.2",
            "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO",
            "chr17\t41234470\t.\tA\tG\t99.0\tPASS\tGene=BRCA1;Type=missense",
            "chr7\t55259515\t.\tT\tG\t95.0\tPASS\tGene=EGFR;Type=missense",
        ]
        path = self._write_vcf(lines)
        parser = VCFParser()
        result = parser.parse(path)
        assert result.total_count == 2
        assert result.routed_count == 2
        assert result.unrouted_count == 0

    def test_empty_file(self):
        lines = [
            "##fileformat=VCFv4.2",
            "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO",
        ]
        path = self._write_vcf(lines)
        parser = VCFParser()
        with pytest.raises(VCFEmptyError):
            parser.parse(path)

    def test_file_not_found(self):
        parser = VCFParser()
        with pytest.raises(FileNotFoundError):
            parser.parse("/nonexistent/file.vcf")


class TestRoundTrip:
    """Test parse → format → parse round-trip."""

    def test_basic_roundtrip(self):
        line = "chr17\t41234470\t.\tA\tG\t99.0\tPASS\tGene=BRCA1;Type=missense"
        variant = parse_vcf_line(line, line_num=1)
        formatted = format_variant_to_vcf(variant)
        reparsed = parse_vcf_line(formatted, line_num=1)

        assert reparsed.chromosome == variant.chromosome
        assert reparsed.position == variant.position
        assert reparsed.ref_allele == variant.ref_allele
        assert reparsed.alt_allele == variant.alt_allele
        assert abs(reparsed.quality - variant.quality) < 0.01
