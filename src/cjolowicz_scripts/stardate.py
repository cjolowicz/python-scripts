"""Display stargazers per time interval for a GitHub repository."""
from __future__ import annotations

import argparse
import contextlib
import datetime
import hashlib
import json
import os
import time
from collections import Counter
from collections.abc import Iterable
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import platformdirs
from matplotlib import pyplot
from rich import print
from rich.console import Console
from rich.progress import Progress
from rich.table import Table


Results = list[dict[str, Any]]


@dataclass
class Page:
    """A page of results from the GitHub API."""

    url: str
    link: dict[str, str]
    etag: str
    results: Results
    cached: bool


def save_page_to_cache(page: Page) -> None:
    """Store page in the cache."""
    data = {
        "url": page.url,
        "link": page.link,
        "etag": page.etag,
        "results": page.results,
    }

    digest = hashlib.blake2b(page.url.encode()).hexdigest()
    cachedir = Path(platformdirs.user_cache_dir("stardate"))
    cache = cachedir / digest

    cachedir.mkdir(parents=True, exist_ok=True)
    with cache.open(mode="w") as io:
        json.dump(data, io)


def load_page_from_cache(url: str) -> Page | None:
    """Load results from the cache."""
    digest = hashlib.blake2b(url.encode()).hexdigest()
    cachedir = Path(platformdirs.user_cache_dir("stardate"))
    cache = cachedir / digest

    if not cache.is_file():
        return None

    with cache.open() as io:
        data = json.load(io)
        return Page(data["url"], data["link"], data["etag"], data["results"], True)


def parse_link_header(response: httpx.Response) -> dict[str, str]:
    """Parse the Link header."""

    def _() -> Iterator[tuple[str, str]]:
        header = response.headers["Link"]
        for field in header.split(","):
            url, rel = field.split(";")
            url = url.strip().removeprefix("<").removesuffix(">")
            rel = rel.strip().removeprefix('rel="').removesuffix('"')
            yield rel, url

    return dict(_())


def parse_starred_at(results: Results) -> list[datetime.datetime]:
    """Parse the response."""

    def _() -> Iterator[datetime.datetime]:
        assert isinstance(results, list), f"got {results = }"  # noqa: S101
        for stargazer in results:
            assert isinstance(stargazer, dict)  # noqa: S101
            starred_at = stargazer["starred_at"]
            assert isinstance(starred_at, str)  # noqa: S101
            yield datetime.datetime.fromisoformat(starred_at.replace("Z", "+00:00"))

    return list(_())


def request_stargazers(url: str, *, token: str, etag: str | None) -> httpx.Response:
    """Retrieve stargazers from the API."""
    headers = {
        "Accept": "application/vnd.github.v3.star+json",
        "Authorization": f"token {token}",
    }

    if etag:
        headers |= {"If-None-Match": etag}

    response = httpx.get(url, headers=headers, params={"per_page": 100})

    if response.status_code != httpx.codes.NOT_MODIFIED:
        response.raise_for_status()

    return response


def get_stargazers_page(url: str, *, token: str, cache: bool = False) -> Page:
    """Retrieve stargazers from the cache or the API."""
    page = load_page_from_cache(url)
    etag = page.etag if page else None

    if cache and page:
        return page

    response = request_stargazers(url, token=token, etag=etag)

    if response.status_code == httpx.codes.NOT_MODIFIED:
        assert page is not None  # noqa: S101
    else:
        etag = response.headers["ETag"]
        link = parse_link_header(response)
        page = Page(url, link, etag, response.json(), False)
        save_page_to_cache(page)

    return page


def parse_query_string(url: str) -> dict[str, str]:
    """Parse a query string."""

    def _() -> Iterator[tuple[str, str]]:
        query = httpx.URL(url).query.decode()
        for field in query.split("&"):
            key, value = field.split("=", 1)
            yield key, value

    return dict(_())


def parse_page_parameter(url: str) -> int:
    """Return the current page and total number of pages."""
    variables = parse_query_string(url)
    return int(variables.get("page", "0"))


