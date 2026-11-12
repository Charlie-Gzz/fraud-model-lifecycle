from typer.testing import CliRunner

from fml.cli import app


def test_help_lists_commands():
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "tools" in result.output
