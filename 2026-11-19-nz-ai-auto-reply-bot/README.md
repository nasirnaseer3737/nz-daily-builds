# nz-ai-auto-reply-bot — AI auto-reply bot for a lead inbox

A Python stdlib CLI that reads a WhatsApp/email inbox export, classifies
each incoming message, drafts a helpful reply, and builds a paced send
queue — so no lead waits until morning and no angry customer gets a robot
answer. The bot drafts only; it never sends anything itself.

## What it does

- Loads an inbox from CSV or JSON (`id, channel, sender, name, message,
  received_at`).
- Classifies intent — pricing, booking, services, hours, location,
  greeting, complaint, spam, other:
  - **AI mode** — Google Gemini (`gemini-2.0-flash`) via the
    `NZ_GEMINI_API_KEY` environment variable classifies the intent AND
    drafts the reply in the business's voice.
  - **Mock mode** — when no key is set (or with `--mock`), a clearly
    labelled offline fallback classifies by keyword rules and drafts from
    intent templates. Mock rows are tagged `mock` in every output and are
    never presented as AI output.
- Safety rules, always on:
  - **Escalation** — refund/complaint/angry/lawyer/cancel words are NEVER
    auto-replied; flagged `escalate — human only` with a short holding
    reply suggested.
  - **WhatsApp 24h window** — a WhatsApp message older than 24 hours is
    flagged `outside_window` (needs an approved template message, not a
    free-form reply). Email has no such window.
  - **Quiet hours** — replies are never scheduled 22:00–08:00 PKT;
    overnight messages queue for 08:00 the next morning.
  - **Send pacing** — queued replies are spaced 10 minutes apart.
  - **Dedupe** — `replied.json` remembers answered messages; re-runs skip
    them unless `--force` is passed.
- Never tells a customer to "call us" — the reply invites them to reply
  here or chat on WhatsApp.

## Outputs (into `--out`, default `replies/`)

| File | Contents |
|------|----------|
| `replies.csv` | one row per message: id, channel, sender, intent, source, status, scheduled_for, reply |
| `replies.json` | structured results + run summary |
| `replies.md` | human-readable report, escalations on top |
| `queue.json` | the paced send queue (auto-replyable messages only) |
| `replied.json` | dedupe history of answered message IDs |

## Usage

```bash
python3 auto_reply_bot.py --inbox sample_messages.csv \
    --business "NZ Plumbing" \
    --services "plumbing, drain cleaning, bathroom fitting" \
    --whatsapp "923339845505" --mock --out replies
```

With a real Gemini key (AI mode):

```bash
export NZ_GEMINI_API_KEY=<your key>
python3 auto_reply_bot.py --inbox messages.csv --business "NZ Plumbing" \
    --services "plumbing, drain cleaning" --out replies
```

Other options: `--start "2026-11-20 08:00"` (queue start time, PKT),
`--force` (re-draft already-answered messages),
`--check replies.csv` (audit an existing replies file for bad rows —
queued-but-empty replies, escalated-but-scheduled, spam-with-a-reply).

## API key setup

```bash
export NZ_GEMINI_API_KEY=<your key>
```

Get a free key at https://aistudio.google.com/app/apikey — the key is NEVER
hardcoded or committed; it is read only from the environment.

## Demo

`sample_messages.csv` has 8 messages: pricing, booking, services,
greeting, a refund complaint, a spam message, an old WhatsApp message
(outside the 24h window) and an overnight message (quiet hours). Run in
mock mode:

```bash
python3 auto_reply_bot.py --inbox sample_messages.csv \
    --business "NZ Plumbing" --services "plumbing, drain cleaning" \
    --mock --out demo-output
```

Expected: 5 queued (10-minute gaps from 14:00 PKT), 1 escalate, 1 spam,
1 outside 24h window.

## Tests

```bash
python3 -m py_compile auto_reply_bot.py test_auto_reply_bot.py
python3 -m unittest test_auto_reply_bot -v
```

27 tests, mock/offline only — no API key or network needed (one test mocks
a Gemini failure to prove the mock fallback kicks in).
