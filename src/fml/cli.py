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


@app.command()
def images(only: list[str] = typer.Argument(None, help="Image name prefixes, e.g. fml-runtime")):
    """Rebuild the project images and load them into kind."""
    from fml import platform

    platform.build_images(only)


@app.command()
def apply() -> None:
    """Apply the app manifests in k8s/ (scorer Rollout, monitor, workflow, alerts, dashboard)."""
    from fml import platform

    platform.kubectl("apply", "-k", "k8s")


@app.command()
def demo(
    scenario: str = typer.Option("test/new_fraud_pattern", help="Scenario key, e.g. test/control"),
    seed: int = typer.Option(201),
    days: int = typer.Option(None, help="Stop after this many simulated days"),
    policy: str = typer.Option("drift", help="drift or none"),
) -> None:
    """Run one scenario end to end on the cluster (replay -> monitor -> retrain -> canary)."""
    from fml.replay.fullloop import demo as run_demo

    run_demo(scenario, seed, days, policy)


@app.command()
def collect(run: str) -> None:
    """Copy a full-loop run's timeline, metrics and reports into results/fullloop/."""
    from fml.replay.fullloop import collect as do_collect

    do_collect(run)


@app.command()
def backtest(
    set_name: str = typer.Option("test", "--set", help="dev or test"),
    policy: list[str] = typer.Option(None, help="Limit to these policies"),
    scenario: list[str] = typer.Option(None, help="Limit to these scenario names"),
    workers: int = typer.Option(None),
) -> None:
    """Fast in-process policy comparison (resumable: finished runs are skipped)."""
    from fml.backtest.runner import run_set
    from fml.policy import load_config

    cfg = load_config()
    if set_name == "test" and not cfg.get("frozen"):
        raise typer.BadParameter("configs/experiment.yaml must be frozen before the test set")
    run_set(set_name, cfg, policy or None, scenario or None, workers)


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
