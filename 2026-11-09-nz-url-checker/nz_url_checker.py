#!/usr/bin/env python3
"""NZ URL Checker — check a list of URLs and report status, redirects and speed.

Usage:
    python3 nz_url_checker.py urls.txt
    python3 nz_url_checker.py https://example.com https://nzgenix.digital
    python3 nz_url_checker.py urls.txt --output report.csv --timeout 10

Input file: one URL per line; lines starting with # are comments.
Output: a table on stdout, plus an optional CSV report (--output).

Only the Python standard library is used — no pip installs needed.
"""

import argparse
import csv
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field


@dataclass
class UrlResult:
    """One checked URL and what the server answered."""

    url: str
    final_url: str = ""
    status: int | None = None
    error: str = ""
    elapsed_ms: int = 0
    redirects: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when the final response was a 2xx status."""
        return self.status is not None and 200 <= self.status < 300

    @property
    def summary(self) -> str:
        """One-line human summary: OK, REDIRECT, BROKEN or ERROR."""
        if self.error:
            return "ERROR"
        if self.status is None:
            return "UNKNOWN"
        if 200 <= self.status < 300:
            return "REDIRECT" if self.redirects else "OK"
        if 300 <= self.status < 400:
            return "REDIRECT"
        return "BROKEN"


def normalise_url(raw: str) -> str:
    """Add https:// when the user gave a bare domain like example.com."""
    raw = raw.strip()
    if not raw:
        return raw
    if "://" not in raw:
        return "https://" + raw
    return raw


def read_url_list(path: str) -> list:
    """Read URLs from a text file, skipping blanks and # comments."""
    urls = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            urls.append(normalise_url(line))
    return urls


def check_url(url: str, timeout: float = 10.0) -> UrlResult:
    """Fetch one URL (following redirects) and time the request."""
    result = UrlResult(url=url)
    request = urllib.request.Request(
        url, headers={"User-Agent": "NZ-URL-Checker/1.0 (+https://nzgenix.digital)"}
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result.status = response.status
            result.final_url = response.geturl()
            if result.final_url != url:
                result.redirects.append(result.final_url)
    except urllib.error.HTTPError as exc:
        # HTTPError still carries the status code (404, 500, ...).
        result.status = exc.code
        result.final_url = exc.geturl()
        if result.final_url and result.final_url != url:
            result.redirects.append(result.final_url)
    except urllib.error.URLError as exc:
        result.error = str(exc.reason) if exc.reason else str(exc)
    except (TimeoutError, OSError) as exc:
        result.error = str(exc)
    finally:
        result.elapsed_ms = int((time.monotonic() - started) * 1000)
    return result


def check_all(urls: list, timeout: float = 10.0) -> list:
    """Check every URL in order and return the results."""
    return [check_url(url, timeout=timeout) for url in urls]


def print_table(results: list) -> None:
    """Print a plain-text summary table to stdout."""
    print(f"{'STATUS':<9} {'CODE':<5} {'MS':>6}  URL")
    print("-" * 78)
    for item in results:
        code = str(item.status) if item.status is not None else "-"
        shown = item.final_url if item.final_url and item.final_url != item.url else item.url
        note = f" -> {item.final_url}" if item.redirects else ""
        detail = item.error if item.error else ""
        print(f"{item.summary:<9} {code:<5} {item.elapsed_ms:>6}  {shown}{note} {detail}".rstrip())
    print("-" * 78)
    total = len(results)
    ok_count = sum(1 for item in results if item.ok)
    broken = [item for item in results if item.summary == "BROKEN"]
    errors = [item for item in results if item.summary == "ERROR"]
    print(f"Checked {total}: {ok_count} OK, {len(broken)} broken, {len(errors)} errors")


def write_csv(results: list, path: str) -> None:
    """Write the full results (one row per URL) to a CSV file."""
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["url", "final_url", "status", "summary", "elapsed_ms", "error"])
        for item in results:
            writer.writerow(
                [item.url, item.final_url, item.status or "", item.summary,
                 item.elapsed_ms, item.error]
            )


def parse_args(argv: list | None = None) -> argparse.Namespace:
    """Parse the command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Check a list of URLs and report status, redirects and speed."
    )
    parser.add_argument(
        "inputs", nargs="+",
        help="URL(s) to check, or a .txt file with one URL per line",
    )
    parser.add_argument(
        "--timeout", type=float, default=10.0,
        help="seconds to wait per URL (default 10)",
    )
    parser.add_argument(
        "--output", metavar="FILE",
        help="also write results to this CSV file",
    )
    return parser.parse_args(argv)


def collect_urls(inputs: list) -> list:
    """Expand inputs: .txt files become their URL lists, the rest are URLs."""
    urls = []
    for value in inputs:
        if value.endswith(".txt"):
            urls.extend(read_url_list(value))
        else:
            urls.append(normalise_url(value))
    # Keep order, drop duplicates.
    seen = set()
    unique = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            unique.append(url)
    return unique


def main(argv: list | None = None) -> int:
    """Entry point: parse args, check URLs, print the table, exit 0/1."""
    args = parse_args(argv)
    urls = collect_urls(args.inputs)
    if not urls:
        print("No URLs to check.", file=sys.stderr)
        return 2
    results = check_all(urls, timeout=args.timeout)
    print_table(results)
    if args.output:
        write_csv(results, args.output)
        print(f"Report written to {args.output}")
    return 0 if all(item.ok for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