def get_star_dates(
    repository: str, *, token: str, console: Console, cache: bool = False
) -> Iterator[datetime.datetime]:
    """Retrieve the star dates for a repository."""
    with Progress(console=console, transient=True) as progress:
        task = progress.add_task("Downloading stargazers…")
        page = get_stargazers_page(
            f"https://api.github.com/repos/{repository}/stargazers",
            token=token,
            cache=cache,
        )

        yield from parse_starred_at(page.results)

        while url := page.link.get("next"):
            if last := page.link.get("last"):
                current = parse_page_parameter(url)
                total = parse_page_parameter(last)
                progress.update(task, total=total, completed=current)

            if not page.cached:
                time.sleep(1)

            page = get_stargazers_page(url, token=token, cache=cache)

            yield from parse_starred_at(page.results)


def truncate(
    now: datetime.datetime, instant: datetime.datetime, interval: datetime.timedelta
) -> datetime.datetime:
    """Truncate an instant to the nearest interval."""
    delta = now - instant
    delta = interval * (delta // interval)
    return now - delta


def aggregate_star_dates(
    dates: Iterable[datetime.datetime], interval: datetime.timedelta
) -> dict[datetime.datetime, int]:
    """Aggregate the star dates for a repository."""
    now = datetime.datetime.now(datetime.timezone.utc)
    return Counter(sorted(truncate(now, date, interval) for date in dates))


def plot_star_dates(
    counter: dict[datetime.datetime, int], repository: str, interval: datetime.timedelta
) -> None:
    """Plot the star dates for a repository."""
    pyplot.bar(
        counter.keys(),
        counter.values(),
        width=interval,
        color=["cornflowerblue", "lightsteelblue"],
    )
    pyplot.title(repository)
    pyplot.show()


def print_star_dates(
    counter: dict[datetime.datetime, int],
    repository: str,
    *,
    console: Console,
    interval: datetime.timedelta,
) -> None:
    """Print the star dates for a repository."""
    table = Table(title=repository)
    table.add_column("Date")
    table.add_column("Stars", justify="right")

    if interval < datetime.timedelta(days=1):
        dateformat = "%Y-%m-%d %H:%M:%S"
    else:
        dateformat = "%Y-%m-%d"

    for date, count in counter.items():
        table.add_row(f"{date:{dateformat}}", f"{count}")

    print()
    console.print(table)


def parse_interval(interval: str) -> datetime.timedelta:
    """Parse a time interval."""
    if interval in ["Y", "year"]:
        return datetime.timedelta(days=365)

    if interval in ["m", "month"]:
        return datetime.timedelta(days=31)

    if interval in ["w", "week"]:
        return datetime.timedelta(weeks=1)

    if interval in ["d", "day"]:
        return datetime.timedelta(days=1)

    if interval in ["H", "hour"]:
        return datetime.timedelta(hours=1)

    if interval in ["M", "minute"]:
        return datetime.timedelta(minutes=1)

    if interval in ["S", "second"]:
        return datetime.timedelta(seconds=1)

    return datetime.timedelta(days=1)


def create_argument_parser() -> argparse.ArgumentParser:
    """Return the command-line parser."""
    parser = argparse.ArgumentParser()
    parser.add_argument("repository")
    parser.add_argument("-i", "--interval")
    parser.add_argument("--plot", action="store_true", default=False)
    parser.add_argument("--cache", action="store_true", default=False)
    parser.add_argument("--token")
    return parser


def load_token() -> str | None:
    """Read the token from the cache."""
    cachedir = Path(platformdirs.user_cache_dir("stardate"))
    tokencache = cachedir / "token"
    with contextlib.suppress(FileNotFoundError):
        return tokencache.read_text()
    return None


def save_token(token: str) -> None:
    """Store the token in the cache."""
    cachedir = Path(platformdirs.user_cache_dir("stardate"))
    tokencache = cachedir / "token"
    tokencache.parent.mkdir(exist_ok=True)
    tokencache.write_text(token)


def find_token(args: argparse.Namespace) -> str | None:
    """Determine the GitHub API token."""
    if token := args.token or os.environ.get("GITHUB_TOKEN"):
        save_token(token)
        return token

    return load_token()


def main() -> None:
    """Main entry point."""
    parser = create_argument_parser()
    args = parser.parse_args()
    interval = parse_interval(args.interval)
    token = find_token(args)

    if not token:
        raise Exception("use --token or GITHUB_TOKEN to specify the API token")

    console = Console()
    dates = get_star_dates(
        args.repository, token=token, console=console, cache=args.cache
    )
    counter = aggregate_star_dates(dates, interval=interval)

    if args.plot:
        plot_star_dates(counter, args.repository, interval=interval)
    else:
        print_star_dates(counter, args.repository, interval=interval, console=console)


if __name__ == "__main__":
    main()
