# NZ AI Outreach Email Drafter

Turns a CSV of prospects into **personalised, ready-to-send outreach emails** —
one draft per prospect, with a **10-minute paced send queue** (one mail, then a
10-minute gap — no batching).

## What it does

1. Reads prospects from a CSV: `name, business, niche, city, email, website,
   pain_point, consent`.
2. **TCPA gate** — anyone without explicit consent (`yes` / `opt-in`) is
   flagged `DO-NOT-CONTACT` and never drafted.
3. **Dedupe** — anyone already in `sent_history.json` is skipped, so nobody
   gets the same outreach twice.
4. **Drafts** 3 subject-line options + a personalised body per prospect:
   - With `NZ_GEMINI_API_KEY` set, drafts are written by the **Gemini API**
     (free tier) — genuinely AI-written.
   - Without a key, a clearly labelled **MOCK** template fallback is used so
     the tool still works offline. Mock drafts are still personalised from
     the prospect's own fields (name, business, city, niche, pain point).
5. Writes `drafts.csv` (one row per draft) and `queue.json` — a send queue
   with one slot every N minutes (default 10), so the sender works through
   the queue one mail at a time.

## Run it

```bash
# Mock mode (no key needed — drafts are labelled "mock")
python3 outreach_drafter.py --input sample_prospects.csv --out out/

# Real AI drafts (Gemini free tier)
export NZ_GEMINI_API_KEY="your-gemini-api-key"
python3 outreach_drafter.py --input sample_prospects.csv --out out/

# Options
python3 outreach_drafter.py --input prospects.csv --out out/ \
    --start "2026-11-15 14:00" --gap-minutes 10 --limit 5 \
    --history sent_history.json
```

| Flag | Default | What it does |
|------|---------|--------------|
| `--input` | — (required) | Prospects CSV |
| `--out` | `out/` | Folder for `drafts.csv` + `queue.json` |
| `--history` | `sent_history.json` | Sent-history JSON (`{"email": "date"}`); missing file = empty |
| `--start` | now | First send slot, `"YYYY-MM-DD HH:MM"` |
| `--gap-minutes` | `10` | Minutes between send slots |
| `--limit` | `0` (all) | Max drafts to generate |

## API key setup

Get a free Gemini key at <https://aistudio.google.com/app/apikey> and set it
as an environment variable — **never hardcode or commit a key**:

```bash
export NZ_GEMINI_API_KEY="your-gemini-api-key"
```

See `.env.example`.

## Sample run

`sample_prospects.csv` has 5 prospects: 4 get drafted (Mike, Sara, Ana,
Priya) and Tom is skipped (no consent — DO-NOT-CONTACT). In the tests, Ana
is additionally skipped because she is already in the sent history.

## Tests

```bash
python3 -m unittest -v test_outreach_drafter
# 16 tests — loading, consent gate, mock drafting, queue pacing, end-to-end run
```

Python standard library only — no dependencies to install.
