"""Tests for the Anything-to-MCP CLI interface."""

from pathlib import Path
import pytest

from backend.generator.cli import main

EXAMPLES_DIR = Path(__file__).parent.parent.parent / "examples"
FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_cli_version(capsys: pytest.CaptureFixture[str]) -> None:
    """Verify --version prints the CLI version and exits cleanly."""
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "anything-to-mcp 0.1.0" in captured.out


def test_cli_missing_spec_argument(capsys: pytest.CaptureFixture[str]) -> None:
    """Verify error when --spec argument is omitted."""
    with pytest.raises(SystemExit) as exc_info:
        main([])
    assert exc_info.value.code != 0
    captured = capsys.readouterr()
    assert "required: --spec" in captured.err


def test_cli_nonexistent_spec_file(capsys: pytest.CaptureFixture[str]) -> None:
    """Verify error when --spec points to a non-existent file."""
    code = main(["--spec", "non_existent_spec.yaml"])
    assert code == 1
    captured = capsys.readouterr()
    assert "Specification file not found" in captured.err


def test_cli_invalid_spec_file(capsys: pytest.CaptureFixture[str]) -> None:
    """Verify error when specification is invalid (e.g. Swagger 2.0)."""
    swagger_path = FIXTURES_DIR / "swagger_v2.json"
    code = main(["--spec", str(swagger_path)])
    assert code == 1
    captured = capsys.readouterr()
    assert "Generation failed" in captured.err
    assert "Swagger 2.0" in captured.err


def test_cli_successful_generation(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Verify successful generation through CLI."""
    spec_path = EXAMPLES_DIR / "task_management_api.yaml"
    out_dir = tmp_path / "cli_output"

    code = main([
        "--spec", str(spec_path),
        "--output", str(out_dir),
        "--package-name", "custom_task_pkg",
        "--base-url", "https://custom.api.example.com",
    ])
    assert code == 0

    captured = capsys.readouterr()
    assert "Successfully generated MCP server!" in captured.out
    assert "Package: custom_task_pkg" in captured.out
    assert "https://custom.api.example.com" in captured.out
    assert "list_tasks" in captured.out

    pkg_dir = out_dir / "custom_task_pkg"
    assert (pkg_dir / "server.py").exists()
    assert (pkg_dir / "README.md").exists()
    assert (pkg_dir / "requirements.txt").exists()


def test_cli_read_only_mode(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Verify --read-only flag generates only GET operations."""
    spec_path = EXAMPLES_DIR / "task_management_api.yaml"
    out_dir = tmp_path / "ro_output"

    code = main([
        "--spec", str(spec_path),
        "--output", str(out_dir),
        "--package-name", "ro_pkg",
        "--read-only",
    ])
    assert code == 0

    captured = capsys.readouterr()
    assert "Mode: Read-Only (GET only)" in captured.out
    assert "list_tasks" in captured.out
    assert "create_task" not in captured.out


def test_cli_no_overwrite_protection(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Verify --no-overwrite refuses to overwrite an existing non-empty directory."""
    spec_path = EXAMPLES_DIR / "task_management_api.yaml"
    out_dir = tmp_path / "protected_output"

    # 1. Initial generation succeeds
    code1 = main([
        "--spec", str(spec_path),
        "--output", str(out_dir),
        "--package-name", "p_pkg",
    ])
    assert code1 == 0

    # 2. Second generation with --no-overwrite fails
    code2 = main([
        "--spec", str(spec_path),
        "--output", str(out_dir),
        "--package-name", "p_pkg",
        "--no-overwrite",
    ])
    assert code2 == 1

    captured = capsys.readouterr()
    assert "already exists and contains files" in captured.err
