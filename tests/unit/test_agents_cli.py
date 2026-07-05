"""Unit tests for local Agents CLI helpers."""

from __future__ import annotations

from argparse import Namespace

import pytest

from tools.agents_cli import build_demo_command, build_pytest_command, create_agent_scaffold


def test_create_agent_scaffold(tmp_path):
    repo_root = tmp_path / "repo"
    (repo_root / "agents").mkdir(parents=True)

    created = create_agent_scaffold(
        "demo_agent",
        description="Demo agent scaffold",
        repo_root=repo_root,
    )

    assert created == repo_root / "agents" / "demo_agent"
    assert (created / "agent.yaml").read_text(encoding="utf-8").startswith("name: demo_agent")
    assert "Demo agent scaffold" in (created / "prompt.md").read_text(encoding="utf-8")


def test_create_agent_scaffold_rejects_existing(tmp_path):
    repo_root = tmp_path / "repo"
    agent_dir = repo_root / "agents" / "demo_agent"
    agent_dir.mkdir(parents=True)
    (agent_dir / "agent.yaml").write_text("name: demo_agent\n", encoding="utf-8")

    with pytest.raises(FileExistsError):
        create_agent_scaffold(
            "demo_agent",
            description="Demo agent scaffold",
            repo_root=repo_root,
        )


def test_build_demo_command_includes_runtime_and_ollama_flag():
    args = Namespace(
        vcf="data/samples/sample_variants.vcf",
        output_dir="output",
        session_id="demo",
        runtime="adk",
        check_ollama=True,
    )

    command = build_demo_command(args)

    assert "--runtime" in command
    assert "adk" in command
    assert "--check-ollama" in command


def test_build_pytest_command_defaults_to_unit_and_integration():
    args = Namespace(coverage=True, unit_only=False, integration_only=False)

    command = build_pytest_command(args)

    assert command[:3] == [command[0], "-m", "pytest"]
    assert "--cov=src" in command
    assert "tests/unit" in command
    assert "tests/integration" in command
