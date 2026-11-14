# NZ AI Lead Scorer

**Daily build — 2026-11-14** · [nz-daily-builds](https://github.com/nasirnaseer3737/nz-daily-builds)

An AI-powered lead scorer for outreach: feed it a CSV of leads and it
ranks them 0–100 so you call the best leads first, with a one-line AI
outreach angle per lead.

## What it does

1. **Rule-based scoring (offline, always runs)** — up to 100 points:
   business vs. free email domain, reachable phone, website, company
   size, industry fit (dental, plumbing, real estate, SaaS, legal…),
   lead source (referral beats scraped list), budget signal, and TCPA
   consent (+5).
2. **AI outreach angle (optional, real API)** — with a Gemini key set,
   each lead's top signals go to Google Gemini (`gemini-2.0-flash`,
   free tier) which returns a one-line pitch angle. Without a key it
   runs in clearly labelled **MOCK mode** with a deterministic template
   angle — it never pretends mock text came from a model.
3. **Consent safety** — leads without TCPA consent are scored but
   flagged `DO-NOT-CONTACT` and excluded from the outreach ranking.
4. **Output** — a scored CSV (same rows + `score`, `grade`, `reasons`,
   `ai_angle`, `contact_ok`) sorted best-first, plus a console summary
   with grade counts and the top contactable leads.

Grades: **A** 80+, **B** 60–79, **C** 40–59, **D** under 40.

## Run it

```bash
# Score the bundled sample (mock mode, no key needed)
python3 lead_scorer.py --demo

# Score your own leads
python3 lead_scorer.py leads.csv --out scored.csv --top 10
```

Input CSV columns: `name, email, phone, company, website, industry,
employees, source, budget, consent` (see `sample_leads.csv`).

## AI key setup (optional)

```bash
export NZ_GEMINI_API_KEY="your-gemini-api-key"   # free tier: aistudio.google.com
python3 lead_scorer.py leads.csv
```

The key is read from the environment only — never hardcoded, never
committed. If the AI call fails for any reason, that lead falls back
to the labelled mock angle.

## Tests

```bash
python3 -m unittest test_lead_scorer.py -v
# 19 tests: parsing, scoring rules, consent gating, mock labelling,
# AI failure fallback, sort order, CSV round-trip, sample data
```

## Files

| File | What it is |
|------|------------|
| `lead_scorer.py` | The scorer CLI (Python stdlib only, no installs) |
| `test_lead_scorer.py` | 19 unit tests (mock/offline mode) |
| `sample_leads.csv` | 8 sample leads to try it with |

## Verification (2026-11-14)

- `python3 -m py_compile lead_scorer.py test_lead_scorer.py` — clean
- `python3 -m unittest test_lead_scorer.py -v` — 19/19 pass
- `python3 lead_scorer.py --demo` — scores 8 sample leads (A:4, B:3, D:1),
  top leads Bright Dental and SaaSFlow (A, 100/100), 1 lead flagged
  do-not-contact (no TCPA consent)
