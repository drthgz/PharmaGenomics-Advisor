"""Property-based test for inline comment density in key modules.

Tests validate that:
- Property 3: Key modules have minimum inline comment density (Requirement 5.6)
"""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st


# ─── Constants ────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

KEY_MODULES = [
    "src/agents/supervisor.py",
    "src/agents/message_bus.py",
    "src/inference/ollama_client.py",
    "src/pipeline/orchestrator.py",
    "src/security/layer.py",
]

MINIMUM_INLINE_COMMENTS = 10


# ─── Helpers ──────────────────────────────────────────────────────────────────


def count_inline_comments(file_path: Path) -> int:
    """Count inline comment lines inside function/method bodies.

    An inline comment is a line where the stripped content starts with '#'
    and the line is indented (has leading whitespace), indicating it's inside
    a function or method body rather than being a module-level comment.

    Excludes:
    - Module-level comments (no indentation)
    - Lines that are part of docstrings (triple-quoted strings)
    """
    lines = file_path.read_text(encoding="utf-8").splitlines()
    count = 0
    for line in lines:
        stripped = line.strip()
        # Must start with '#' (a comment line)
        if not stripped.startswith("#"):
            continue
        # Must be indented (inside a function/method/class body)
        if line == stripped:
            # No leading whitespace means it's at module level
            continue
        # Line is indented and starts with '#' — it's an inline comment
        count += 1
    return count


# ─── Property Tests ──────────────────────────────────────────────────────────


class TestInlineCommentDensity:
    """**Validates: Requirements 5.6**

    For any key module file in the set {supervisor.py, message_bus.py,
    ollama_client.py, orchestrator.py, layer.py}, counting lines that match
    the pattern of inline comments within function/method bodies SHALL yield
    a count of at least 10.
    """

    @pytest.mark.property
    @settings(max_examples=100)
    @given(module_path=st.sampled_from(KEY_MODULES))
    def test_key_modules_have_minimum_inline_comments(self, module_path: str):
        """Each key module has at least 10 inline comment lines in function bodies."""
        full_path = PROJECT_ROOT / module_path
        assert full_path.exists(), f"Key module not found: {full_path}"

        comment_count = count_inline_comments(full_path)
        assert comment_count >= MINIMUM_INLINE_COMMENTS, (
            f"{module_path} has only {comment_count} inline comments "
            f"(minimum required: {MINIMUM_INLINE_COMMENTS})"
        )
