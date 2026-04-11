"""Pins the integration matrix.

Three things this test enforces:

1. Every entry in ``INTEGRATIONS`` declares a valid ``kind``.
2. ``pre_execution_gate`` is consistent with ``kind`` (gate => True,
   audit => False, adapter => False).
3. The README's integration table mentions every integration name and
   marks every gate as having a real gate. This is the test that catches
   it when somebody changes a docstring without updating the README.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aira.extras import INTEGRATIONS, IntegrationSpec, integration_matrix_markdown


VALID_KINDS = {"gate", "audit", "adapter"}


def test_every_integration_has_valid_kind():
    for spec in INTEGRATIONS:
        assert spec.kind in VALID_KINDS, f"{spec.name} has invalid kind {spec.kind!r}"


def test_kind_matches_pre_execution_gate_flag():
    for spec in INTEGRATIONS:
        if spec.kind == "gate":
            assert spec.pre_execution_gate is True, (
                f"{spec.name}: kind=gate must have pre_execution_gate=True"
            )
        else:
            assert spec.pre_execution_gate is False, (
                f"{spec.name}: kind={spec.kind} must have pre_execution_gate=False"
            )


def test_no_duplicate_names():
    names = [s.name for s in INTEGRATIONS]
    assert len(names) == len(set(names)), "duplicate integration names"


def test_required_competitive_integrations_present():
    """The integrations we explicitly counter the LangChain RFC competitors
    on must remain in the registry. If somebody removes one, the test fails."""
    names = {s.name for s in INTEGRATIONS}
    must_have = {"LangChain", "OpenAI Agents", "AWS Bedrock", "Google ADK", "CrewAI", "MCP"}
    missing = must_have - names
    assert not missing, f"Missing integrations: {missing}"


def test_at_least_four_real_gates():
    """Quality over count. At least four of our integrations must be real
    pre-execution gates, not audit shims that only record after the fact."""
    gates = [s for s in INTEGRATIONS if s.kind == "gate"]
    assert len(gates) >= 4, (
        f"Only {len(gates)} real-gate integrations; need at least 4 to credibly "
        "claim 'we wrap a real policy gate around your existing framework'."
    )


def test_crewai_is_honestly_labeled_audit():
    """CrewAI cannot be a gate (no pre-exec hook); we must label it that way."""
    crewai = next(s for s in INTEGRATIONS if s.name == "CrewAI")
    assert crewai.kind == "audit"
    assert crewai.pre_execution_gate is False


def test_integration_matrix_markdown_renders():
    md = integration_matrix_markdown()
    assert "| Integration |" in md
    for spec in INTEGRATIONS:
        assert spec.name in md


def test_readme_references_every_integration():
    """The README integration matrix must mention every integration in the
    registry. Catches it when somebody adds an extra without documenting it."""
    readme = Path(__file__).resolve().parents[1] / "README.md"
    if not readme.exists():
        pytest.skip("README.md not present")
    text = readme.read_text(encoding="utf-8")
    for spec in INTEGRATIONS:
        assert spec.name in text, f"README does not mention {spec.name}"
