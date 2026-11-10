# nz-meta-tags

A zero-dependency Node.js CLI that generates SEO meta tags for a web page —
title, description, canonical link, Open Graph, Twitter Card and JSON-LD
(Schema.org) — from flags or a JSON file. It also checks an existing page's
meta tags and warns about titles/descriptions that Google will truncate.

Built 2026-11-10 as part of [NZ Daily Builds](https://github.com/nasirnaseer3737/nz-daily-builds).

## Usage

Generate tags for a page:

```bash
node meta-tags.js --title "WordPress Web Design Services" \
  --description "Affordable WordPress websites for small businesses." \
  --url "https://nzgenix.digital/services/" \
  --image "https://nzgenix.digital/og.jpg" \
  --site-name "NZGenix"
```

Or load the same fields from a JSON file (see `example.json`):

```bash
node meta-tags.js --input example.json
node meta-tags.js --input example.json --out tags.html   # write to a file
```

Check an existing page's meta tags:

```bash
node meta-tags.js --check existing-page.html
```

## Options

| Flag | What it does |
|------|--------------|
| `--title` | Page title — kept to 60 chars (Google's display limit) |
| `--description` | Meta description — kept to 160 chars |
| `--url` | Canonical URL of the page |
| `--image` | Absolute image URL for Open Graph / Twitter previews |
| `--type` | `website` (default) or `article` |
| `--site-name` | Site name for `og:site_name` |
| `--author` | Author name (article only) |
| `--date` | Publication date, e.g. `2026-11-10` (article only) |
| `--input` | JSON file with the same fields |
| `--out` | Write tags to a file instead of stdout |
| `--check` | Validate an HTML file's existing meta tags, exit 1 if problems |

## What it checks

- Title over 60 characters — Google truncates it in search results.
- Description over 160 characters, or under 120 (too thin to rank well).
- Missing canonical URL, missing `og:image` (social shares show no preview).
- Non-absolute URLs for `--url` / `--image`.

## Tests

```bash
node --test test.js   # 11 tests, no dependencies
```

Requires Node.js 18+ (uses only the standard library).
