"""Print *k* randomly chosen lines to stdout."""
import argparse
import random
import sys
from typing import TextIO


def create_argument_parser() -> argparse.ArgumentParser:
    """Create argument parser."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--lines",
        "-n",
        metavar="K",
        type=int,
        default=1,
        help="print K lines",
    )
    parser.add_argument(
        "files",
        nargs="*",
    )
    return parser


def sample(io: TextIO, k: int) -> None:
    """Print *k* randomly chosen lines to stdout."""
    for line in random.sample(list(io), k):
        sys.stdout.write(line)


def main() -> None:
    """The main entry point."""
    parser = create_argument_parser()
    args = parser.parse_args()
    if not args.files:
        sample(sys.stdin, args.lines)

    for filename in args.files:
        if filename == "-":
            sample(sys.stdin, args.lines)
        else:
            with open(filename) as io:
                sample(io, args.lines)


if __name__ == "__main__":
    main()
