"""Display dependents for a PyPI package."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import time
from collections.abc import Iterable
from collections.abc import Iterator
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import platformdirs
from rich.console import Console
from rich.progress import Progress
from rich.table import Table


APP_NAME = "pypi-dependents"


@dataclass
class Page:
    """A page of results from the GitHub API."""

    url: str
    link: dict[str, str]
    etag: str
    data: Any
    cached: bool


def save_page_to_cache(page: Page) -> None:
    """Store page in the cache."""
    data = {
        "url": page.url,
        "link": page.link,
        "etag": page.etag,
        "data": page.data,
    }

    digest = hashlib.blake2b(page.url.encode()).hexdigest()
    cachedir = Path(platformdirs.user_cache_dir(APP_NAME))
    cache = cachedir / digest

    cachedir.mkdir(parents=True, exist_ok=True)
    with cache.open(mode="w") as io:
        json.dump(data, io)


def load_page_from_cache(url: str) -> Page | None:
    """Load page from the cache."""
    digest = hashlib.blake2b(url.encode()).hexdigest()
    cachedir = Path(platformdirs.user_cache_dir(APP_NAME))
    cache = cachedir / digest

    if not cache.is_file():
        return None

    with cache.open() as io:
        data = json.load(io)
        return Page(data["url"], data["link"], data["etag"], data["data"], True)


def parse_link_header(response: httpx.Response) -> dict[str, str]:
    """Parse the Link header."""

    def _() -> Iterator[tuple[str, str]]:
        try:
            header = response.headers["Link"]
        except KeyError:
            return

        for field in header.split(","):
            url, rel = field.split(";")
            url = url.strip().removeprefix("<").removesuffix(">")
            rel = rel.strip().removeprefix('rel="').removesuffix('"')
            yield rel, url

    return dict(_())


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


def request_top_pypi(url: str, *, etag: str | None) -> httpx.Response:
    """Request the list of top PyPI packages."""
    headers = {"If-None-Match": etag} if etag else {}
    response = httpx.get(url, headers=headers)

    if response.status_code != httpx.codes.NOT_MODIFIED:
        response.raise_for_status()

    return response


def get_top_pypi_page(*, cache: bool = False) -> Page:
    """Retrieve the page with the top PyPI packages."""
    url = "https://hugovk.github.io/top-pypi-packages/top-pypi-packages-30-days.json"
    page = load_page_from_cache(url)
    etag = page.etag if page else None

    if cache and page:
        return page

    response = request_top_pypi(url, etag=etag)

    if response.status_code == httpx.codes.NOT_MODIFIED:
        assert page is not None  # noqa: S101
    else:
        etag = response.headers["ETag"]
        page = Page(url, {}, etag, response.json(), False)
        save_page_to_cache(page)

    return page


def request_dependents(url: str, *, token: str, etag: str | None) -> httpx.Response:
    """Retrieve dependents from the API."""
    headers = {"If-None-Match": etag} if etag else {}

    response = httpx.get(
        url, headers=headers, params={"per_page": 100, "api_key": token}
    )

    if response.status_code != httpx.codes.NOT_MODIFIED:
        response.raise_for_status()

    return response


def get_dependents_page(url: str, *, token: str, cache: bool = False) -> Page:
    """Retrieve dependents from the cache or the API."""
    page = load_page_from_cache(url)
    etag = page.etag if page else None

    if cache and page:
        return page

    response = request_dependents(url, token=token, etag=etag)

    if response.status_code == httpx.codes.NOT_MODIFIED:
        assert page is not None  # noqa: S101
    else:
        etag = response.headers["ETag"]
        link = parse_link_header(response)
        page = Page(url, link, etag, response.json(), False)
        save_page_to_cache(page)

    return page


@dataclass
class Package:
    """Package data from libraries.io."""

    dependent_repos_count: int
    dependents_count: int
    forks: int
    name: str
    rank: int
    stars: int

    @classmethod
    def parse(cls, result: dict[str, Any]) -> Package:
        """Parse the result for a dependent."""
        return Package(
            int(result["dependent_repos_count"]),
            int(result["dependents_count"]),
            int(result["forks"]),
            result["name"],
            int(result["rank"]),
            int(result["stars"]),
        )


def get_dependents(
    package: str, *, token: str, console: Console, cache: bool = False
) -> Iterator[Package]:
    """Retrieve the dependents for a package."""
    with Progress(console=console, transient=True) as progress:
        task = progress.add_task("Downloading dependents…")
        page = get_dependents_page(
            f"https://libraries.io/api/pypi/{package}/dependents",
            token=token,
            cache=cache,
        )

        for result in page.data:
            yield Package.parse(result)

        while url := page.link.get("next"):
            if last := page.link.get("last"):
                current = parse_page_parameter(url)
                total = parse_page_parameter(last)
                progress.update(task, total=total, completed=current)

            if not page.cached:
                time.sleep(1)

            page = get_dependents_page(url, token=token, cache=cache)

            for result in page.data:
                yield Package.parse(result)


def create_argument_parser() -> argparse.ArgumentParser:
    """Return the command-line parser."""
    parser = argparse.ArgumentParser()
    parser.add_argument("package")
    parser.add_argument("--cache", action="store_true", default=False)
    parser.add_argument("--token")
    return parser


def load_token() -> str | None:
    """Read the token from the cache."""
    cachedir = Path(platformdirs.user_cache_dir(APP_NAME))
    tokencache = cachedir / "token"
    with contextlib.suppress(FileNotFoundError):
        return tokencache.read_text()
    return None


def save_token(token: str) -> None:
    """Store the token in the cache."""
    cachedir = Path(platformdirs.user_cache_dir(APP_NAME))
    tokencache = cachedir / "token"
    tokencache.parent.mkdir(exist_ok=True)
    tokencache.write_text(token)


def find_token(args: argparse.Namespace) -> str | None:
    """Determine the Libraries.io API token."""
    if token := args.token or os.environ.get("LIBRARIES_TOKEN"):
        save_token(token)
        return token

    return load_token()


def sort_packages(
    packages: Iterable[Package],
    *,
    top_pypi: Mapping[str, int],
) -> Iterable[Package]:
    """Sort packages by importance."""
    packages = list({p.name: p for p in packages}.values())
    if not packages:
        return packages

    top = Package(
        name="top",
        dependent_repos_count=max(1, *(p.dependent_repos_count for p in packages)),
        dependents_count=max(1, *(p.dependents_count for p in packages)),
        forks=max(1, *(p.forks for p in packages)),
        rank=max(1, *(p.rank for p in packages)),
        stars=max(1, *(p.stars for p in packages)),
    )

    def key(package: Package) -> float:
        with contextlib.suppress(KeyError):
            return top_pypi[package.name]

        return max(
            package.dependent_repos_count / top.dependent_repos_count,
            package.dependents_count / top.dependents_count,
            package.forks / top.forks,
            package.rank / top.rank,
            package.stars / top.stars,
        )

    return sorted(packages, key=key, reverse=True)


def print_packages(
    packages: Iterable[Package],
    dependency: str,
    *,
    console: Console,
    top_pypi: Mapping[str, int],
) -> None:
    """Print the star dates for a repository."""
    table = Table(title=dependency)
    table.add_column("Name")
    table.add_column("Downloads", justify="right")
    table.add_column("Stars", justify="right")
    table.add_column("Forks", justify="right")
    table.add_column("Rank", justify="right")
    table.add_column("Packages", justify="right")
    table.add_column("Package Repos", justify="right")

    for package in sort_packages(packages, top_pypi=top_pypi):
        downloads = top_pypi.get(package.name, 0)
        table.add_row(
            package.name,
            f"{downloads}",
            f"{package.stars}",
            f"{package.forks}",
            f"{package.rank}",
            f"{package.dependents_count}",
            f"{package.dependent_repos_count}",
        )

    print()
    console.print(table)


def main() -> None:
    """Main."""
    parser = create_argument_parser()
    args = parser.parse_args()
    token = find_token(args)

    if not token:
        raise Exception("use --token or LIBRARIES_TOKEN to specify the API token")

    stdout = Console()
    stderr = Console(stderr=True)
    dependents = get_dependents(
        args.package, token=token, console=stderr, cache=args.cache
    )

    top_pypi = {
        row["project"]: int(row["download_count"])
        for row in get_top_pypi_page(cache=args.cache).data["rows"]
    }
    print_packages(dependents, args.package, console=stdout, top_pypi=top_pypi)
