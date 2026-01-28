from typer.testing import CliRunner

from envbox.main import app  # ← changed to envbox

runner = CliRunner()


def test_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "envsync" in result.stdout
