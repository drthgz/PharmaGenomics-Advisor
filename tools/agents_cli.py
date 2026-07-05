"""Agents CLI style helpers for local agent lifecycle management."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = REPO_ROOT / "agents"
DEMO_SCRIPT = REPO_ROOT / "scripts" / "demo.py"


def create_agent_scaffold(
    name: str,
    description: str,
    model: str = "medgemma",
    *,
    repo_root: Path = REPO_ROOT,
    force: bool = False,
) -> Path:
    """Create an Agents CLI compatible scaffold under agents/."""
    agent_dir = repo_root / "agents" / name
    agent_dir.mkdir(parents=True, exist_ok=True)

    agent_yaml = agent_dir / "agent.yaml"
    prompt_md = agent_dir / "prompt.md"

    if not force and (agent_yaml.exists() or prompt_md.exists()):
        raise FileExistsError(f"Agent scaffold already exists for '{name}'")

    agent_yaml.write_text(
        "\n".join(
            [
                f"name: {name}",
                f"model: {model}",
                f'description: "{description}"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    prompt_md.write_text(
        "\n".join(
            [
                f"# {name} Agent — System Prompt",
                "",
                description,
                "",
                "## Responsibilities",
                "",
                "1. Receive structured inputs from the supervisor agent",
                "2. Use the configured MCP tools when available",
                "3. Return structured outputs that match the project schemas",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return agent_dir


def build_demo_command(args: argparse.Namespace) -> list[str]:
    """Build the demo command used by the run subcommand."""
    command = [
        sys.executable,
        str(DEMO_SCRIPT),
        "--vcf",
        args.vcf,
        "--output-dir",
        args.output_dir,
        "--session-id",
        args.session_id,
        "--runtime",
        args.runtime,
    ]
    if args.check_ollama:
        command.append("--check-ollama")
    return command


def build_pytest_command(args: argparse.Namespace) -> list[str]:
    """Build the pytest command used by the test subcommand."""
    command = [sys.executable, "-m", "pytest"]
    if args.coverage:
        command.extend(["--cov=src", "--cov-report=term-missing"])
    if args.unit_only:
        command.append("tests/unit")
    elif args.integration_only:
        command.append("tests/integration")
    else:
        command.extend(["tests/unit", "tests/integration"])
    return command


def _run_subprocess(command: list[str]) -> int:
    completed = subprocess.run(command, cwd=REPO_ROOT, check=False)
    return completed.returncode


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pharmagenomics-agents",
        description="Agents CLI style workflow helpers for PharmaGenomics Advisor",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_parser = subparsers.add_parser("create", help="Scaffold a new agent")
    create_parser.add_argument("name", help="Agent directory name")
    create_parser.add_argument("--description", default="New agent scaffold")
    create_parser.add_argument("--model", default="medgemma")
    create_parser.add_argument("--force", action="store_true")

    run_parser = subparsers.add_parser("run", help="Run the sample pipeline locally")
    run_parser.add_argument("--vcf", default="data/samples/sample_variants.vcf")
    run_parser.add_argument("--output-dir", default="output")
    run_parser.add_argument("--session-id", default="agents-cli-session")
    run_parser.add_argument("--runtime", default="local", choices=["local", "adk"])
    run_parser.add_argument("--check-ollama", action="store_true")

    test_parser = subparsers.add_parser("test", help="Run project tests")
    test_parser.add_argument("--coverage", action="store_true")
    test_group = test_parser.add_mutually_exclusive_group()
    test_group.add_argument("--unit-only", action="store_true")
    test_group.add_argument("--integration-only", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point for the local Agents CLI helper."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "create":
        created = create_agent_scaffold(
            args.name,
            description=args.description,
            model=args.model,
            force=args.force,
        )
        print(f"Created agent scaffold at {created}")
        return 0

    if args.command == "run":
        return _run_subprocess(build_demo_command(args))

    if args.command == "test":
        return _run_subprocess(build_pytest_command(args))

    parser.error(f"Unsupported command: {args.command}")
    return 2
