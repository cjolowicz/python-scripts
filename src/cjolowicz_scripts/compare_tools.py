"""Compare the status, output, and runtime of two commands."""
import argparse
import datetime
import difflib
import itertools
import locale
import shlex
import statistics
import subprocess  # noqa: S404
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

import pygments.formatters
import pygments.lexers


T = TypeVar("T")


def pairwise(iterable: Iterable[T]) -> Iterable[tuple[T, T]]:
    """Return an iterable of each element with its successor."""
    a, b = itertools.tee(iterable)
    next(b, None)
    return zip(a, b)


def create_argument_parser() -> argparse.ArgumentParser:
    """Create the command-line parser."""
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        "--encoding",
        metavar="NAME",
        default=locale.getpreferredencoding(),
        help="encoding of command output",
    )
    parser.add_argument(
        "--encoding-errors",
        metavar="NAME",
        default="strict",
        help="error handling scheme when decoding text",
    )
    parser.add_argument(
        "--command",
        "-c",
        metavar="COMMAND",
        dest="commands",
        action="append",
        help="command line (use '{}' for filename, omit for stdin)",
    )
    parser.add_argument(
        "--files-from",
        metavar="FILE",
        help="Read paths to files from this file.",
    )
    parser.add_argument(
        "files",
        nargs="*",
    )
    return parser


def parse_args() -> argparse.Namespace:
    """Parse the command-line options."""
    parser = create_argument_parser()
    return parser.parse_args()


@dataclass
class Result:
    """The result of running a command."""

    command: str
    returncode: int
    stdout: str
    stderr: str
    runtime: datetime.timedelta


def run_command(command: str, path: Path, *, encoding: str, errors: str) -> Result:
    """Run the command and return the result."""
    if "{}" in command:
        full_command = command.replace("{}", str(path))
    else:
        full_command = f"{command} < {path}"

    start = datetime.datetime.now()
    process = subprocess.run(
        full_command,
        shell=True,  # noqa: S602
        capture_output=True,
        text=True,
        encoding=encoding,
        errors=errors,
    )
    runtime = datetime.datetime.now() - start

    return Result(command, process.returncode, process.stdout, process.stderr, runtime)


def compare_results(a: Result, b: Result) -> None:
    """Compare the results and print the output."""
    failed = [result for result in (a, b) if result.returncode != 0]

    for result in failed:
        print(f"{result.command!r} exited with status {result.returncode}")
        print()
        print(result.stderr)

    if failed:
        return

    a_executable, b_executable = (shlex.split(result.command)[0] for result in (a, b))

    if a.stdout == b.stdout:
        for result in (a, b):
            print(f"{result.runtime}  {result.command}")

        print()
        print("The output is identical.")

        return

    diff = "".join(
        difflib.unified_diff(
            a.stdout.splitlines(keepends=True),
            b.stdout.splitlines(keepends=True),
            fromfile=f"{a.runtime}",
            fromfiledate=a.command,
            tofile=f"{b.runtime}",
            tofiledate=b.command,
        )
    )

    formatted = pygments.highlight(
        diff,
        pygments.lexers.DiffLexer(),
        pygments.formatters.TerminalFormatter(),
    )

    print(formatted, end="")


def main() -> None:
    """The main entry point."""
    args = parse_args()
    paths = [Path(filename) for filename in args.files]

    if args.files_from:
        text = (
            sys.stdin.read()
            if args.files_from == "-"
            else Path(args.files_from).read_text()
        )
        paths.extend([Path(filename) for filename in text.splitlines()])

    all_results = []

    for path in paths:
        print(f"==> {path} <==")

        results = [
            run_command(
                command, path, encoding=args.encoding, errors=args.encoding_errors
            )
            for command in args.commands
        ]
        all_results.append(results)

        for a, b in pairwise(results):
            compare_results(a, b)

    print()
    print("--")

    for command in args.commands:
        seconds = statistics.mean(
            result.runtime.total_seconds()
            for results in all_results
            for result in results
            if result.command == command
        )
        runtime = datetime.timedelta(seconds=seconds)
        print(f"{runtime}  {command}")


if __name__ == "__main__":
    main()
