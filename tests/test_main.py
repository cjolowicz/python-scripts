"""Test cases for the __main__ module."""
import pytest
from click import BaseCommand
from click.testing import CliRunner

from cjolowicz_scripts import dependabot_rebase_all


@pytest.fixture
def runner() -> CliRunner:
    """Fixture for invoking command-line interfaces."""
    return CliRunner()


@pytest.mark.parametrize(
    "main",
    [dependabot_rebase_all.main],
)
def test_help(runner: CliRunner, main: BaseCommand) -> None:
    """It exits with a status code of zero."""
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
