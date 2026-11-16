# nz-ai-social-scheduler

AI social post drafter + scheduler — turn a CSV of topics into platform-ready
posts (LinkedIn / X / Facebook) and a timed posting schedule.

## What it does

1. Reads a topics CSV (`topic, platforms, tone, link, hashtags`).
2. Drafts one post per topic × platform:
   - **With `NZ_GEMINI_API_KEY` set** — calls the Gemini API (free tier,
     model `gemini-2.0-flash`) for a real AI-written post.
   - **Without a key (or with `--mock`)** — uses a clearly labelled offline
     MOCK generator, so the scheduler, limits and outputs work without any
     API key. Mock posts are labelled `mock` in every output.
3. Enforces platform rules: X ≤ 280 characters, LinkedIn ≤ 3000,
   Facebook ≤ 2000, with per-platform hashtag caps (X 2, Facebook 3,
   LinkedIn 5). Long posts are truncated with hashtags preserved.
4. Slots posts into a schedule (default: one post every 4 hours, starting
   tomorrow 14:00 Asia/Karachi — the usual daily-post time).
5. Dedupes via a history file (`posted.json`): a topic already scheduled or
   posted for a platform is skipped, so the same post is never drafted twice.
6. Writes three outputs: `schedule.json`, `drafts.md` (human-readable, for
   review before posting) and `posts.csv`.

## Usage

```bash
# Draft + schedule from a topics CSV (mock mode — no key needed)
python3 social_scheduler.py sample_topics.csv --out out/ --mock

# Real AI drafts (free Gemini key)
export NZ_GEMINI_API_KEY=<redacted>
python3 social_scheduler.py sample_topics.csv --out out/

# Custom start time and spacing
python3 social_scheduler.py topics.csv --out out/ \
    --start 2026-11-17T14:00 --gap-hours 6

# Only the first 3 topics
python3 social_scheduler.py topics.csv --out out/ --limit 3
```

Options: `--history posted.json` (dedupe file, default `posted.json`),
`--start YYYY-MM-DD[THH:MM]` (PKT, default tomorrow 14:00),
`--gap-hours N` (default 4), `--limit N`, `--mock` (force mock mode).

## Topics CSV format

| column | required | example |
|--------|----------|---------|
| `topic` | yes | `WordPress 7.2 is coming — check plugin compatibility` |
| `platforms` | no (default `linkedin`) | `linkedin; x` or `linkedin, facebook` |
| `tone` | no (default `professional`) | `professional`, `friendly`, `bold`, `educational`, `funny` |
| `link` | no | `https://nzgenix.digital` |
| `hashtags` | no | `WordPress, SEO` |

## API key setup

Get a free key at https://aistudio.google.com/app/apikey, then:

```bash
export NZ_GEMINI_API_KEY=<redacted>
```

The key is read from the environment only — it is never hardcoded or
committed. If the API call fails, the tool falls back to the labelled mock
generator for that post instead of crashing.

## Files

- `social_scheduler.py` — the tool (Python 3 stdlib only, ~430 lines)
- `test_social_scheduler.py` — 21 offline tests (no API calls)
- `sample_topics.csv` — 5 example topics
- `out/` — demo output from the sample run (schedule.json, drafts.md, posts.csv)

## Tests

```bash
python3 -m unittest test_social_scheduler -v
# 21 tests: CSV parsing, platform limits, mock generation, scheduling slots,
# dedupe history, and the full mock pipeline with all three outputs.
```

## Demo result

Running the sample topics in mock mode drafts **7 posts** (5 topics across
LinkedIn/X/Facebook) scheduled **2026-11-17 14:00 PKT → 2026-11-18 14:00 PKT**,
all within platform limits, all labelled MOCK.
