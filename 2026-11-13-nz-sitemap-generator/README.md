# nz-sitemap-generator

Generate XML sitemaps from a URL list or a folder of HTML files — pure Python
standard library, no dependencies, no network needed.

## What it does

- Reads a URL list (`url[,lastmod]` per line) or scans a folder of `.html`
  files and turns each file into a URL under a base URL (`index.html` maps
  to its directory URL).
- Writes a standards-compliant `sitemap.xml` (`sitemap.org`):
  `<loc>`, `<lastmod>`, `<changefreq>`, `<priority>`.
- `<lastmod>` comes from file mtime (folder mode) or the optional CSV
  column (URL-list mode); dates are validated (real `YYYY-MM-DD`, never
  in the future).
- `<priority>` is derived from URL depth (homepage `1.0`, deeper pages
  lower, minimum `0.3`); `<changefreq>` is a heuristic (homepage daily,
  blog/news weekly, everything else monthly).
- Splits automatically into several sitemap files plus a `sitemap-index.xml`
  when a sitemap would exceed 50,000 URLs or ~50 MB.
- Validates every URL (http/https, real host, fragments dropped) and
  reports the exact line number of bad input.

## Usage

```bash
# From a URL list
python3 sitemap.py sample-urls.txt --out sitemap.xml

# From a folder of HTML files (e.g. a static site build)
python3 sitemap.py --scan ./public --base https://example.com --out sitemap.xml

# Split a huge list and write a sitemap index (needs the public base URL)
python3 sitemap.py big-list.txt --out sitemaps/ --index-base-url https://example.com/

# Omit <lastmod>, or also write .gz versions
python3 sitemap.py sample-urls.txt --out sitemap.xml --no-lastmod --gzip
```

Exit codes: `0` = sitemap(s) written, `1` = usage/validation error,
`2` = no URLs found.

## Files

| File | What it is |
|------|-----------|
| `sitemap.py` | The generator (~300 lines) |
| `test_sitemap.py` | 21 unit tests (stdlib `unittest`) |
| `sample-urls.txt` | Example URL list to try it with |

## Tests

```bash
python3 -m unittest -v test_sitemap
```

## Part of

[NZ Daily Builds](https://github.com/nasirnaseer3737/nz-daily-builds) —
one small, real, working build every day.
