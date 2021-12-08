"""Command-line interface."""
import click


@click.command()
@click.version_option()
def main() -> None:
    """Miscellaneous Python scripts."""


if __name__ == "__main__":
    main(prog_name="cjolowicz-scripts")  # pragma: no cover
