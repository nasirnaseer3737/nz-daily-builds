#!/usr/bin/env python3
"""nz-sitemap-generator — build XML sitemaps from a URL list or a folder of HTML files.

Pure Python standard library. No dependencies, no network access needed.

Two input modes:
  1. URL list:  one URL per line (lines starting with ``#`` are ignored).
  2. Folder scan: walk a folder of ``.html`` files and turn each file into a
     URL under a base URL (``index.html`` maps to its directory URL).

Features:
  * <lastmod> from file mtime (folder mode) or an optional CSV column
    (URL-list mode: ``url,lastmod``).
  * <priority> derived from URL depth (homepage 1.0, deeper pages lower).
  * <changefreq> heuristic: homepage daily, blog-ish paths weekly,
    everything else monthly.
  * Splits automatically into several sitemap files plus a sitemap index
    when a sitemap would exceed 50,000 URLs or ~50 MB (the sitemap.org limits).
  * Validates every URL (scheme, host) and every lastmod date before writing.

Usage:
    python3 sitemap.py urls.txt --out sitemap.xml
    python3 sitemap.py urls.txt --out sitemaps/ --split
    python3 sitemap.py --scan ./public --base https://example.com --out sitemap.xml
    python3 sitemap.py urls.txt --out sitemap.xml --no-lastmod --gzip

Exit codes: 0 = sitemap(s) written, 1 = usage/validation error, 2 = no URLs found.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import gzip
import os
import re
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

MAX_URLS_PER_SITEMAP = 50_000
MAX_BYTES_PER_SITEMAP = 50 * 1024 * 1024  # 50 MB, per sitemap.org
SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"

URL_RE = re.compile(r"^https?://[^\s/$.?#].[^\s]*$", re.IGNORECASE)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
BLOG_HINT = re.compile(r"/(blog|news|post|article)s?(/|$)", re.IGNORECASE)


class SitemapError(ValueError):
    """Raised when input data cannot be turned into a valid sitemap."""


def validate_url(url: str) -> str:
    """Return a normalised URL or raise SitemapError."""
    url = url.strip()
    if not URL_RE.match(url):
        raise SitemapError(f"not a valid http(s) URL: {url!r}")
    parsed = urllib.parse.urlparse(url)
    if not parsed.netloc or "." not in parsed.netloc:
        raise SitemapError(f"URL has no usable host: {url!r}")
    # Drop fragments; sitemaps must not contain them.
    return urllib.parse.urlunsplit(
        (parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or "/",
         parsed.query, "")
    )


def validate_lastmod(value: str) -> str:
    """Return a YYYY-MM-DD date or raise SitemapError."""
    value = value.strip()
    if not DATE_RE.match(value):
        raise SitemapError(f"lastmod must be YYYY-MM-DD, got {value!r}")
    try:
        _dt.date.fromisoformat(value)
    except ValueError:
        raise SitemapError(f"lastmod is not a real date: {value!r}")
    if value > _dt.date.today().isoformat():
        raise SitemapError(f"lastmod is in the future: {value!r}")
    return value


def priority_for(url: str) -> str:
    """Priority from URL depth: homepage 1.0, each extra segment -0.1 (min 0.3)."""
    path = urllib.parse.urlparse(url).path.strip("/")
    depth = 0 if not path else len(path.split("/"))
    return f"{max(0.3, 1.0 - depth * 0.1):.1f}"


def changefreq_for(url: str) -> str:
    """Changefreq heuristic from the URL path."""
    path = urllib.parse.urlparse(url).path
    if path in ("", "/"):
        return "daily"
    if BLOG_HINT.search(path):
        return "weekly"
    return "monthly"


def read_url_list(path: Path) -> list[dict]:
    """Parse a ``url[,lastmod]`` text file into entry dicts."""
    entries: list[dict] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(",", 1)]
        try:
            url = validate_url(parts[0])
        except SitemapError as exc:
            raise SitemapError(f"{path}:{lineno}: {exc}") from exc
        entry: dict = {"loc": url}
        if len(parts) == 2 and parts[1]:
            try:
                entry["lastmod"] = validate_lastmod(parts[1])
            except SitemapError as exc:
                raise SitemapError(f"{path}:{lineno}: {exc}") from exc
        entries.append(entry)
    return dedupe(entries)


def dedupe(entries: list[dict]) -> list[dict]:
    """Drop duplicate URLs, keeping the first occurrence, preserving order."""
    seen: set[str] = set()
    out: list[dict] = []
    for entry in entries:
        if entry["loc"] not in seen:
            seen.add(entry["loc"])
            out.append(entry)
    return out


def scan_folder(root: Path, base_url: str) -> list[dict]:
    """Turn every .html file under *root* into a sitemap entry."""
    base = validate_url(base_url).rstrip("/")
    entries: list[dict] = []
    for html in sorted(root.rglob("*.html")):
        rel = html.relative_to(root).as_posix()
        if rel.endswith("index.html"):
            rel = rel[: -len("index.html")]
        url = base + "/" + rel
        mtime = _dt.datetime.fromtimestamp(
            html.stat().st_mtime, tz=_dt.timezone.utc
        ).date().isoformat()
        entries.append({"loc": validate_url(url), "lastmod": mtime})
    return dedupe(sorted(entries, key=lambda e: e["loc"]))


def build_sitemap_xml(entries: list[dict], include_lastmod: bool = True) -> bytes:
    """Serialise one sitemap document (<= MAX_URLS_PER_SITEMAP entries)."""
    if len(entries) > MAX_URLS_PER_SITEMAP:
        raise SitemapError(
            f"too many URLs for one sitemap: {len(entries)} > {MAX_URLS_PER_SITEMAP}"
        )
    urlset = ET.Element("urlset", {"xmlns": SITEMAP_NS})
    for entry in entries:
        url_el = ET.SubElement(urlset, "url")
        loc = ET.SubElement(url_el, "loc")
        loc.text = entry["loc"]
        if include_lastmod and entry.get("lastmod"):
            lastmod = ET.SubElement(url_el, "lastmod")
            lastmod.text = entry["lastmod"]
        changefreq = ET.SubElement(url_el, "changefreq")
        changefreq.text = changefreq_for(entry["loc"])
        priority = ET.SubElement(url_el, "priority")
        priority.text = priority_for(entry["loc"])
    ET.indent(urlset, space="  ")
    return ET.tostring(urlset, encoding="utf-8", xml_declaration=True) + b"\n"


def build_index_xml(filenames: list[str], base_url: str,
                    lastmod: str | None = None) -> bytes:
    """Serialise a sitemap index pointing at *filenames* under *base_url*."""
    index = ET.Element("sitemapindex", {"xmlns": SITEMAP_NS})
    for name in filenames:
        sm = ET.SubElement(index, "sitemap")
        loc = ET.SubElement(sm, "loc")
        loc.text = validate_url(base_url.rstrip("/") + "/" + name)
        if lastmod:
            lm = ET.SubElement(sm, "lastmod")
            lm.text = lastmod
    ET.indent(index, space="  ")
    return ET.tostring(index, encoding="utf-8", xml_declaration=True) + b"\n"


def split_entries(entries: list[dict]) -> list[list[dict]]:
    """Chunk entries so each chunk fits the sitemap size limits."""
    chunks: list[list[dict]] = []
    current: list[dict] = []
    current_bytes = 0
    for entry in entries:
        # ~180 bytes per <url> block is a safe over-estimate for the check.
        est = len(entry["loc"].encode("utf-8")) + 180
        if (current and (len(current) >= MAX_URLS_PER_SITEMAP
                         or current_bytes + est > MAX_BYTES_PER_SITEMAP)):
            chunks.append(current)
            current, current_bytes = [], 0
        current.append(entry)
        current_bytes += est
    if current:
        chunks.append(current)
    return chunks


def write_file(path: Path, data: bytes, use_gzip: bool) -> Path:
    """Write *data* to *path*, optionally gzipped (adds .gz to the name)."""
    if use_gzip:
        path = path.with_suffix(path.suffix + ".gz")
        with gzip.open(path, "wb") as fh:
            fh.write(data)
    else:
        path.write_bytes(data)
    return path


def generate(entries: list[dict], out: Path, *, include_lastmod: bool = True,
             use_gzip: bool = False, index_base_url: str | None = None) -> list[Path]:
    """Write sitemap file(s) for *entries*; return the files written."""
    if not entries:
        raise SitemapError("no URLs to write — input produced zero entries")
    chunks = split_entries(entries)
    written: list[Path] = []
    if len(chunks) == 1 and out.suffix == ".xml":
        out.parent.mkdir(parents=True, exist_ok=True)
        written.append(write_file(out, build_sitemap_xml(
            chunks[0], include_lastmod), use_gzip))
        return written
    # Multi-file mode: out is a directory (or a stem for the file names).
    out_dir = out if out.suffix != ".xml" else out.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = out.stem if out.suffix == ".xml" else "sitemap"
    names: list[str] = []
    for i, chunk in enumerate(chunks, 1):
        name = f"{stem}-{i}.xml" if len(chunks) > 1 else f"{stem}.xml"
        names.append(name)
        written.append(write_file(out_dir / name,
                                  build_sitemap_xml(chunk, include_lastmod),
                                  use_gzip))
    if len(chunks) > 1:
        if not index_base_url:
            raise SitemapError(
                "split sitemap needs --index-base-url so the index can "
                "point at the parts (e.g. https://example.com/)")
        today = _dt.date.today().isoformat()
        index_names = [n + (".gz" if use_gzip else "") for n in names]
        index_path = out_dir / "sitemap-index.xml"
        index_path.write_bytes(build_index_xml(index_names, index_base_url, today))
        written.append(index_path)
    return written


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate XML sitemap(s) from a URL list or an HTML folder.")
    parser.add_argument("input", nargs="?", help="URL list file (one URL per line)")
    parser.add_argument("--scan", metavar="DIR",
                        help="scan a folder of .html files instead of a URL list")
    parser.add_argument("--base", metavar="URL",
                        help="base URL for --scan mode (required with --scan)")
    parser.add_argument("--out", required=True, metavar="PATH",
                        help="output .xml file, or a directory when splitting")
    parser.add_argument("--index-base-url", metavar="URL",
                        help="public base URL for the sitemap index (split mode)")
    parser.add_argument("--no-lastmod", action="store_true",
                        help="omit <lastmod> from the output")
    parser.add_argument("--gzip", action="store_true",
                        help="also write .gz versions of the sitemaps")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.scan:
            if not args.base:
                raise SitemapError("--scan needs --base, e.g. --base https://example.com")
            root = Path(args.scan)
            if not root.is_dir():
                raise SitemapError(f"not a directory: {args.scan}")
            entries = scan_folder(root, args.base)
            source = f"folder {args.scan}"
        else:
            if not args.input:
                raise SitemapError("give a URL list file or use --scan DIR --base URL")
            entries = read_url_list(Path(args.input))
            source = f"file {args.input}"
        written = generate(entries, Path(args.out),
                           include_lastmod=not args.no_lastmod,
                           use_gzip=args.gzip,
                           index_base_url=args.index_base_url)
    except SitemapError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"error: cannot write output: {exc}", file=sys.stderr)
        return 1
    if not entries:
        print("error: no URLs found in input", file=sys.stderr)
        return 2
    print(f"{len(entries)} URLs from {source} -> {len(written)} file(s):")
    for path in written:
        print(f"  {path} ({path.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
