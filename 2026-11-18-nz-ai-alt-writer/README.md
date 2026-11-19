# nz-ai-alt-writer — AI image alt-text writer

A Python stdlib CLI that writes descriptive, SEO-friendly `alt` text for
every image on a website — one of the most commonly missing on-page SEO
items for local business sites.

## What it does

- Scans a folder of images (`.jpg`, `.png`, `.webp`, `.gif`, `.svg`, `.avif`)
  or a CSV with an `image` column (paths or URLs).
- Generates one alt text per image:
  - **AI mode** — Google Gemini (`gemini-2.0-flash`) via the
    `NZ_GEMINI_API_KEY` environment variable.
  - **Mock mode** — when no key is set (or with `--mock`), a clearly
    labelled offline fallback derives alt text from the image filename.
    Mock rows are tagged `mock` in every output and are never presented
    as AI output.
- Enforces alt-text rules in both modes: max 125 characters (configurable),
  never starts with "image of / photo of", sentence case, single line.
- Decorative images (`--decorative logo.svg,divider.png`) get an empty alt
  (`""`) — the correct accessible choice.
- Dedupes via `done.json` history: re-runs skip already-written images
  unless `--force` is passed.
- `--check existing-alts.csv` audits an existing alt-text CSV and reports
  empty, too-long, duplicated, or "image of"-prefixed rows.

## Outputs (into `--out`, default `alt-output/`)

| File | Contents |
|------|----------|
| `alt-text.csv` | `image, alt, source, chars` — one row per image |
| `alt-text.json` | Structured results + run summary |
| `alt-text.md` | Human-readable report |
| `done.json` | History of already-written images |

## Usage

```bash
# Folder of images, mock fallback (no key needed)
python3 alt_writer.py --images ./images --out ./alt-output

# CSV of image paths/URLs + keyword hint
python3 alt_writer.py --images images.csv --keyword "plumbing services"

# Real AI mode (needs the key below)
export NZ_GEMINI_API_KEY="your-gemini-api-key"
python3 alt_writer.py --images ./images

# Decorative images get empty alt; rewrite everything
python3 alt_writer.py --images ./images --decorative logo.svg,divider.png --force

# Audit existing alt text instead of generating
python3 alt_writer.py --check alt-text.csv
```

## API key setup

Get a free Gemini key at https://aistudio.google.com/app/apikey, then:

```bash
export NZ_GEMINI_API_KEY="your-key-here"
```

The key is read **only** from the environment — it is never hardcoded,
never written to any output file, and never committed.

## Tests

```bash
python3 -m py_compile alt_writer.py test_alt_writer.py
python3 -m unittest test_alt_writer -v
```

23 tests, mock/offline only — no API key or network needed (one test checks
that a bad key fails gracefully).

## Demo

`demo/` contains sample image filenames; run in mock mode:

```bash
python3 alt_writer.py --images demo --keyword "home services" --out demo-output
```
