"""Show the top contributors in surviving LOC."""
from __future__ import annotations

import argparse
import json
import re
import subprocess  # noqa: S404
from collections import defaultdict
from collections.abc import Iterable
from collections.abc import Iterator
from pathlib import Path

import rich.console
import rich.progress
import rich.table
import rich.traceback

APP_NAME = "git-culpa"
TOTALS = "null"


def getcache() -> Path:
    """Return the path to the cache file."""
    return Path(f".{APP_NAME}.json")


def _parse_blame_incremental(text: str) -> Iterator[str]:
    """Yield the author of each line."""
    authors = {}
    sha = ""
    for line in text.splitlines():
        tag, _, payload = line.partition(" ")
        if len(tag) == 40:
            sha = tag
        elif sha:
            if tag == "author":
                authors[sha] = payload
            if tag == "filename":
                yield authors[sha]


def dump(*, exclude: str | None) -> None:
    """Dump contributions."""
    console = rich.console.Console(stderr=True)
    options = ["--", f":(exclude){exclude}"] if exclude else []
    process = subprocess.run(  # noqa: S603, S607
        ["git", "ls-files", *options],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )

    filenames = process.stdout.splitlines()
    contributions: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for filename in rich.progress.track(filenames, console=console):
        parts = filename.split("/")
        prefixes = ["/".join(parts[:index]) for index in range(len(parts) + 1)]
        process = subprocess.run(  # noqa: S603, S607
            ["git", "blame", "--incremental", "--", filename],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        )
        for author in _parse_blame_incremental(process.stdout):
            for prefix in prefixes:
                contributions[prefix][author] += 1
                contributions[prefix][TOTALS] += 1

    with getcache().open(mode="w") as io:
        json.dump(contributions, io)


def _compile_glob_character_class(pattern: str, pos: int) -> tuple[str, int]:
    start, end = pos, len(pattern)

    if pos < end and pattern[pos] == "!":
        pos += 1

    if pos < end and pattern[pos] == "]":
        pos += 1

    while pos < end and pattern[pos] != "]":
        pos += 1

    if pos >= end:
        return r"\[", start

    cclass = pattern[start:pos].replace("\\", "\\\\")
    pos += 1

    if cclass[0] == "!":
        cclass = "^" + cclass[1:]
    elif cclass[0] == "^":
        cclass = "\\" + cclass

    return f"[{cclass}]", pos


def _compile_glob_expression(pattern: str, pos: int) -> tuple[str, int]:
    character = pattern[pos]
    pos += 1

    if character == "*":
        return "[^/]*", pos

    if character == "?":
        return "[^/]", pos

    if character == "[":
        return _compile_glob_character_class(pattern, pos)

    return re.escape(character), pos


def compile_glob(pattern: str) -> re.Pattern[str]:
    """Translate glob pattern to a regular expression."""
    # https://stackoverflow.com/a/29820981/1355754

    def _() -> Iterator[str]:
        pos, length = 0, len(pattern)

        while pos < length:
            expression, pos = _compile_glob_expression(pattern, pos)
            yield expression

        yield r"\Z(?ms)"

    return re.compile("".join(_()))


def query(pathspecs: Iterable[str], *, top: int | None) -> None:
    """Query contributions."""
    with getcache().open() as io:
        contributions: dict[str, dict[str, int]] = json.load(io)

    patterns = [compile_glob(pathspec) for pathspec in pathspecs]
    if not patterns:
        patterns = [re.compile("^$")]

    console = rich.console.Console()

    for pattern in patterns:
        paths = sorted(path for path in contributions if pattern.match(path))
        author_width = max(
            len(author) for path in paths for author in contributions[path]
        )
        lines_width = max(
            len(str(lines)) for path in paths for lines in contributions[path].values()
        )

        for path in paths:
            blame = contributions[path]
            total = blame[TOTALS]

            table = rich.table.Table(title=path or "Total")
            table.add_column("Author", width=author_width)
            table.add_column("Lines", justify="right", width=lines_width)
            table.add_column("%Lines", justify="right", width=len("100.00%"))

            authors = sorted(
                (author for author in blame if author != TOTALS),
                key=lambda author: blame[author],
                reverse=True,
            )
            if top is not None:
                authors = authors[:top]

            for author in (TOTALS, *authors):
                lines = blame[author]
                percent = f"{100 * lines / total:.2f}%"
                author = author if author != TOTALS else "Total"
                table.add_row(author, str(lines), percent)

            console.print(table)


def create_argument_parser() -> argparse.ArgumentParser:
    """Create the command-line parser."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--invalidate",
        action="store_true",
        help="Invalidate the cache of contributions",
    )
    parser.add_argument(
        "--exclude",
        metavar="pathspec",
        help="Exclude the given pathspecs when computing contributions",
    )
    parser.add_argument(
        "--top",
        type=int,
        metavar="N",
        help="Only show the top N contributors",
    )
    parser.add_argument(
        "pathspecs",
        nargs="*",
        help="Show contributions matching the given pathspecs",
    )
    return parser


def main() -> None:
    """Main function."""
    rich.traceback.install(show_locals=True)

    parser = create_argument_parser()
    args = parser.parse_args()

    if args.invalidate or not getcache().exists():
        dump(exclude=args.exclude)

    query(args.pathspecs, top=args.top)
