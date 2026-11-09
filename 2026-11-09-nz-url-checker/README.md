# NZ URL Checker

Check a list of URLs and report each one's HTTP status, redirect chain and
response time — handy after a site move, a redesign, or a hosting change, when
you want to know which pages still answer and which are broken.

## What it does

- Reads URLs from a text file (one per line, `#` comments skipped) or straight
  from the command line; bare domains like `example.com` get `https://` added.
- Follows redirects and reports the final URL and status code.
- Times every request and prints a plain-text summary table.
- Optionally writes a CSV report (`--output report.csv`) for spreadsheets.
- Exit code `0` when every URL is OK, `1` when any URL is broken or errors.

## Usage

```bash
python3 nz_url_checker.py urls.txt
python3 nz_url_checker.py https://example.com https://nzgenix.digital
python3 nz_url_checker.py urls.txt --output report.csv --timeout 10
```

Example output:

```
STATUS    CODE      MS  URL
------------------------------------------------------------------------------
OK        200      412  https://example.com
REDIRECT  200      380  https://nzgenix.digital
BROKEN    404      290  https://example.com/old-page
------------------------------------------------------------------------------
Checked 3: 2 OK, 1 broken, 0 errors
```

## Files

- `nz_url_checker.py` — the checker (Python 3, standard library only)
- `test_nz_url_checker.py` — 10 unit tests against a local HTTP server
- `urls.example.txt` — example input file

## Tests

```bash
python3 -m unittest test_nz_url_checker -v
```

No third-party packages are needed — Python 3.8+ is enough.
