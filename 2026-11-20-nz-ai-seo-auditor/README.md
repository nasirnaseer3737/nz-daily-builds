# NZ AI SEO Auditor

AI-powered on-page SEO auditor — a Python (stdlib only) CLI that audits HTML
pages against on-page SEO best practice and suggests concrete fixes.

## What it checks

| Check | Pass rule |
|---|---|
| Title tag | Present, 30–60 chars |
| Meta description | Present, 120–160 chars |
| H1 heading | Exactly one H1 |
| Heading order | No skipped levels (H1 → H2 → H3) |
| Image alt text | Every `<img>` has non-empty alt |
| Canonical URL | Canonical link tag present |
| Social tags | Open Graph + Twitter Card present |
| Schema.org markup | JSON-LD structured data present |
| Content length | 300+ words of body text |
| Links | No placeholder links (`#`, `javascript:`) |
| Readability | Flesch reading-ease 60+ |
| Target keyword | In title, H1 and body (with density) |

Each check is pass / warn / fail and rolls up into a **0–100 score** with a
grade (A/B/C/D/F).

## AI fix suggestions

For every failed or warning check the tool asks **Gemini** (`gemini-2.0-flash`)
for one short, concrete fix. Set your key first:

```bash
export NZ_GEMINI_API_KEY="your-gemini-api-key"
```

No key set? The tool uses a clearly labelled **offline MOCK fallback** that
builds the same suggestions from the rule results — it never pretends to be
AI output. If the Gemini call fails (bad key, no network), it falls back to
the same labelled mock instead of crashing.

API keys are **never** hardcoded or committed — they are read only from the
`NZ_GEMINI_API_KEY` environment variable.

## Usage

```bash
# Audit local HTML files
python3 seo_auditor.py page1.html page2.html --keyword "wordpress developer"

# Audit live URLs
python3 seo_auditor.py https://example.com --keyword "plumber chicago"

# Audit a whole folder of HTML files
python3 seo_auditor.py --folder sample_pages --keyword "seo audit"

# Audit a list of files/URLs, one per line
python3 seo_auditor.py --list pages.txt --keyword "local seo"
```

Output goes to `audit-output/` by default (`--out` to change it):

- `report.json` — machine-readable results for every page
- `report.md` — human-readable report with scores and fix suggestions

## Demo

```bash
python3 seo_auditor.py --folder sample_pages --keyword "WordPress developer" --out demo
```

Sample pages included:

- `sample_pages/good-page.html` — a well-optimised page (scores 92/100, grade A)
- `sample_pages/bad-page.html` — a page with typical SEO mistakes (scores low, grade D/F)

Demo output (mock mode, no API key):

- `good-page.html`: 92/100 (Grade A) — 0 failed, 1 warning
- `bad-page.html`: 32/100 (Grade F) — 3 failed, 8 warnings

## Tests

```bash
python3 -m unittest test_seo_auditor.py -v
```

21/21 tests pass (offline, no API key needed). Tests cover HTML parsing,
every audit check, scoring, keyword stats, readability, the labelled mock
fallback, Gemini-failure fallback, and end-to-end report generation.

## Requirements

- Python 3.8+ — standard library only, no packages to install.
