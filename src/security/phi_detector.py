"""Protected Health Information (PHI) detection.

Detects common PHI patterns (names, dates of birth, MRNs) in inputs to prevent
accidental processing of patient-identifiable data.

When clinical_use_mode is enabled (via environment variable), PHI is allowed through.
"""

from __future__ import annotations

import re

from src.models import ValidationResult

# ─── PHI Pattern Definitions ─────────────────────────────────────────────────

# Common date of birth formats
DOB_PATTERNS = [
    r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b",  # MM/DD/YYYY, DD-MM-YYYY
    r"\b(0[1-9]|1[0-2])\d{6,8}\b",  # Compact date formats
    r"(?i)\b(dob|date\s*of\s*birth|birth\s*date)\s*[:=]?\s*\S+",
]

# Medical Record Number patterns
MRN_PATTERNS = [
    r"(?i)\b(mrn|medical\s*record|patient\s*id|chart\s*number)\s*[:=#]?\s*\w+",
    r"\b[A-Z]{2,3}\d{6,10}\b",  # Common MRN format: 2-3 letters + 6-10 digits
]

# Name patterns (simplified - First Last with capitalization)
NAME_PATTERNS = [
    r"(?i)\b(patient|name|pt)\s*[:=]?\s*[A-Z][a-z]+\s+[A-Z][a-z]+",
    r"(?i)\b(mr|mrs|ms|dr)\.?\s+[A-Z][a-z]+\s+[A-Z][a-z]+",
]

# Social Security Number
SSN_PATTERNS = [
    r"\b\d{3}-\d{2}-\d{4}\b",
    r"(?i)\b(ssn|social\s*security)\s*[:=#]?\s*\d",
]


class PHIDetector:
    """Detects Protected Health Information in text inputs.

    Usage:
        detector = PHIDetector(clinical_use_mode=False)
        result = detector.check("Patient: John Smith DOB: 01/15/1980")
        # result.is_valid == False (PHI detected)
    """

    def __init__(self, clinical_use_mode: bool = False):
        """Initialize PHI detector.

        Args:
            clinical_use_mode: If True, PHI is allowed (for actual clinical deployments).
                              Set via PHI_CLINICAL_USE environment variable.
        """
        self.clinical_use_mode = clinical_use_mode
        self._patterns: list[tuple[str, re.Pattern]] = []

        for pattern in DOB_PATTERNS:
            self._patterns.append(("date_of_birth", re.compile(pattern)))
        for pattern in MRN_PATTERNS:
            self._patterns.append(("medical_record_number", re.compile(pattern)))
        for pattern in NAME_PATTERNS:
            self._patterns.append(("patient_name", re.compile(pattern)))
        for pattern in SSN_PATTERNS:
            self._patterns.append(("social_security_number", re.compile(pattern)))

    def check(self, text: str) -> ValidationResult:
        """Check input for PHI patterns.

        Args:
            text: Input text to scan for PHI.

        Returns:
            ValidationResult. If clinical_use_mode is True, always returns is_valid=True.
        """
        if self.clinical_use_mode:
            return ValidationResult(is_valid=True)

        for phi_type, pattern in self._patterns:
            if pattern.search(text):
                return ValidationResult(
                    is_valid=False,
                    error_message=(
                        f"Input contains potential PHI ({phi_type}). "
                        "Set PHI_CLINICAL_USE=true to allow PHI processing."
                    ),
                    rejected_reason=f"phi_{phi_type}",
                )

        return ValidationResult(is_valid=True)
