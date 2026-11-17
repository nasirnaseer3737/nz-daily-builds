# NZ AI Keyword Clusterer

Group SEO keywords into topic clusters — one pillar page per cluster, with a
short content brief for each. Built 2026-11-17 as the daily AI/automation
build.

## What it does

- Reads a CSV of keywords (`keyword`, `search_volume`, `difficulty`).
- Clusters them by topic, so each cluster can become one pillar page with
  supporting pages linking back to it.
- Picks the pillar keyword per cluster (highest search volume, ties broken
  by lowest difficulty), a pillar page title + URL slug, total volume and
  average difficulty.
- Writes three outputs: `clusters.json`, `clusters.csv` (one row per
  keyword, pillar flagged) and `clusters.md` (human-readable report).

## AI vs mock

With `NZ_GEMINI_API_KEY` set, clustering is done by the Gemini API
(`gemini-2.0-flash`, free tier) — it judges search intent and meaning, and
the output is labelled `source: gemini`.

Without a key (or with `--mock`, or if the API call fails) it uses a clearly
labelled **offline mock heuristic**: stemmed-token overlap plus shared
head/tail two-word phrases, merged with a union-find pass. It works, but it
cannot judge meaning the way an LLM can — so set the key for real AI
clustering.

## Setup

```bash
export NZ_GEMINI_API_KEY="your-gemini-api-key"   # free tier: Google AI Studio
```

The key is read only from the environment. It is never hardcoded, never
written to any output file, and never committed.

## Usage

```bash
python3 keyword_clusterer.py --input sample_keywords.csv --out-dir out
python3 keyword_clusterer.py -i keywords.csv -o out --max-clusters 8
python3 keyword_clusterer.py -i keywords.csv -o out --mock   # offline mode
```

## Example output (mock mode, 14 sample keywords)

| # | Cluster | Pillar keyword | Keywords | Total volume |
|---|---------|---------------|----------|--------------|
| 1 | seo plugin | wordpress seo plugin | 3 | 16,400 |
| 2 | generation lead | ai lead generation tools | 3 | 10,700 |
| 3 | seo math | yoast seo vs rank math | 2 | 8,500 |
| 4 | seo plumb | local seo for plumbers | 2 | 4,200 |
| 5 | clinic design | dental clinic website design | 1 | 2,200 |
| 6 | clinic market | whatsapp marketing for clinics | 1 | 1,500 |
| 7 | design cost | dentist website design cost | 1 | 1,300 |
| 8 | rank website | how to rank a plumbing website | 1 | 900 |

(Exact grouping depends on `--min-similarity`; Gemini mode may group
differently — e.g. it can merge the two SEO-plugin groups by intent.)

## Files

- `keyword_clusterer.py` — the tool (Python 3, standard library only)
- `test_keyword_clusterer.py` — 22 unit tests
- `sample_keywords.csv` — 14 sample keywords to try it on
- `out/` — demo output generated from the sample file

## Tests

```bash
python3 -m py_compile keyword_clusterer.py test_keyword_clusterer.py
python3 -m unittest -v test_keyword_clusterer.py
```

22/22 tests pass. The demo run clusters the 14 sample keywords into 8
clusters in mock mode.
