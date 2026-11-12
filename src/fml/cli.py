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


@app.command()
def up(skip_images: bool = typer.Option(False, help="Reuse images already loaded.")) -> None:
    """Create the kind cluster, install the platform, start port-forwards, smoke-check."""
    from fml import platform

    result = platform.up(skip_images=skip_images)
    raise typer.Exit(0 if all(result.values()) else 1)


@app.command()
def down() -> None:
    """Stop port-forwards and delete the cluster (images are kept for a fast restart)."""
    from fml import platform

    platform.down()


@app.command()
def status() -> None:
    """Show pods, port-forwards and cluster memory."""
    from fml import platform

    platform.status()


@app.command()
def forward() -> None:
    """(Re)start the 127.0.0.1 port-forwards."""
    from fml import platform

    platform.start_port_forwards()


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
