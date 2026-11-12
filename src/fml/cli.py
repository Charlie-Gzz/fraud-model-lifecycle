"""The `fml` command line: one entry point for the whole project."""

from __future__ import annotations

import subprocess
import sys

import typer

from fml import REPO_ROOT

app = typer.Typer(
    help="Fraud model lifecycle: platform, experiments, and assets.", no_args_is_help=True
)


def _run(cmd: list[str]) -> int:
    return subprocess.call(cmd, cwd=REPO_ROOT)


@app.command()
def tools(force: bool = typer.Option(False, help="Re-download even if present.")) -> None:
    """Download the pinned CLI tools (kind, kubectl, helm, terraform, argo) into .tools/."""
    from fml.tools import install_all

    for name, path in install_all(force).items():
        typer.echo(f"{name:24s} {path.relative_to(REPO_ROOT)}")


@app.command(context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def test(ctx: typer.Context) -> None:
    """Run the test suite. Extra arguments go straight to pytest."""
    raise typer.Exit(_run([sys.executable, "-m", "pytest", *ctx.args]))


@app.command()
def lint() -> None:
    """Run ruff (lint + format check)."""
    code = _run([sys.executable, "-m", "ruff", "check", "src", "tests"])
    code |= _run([sys.executable, "-m", "ruff", "format", "--check", "src", "tests"])
    raise typer.Exit(code)


if __name__ == "__main__":
    app()
