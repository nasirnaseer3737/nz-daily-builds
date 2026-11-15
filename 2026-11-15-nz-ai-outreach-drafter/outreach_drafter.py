#!/usr/bin/env python3
"""
NZ AI Outreach Email Drafter
=============================

Turns a CSV of prospects into personalised, ready-to-send outreach emails —
one draft per prospect, with a 10-minute paced send queue.

How it works (end to end):
  1. Read prospects from a CSV (name, business, niche, city, email, website,
     pain_point, consent).
  2. Skip anyone without TCPA consent — they are flagged DO-NOT-CONTACT and
     never drafted.
  3. Skip anyone already in the sent-history file (no duplicate outreach).
  4. Draft a personalised email per prospect: 3 subject-line options + body.
     With NZ_GEMINI_API_KEY set it calls the Gemini API (free tier) for a
     genuinely AI-written draft; without a key it uses a clearly labelled
     MOCK template fallback so the tool still works offline.
  5. Write drafts.csv (one row per draft) and queue.json — a send queue with
     one slot every N minutes (default 10, matching the "one mail, then a
     10-minute gap" outreach rule), so a sender can work through the queue
     without batching.

Usage:
  python3 outreach_drafter.py --input prospects.csv --out out/
  python3 outreach_drafter.py --input prospects.csv --out out/ --limit 5
  python3 outreach_drafter.py --input prospects.csv --out out/ \
      --start "2026-11-15 14:00" --gap-minutes 10

API key (never hardcode it):
  export NZ_GEMINI_API_KEY="your-gemini-api-key"
  # Get a free key at https://aistudio.google.com/app/apikey

Python standard library only — no dependencies to install.
"""

import argparse
import csv
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timedelta

VERSION = "1.0.0"
DEFAULT_GAP_MINUTES = 10
GEMINI_MODEL = "gemini-2.0-flash"
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    + GEMINI_MODEL
    + ":generateContent"
)

# ---------------------------------------------------------------------------
# Prospect loading & validation
# ---------------------------------------------------------------------------

REQUIRED_COLUMNS = ["name", "business", "niche", "city", "email"]
OPTIONAL_COLUMNS = ["website", "pain_point", "consent"]

# Niches the mock drafter knows how to talk about. Unknown niches fall back
# to a generic-but-personalised line built from the prospect's own words.
NICHE_LINES = {
    "plumbing": "slow website, missed calls after hours, and jobs lost to "
                "competitors who answer first",
    "dental": "empty chair time, no-shows, and new-patient bookings that "
              "never turn into visits",
    "roofing": "storm-season leads going to the first roofer who picks up "
               "the phone",
    "hvac": "seasonal rushes where the phone rings off the hook and "
            "quotes slip through the cracks",
    "solar": "homeowners who ask for a quote and then go quiet before "
             "the survey is booked",
    "real estate": "leads that go cold while agents are out showing homes",
    "clinic": "patients who call once, get no answer, and book elsewhere",
}


def load_prospects(path):
    """Read prospects CSV. Returns (prospects, errors)."""
    prospects, errors = [], []
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            return [], ["empty CSV: no header row"]
        missing = [c for c in REQUIRED_COLUMNS if c not in reader.fieldnames]
        if missing:
            return [], ["missing required column(s): " + ", ".join(missing)]
        for lineno, row in enumerate(reader, start=2):
            row = {k: (v or "").strip() for k, v in row.items() if k}
            email = row.get("email", "")
            if not row.get("business") and not row.get("name"):
                errors.append(f"line {lineno}: no name or business, skipped")
                continue
            if "@" not in email or "." not in email.split("@")[-1]:
                errors.append(f"line {lineno}: bad email '{email}', skipped")
                continue
            row.setdefault("website", "")
            row.setdefault("pain_point", "")
            row.setdefault("consent", "")
            prospects.append(row)
    return prospects, errors


def has_consent(row):
    """TCPA gate: only explicit yes/opt-in counts as consent."""
    return row.get("consent", "").strip().lower() in ("yes", "y", "true", "opt-in", "optin")


def load_history(path):
    """Sent-history JSON: {"email": "ISO date"}. Missing file = empty."""
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


# ---------------------------------------------------------------------------
# Drafting — Gemini AI, with a clearly labelled mock fallback
# ---------------------------------------------------------------------------

def mock_draft(prospect):
    """Template draft (MOCK — no AI involved). Personalised from the
    prospect's own fields so every draft is still unique."""
    name = prospect.get("name") or "there"
    business = prospect.get("business") or "your business"
    niche = (prospect.get("niche") or "local business").lower()
    city = prospect.get("city") or "your area"
    pain = prospect.get("pain_point") or NICHE_LINES.get(
        niche, "leads that slip away while you're busy doing the work")
    first = name.split()[0]

    subjects = [
        f"Quick idea for {business} in {city}",
        f"{first} — {business} losing jobs to slow replies?",
        f"2 minutes that could win {business} more {niche} work",
    ]
    body = (
        f"Hi {first},\n\n"
        f"I came across {business} while looking at {niche} businesses in "
        f"{city}, and one thing stood out: {pain}.\n\n"
        f"We help {niche} businesses fix exactly that — a simple system "
        f"that answers every enquiry fast, follows up automatically, and "
        f"books the job while the customer is still deciding. No new "
        f"software to learn, no extra staff needed.\n\n"
        f"Would a quick 10-minute call this week be useful? I can show you "
        f"what it would look like for {business} specifically — no pitch, "
        f"no obligation.\n\n"
        f"Best regards,\nNasir Naseer\n"
        f"Web Development & AI Automation — nzgenix.digital"
    )
    return {"subjects": subjects, "body": body, "source": "mock"}


def gemini_draft(prospect, api_key):
    """Ask Gemini for a personalised draft. Returns dict or None on failure."""
    prompt = (
        "Write a short, friendly cold outreach email for a web developer / "
        "AI automation specialist to a local business owner. "
        "Keep it under 150 words, plain English, no hype, no emojis. "
        "Return exactly this format:\n"
        "SUBJECT: <one subject line>\n"
        "SUBJECT: <second subject line>\n"
        "SUBJECT: <third subject line>\n"
        "BODY:\n<email body>\n\n"
        f"Business: {prospect.get('business')}\n"
        f"Owner: {prospect.get('name')}\n"
        f"Niche: {prospect.get('niche')}\n"
        f"City: {prospect.get('city')}\n"
        f"Website: {prospect.get('website') or 'none listed'}\n"
        f"Their pain point: {prospect.get('pain_point') or 'not specified'}\n"
        "Offer: a simple AI system that answers enquiries fast and books "
        "jobs automatically. Sender: Nasir Naseer, nzgenix.digital."
    )
    payload = json.dumps(
        {"contents": [{"parts": [{"text": prompt}]}]}
    ).encode("utf-8")
    req = urllib.request.Request(
        GEMINI_URL + "?key=" + api_key,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (urllib.error.URLError, KeyError, IndexError, ValueError, TimeoutError) as exc:
        print(f"  ! Gemini call failed ({exc}); using mock draft", file=sys.stderr)
        return None
    subjects, body_lines, in_body = [], [], False
    for line in text.splitlines():
        if line.startswith("SUBJECT:"):
            subjects.append(line[len("SUBJECT:"):].strip())
        elif line.startswith("BODY:"):
            in_body = True
        elif in_body:
            body_lines.append(line)
    if not subjects or not body_lines:
        return None
    return {
        "subjects": subjects[:3],
        "body": "\n".join(body_lines).strip(),
        "source": "gemini",
    }


def draft_for(prospect, api_key):
    """AI draft when a key is available, labelled mock fallback otherwise."""
    if api_key:
        result = gemini_draft(prospect, api_key)
        if result:
            return result
    return mock_draft(prospect)


# ---------------------------------------------------------------------------
# Queue building
# ---------------------------------------------------------------------------

def build_queue(drafts, start, gap_minutes):
    """Assign one send slot per draft, gap_minutes apart, starting at start."""
    queue, when = [], start
    for draft in drafts:
        queue.append({
            "email": draft["email"],
            "business": draft["business"],
            "subject": draft["subjects"][0],
            "send_at": when.strftime("%Y-%m-%d %H:%M"),
            "status": "queued",
        })
        when += timedelta(minutes=gap_minutes)
    return queue


# ---------------------------------------------------------------------------
# Main run
# ---------------------------------------------------------------------------

def run(input_path, out_dir, history_path, start, gap_minutes, limit, api_key):
    prospects, errors = load_prospects(input_path)
    history = load_history(history_path)

    drafts, skipped = [], []
    seen_emails = set()
    for row in prospects:
        email = row["email"].lower()
        if email in seen_emails:
            skipped.append((row, "duplicate email in file"))
            continue
        seen_emails.add(email)
        if not has_consent(row):
            skipped.append((row, "NO CONSENT — DO-NOT-CONTACT"))
            continue
        if email in {k.lower() for k in history}:
            skipped.append((row, f"already emailed {history.get(email, '')}"))
            continue
        draft = draft_for(row, api_key)
        draft.update({
            "name": row.get("name", ""),
            "business": row.get("business", ""),
            "niche": row.get("niche", ""),
            "city": row.get("city", ""),
            "email": row["email"],
            "website": row.get("website", ""),
        })
        drafts.append(draft)
        if limit and len(drafts) >= limit:
            break

    os.makedirs(out_dir, exist_ok=True)

    drafts_path = os.path.join(out_dir, "drafts.csv")
    with open(drafts_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["email", "name", "business", "niche", "city",
                         "subject_1", "subject_2", "subject_3", "body", "source"])
        for d in drafts:
            writer.writerow([d["email"], d["name"], d["business"], d["niche"],
                             d["city"], *(d["subjects"] + ["", "", ""])[:3],
                             d["body"], d["source"]])

    queue = build_queue(drafts, start, gap_minutes)
    queue_path = os.path.join(out_dir, "queue.json")
    with open(queue_path, "w", encoding="utf-8") as fh:
        json.dump({
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "gap_minutes": gap_minutes,
            "queue": queue,
        }, fh, indent=2)

    return {
        "total": len(prospects),
        "drafted": len(drafts),
        "skipped": skipped,
        "errors": errors,
        "ai_drafts": sum(1 for d in drafts if d["source"] == "gemini"),
        "mock_drafts": sum(1 for d in drafts if d["source"] == "mock"),
        "drafts_path": drafts_path,
        "queue_path": queue_path,
        "queue": queue,
    }


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Draft personalised AI outreach emails from a prospects CSV.")
    parser.add_argument("--input", required=True, help="Prospects CSV file")
    parser.add_argument("--out", default="out",
                        help="Output folder for drafts.csv + queue.json")
    parser.add_argument("--history", default="sent_history.json",
                        help="Sent-history JSON (skipped if missing)")
    parser.add_argument("--start", default=None,
                        help='First send slot, "YYYY-MM-DD HH:MM" (default: now)')
    parser.add_argument("--gap-minutes", type=int, default=DEFAULT_GAP_MINUTES,
                        help="Minutes between send slots (default 10)")
    parser.add_argument("--limit", type=int, default=0,
                        help="Max drafts to generate (0 = all)")
    parser.add_argument("--version", action="version", version="%(prog)s " + VERSION)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    start = (datetime.strptime(args.start, "%Y-%m-%d %H:%M") if args.start
             else datetime.now().replace(second=0, microsecond=0))
    api_key = os.environ.get("NZ_GEMINI_API_KEY", "").strip()

    result = run(args.input, args.out, args.history, start,
                 args.gap_minutes, args.limit, api_key)

    print(f"Prospects read: {result['total']}")
    print(f"Drafts written: {result['drafted']} "
          f"(AI: {result['ai_drafts']}, mock: {result['mock_drafts']})")
    print(f"Skipped: {len(result['skipped'])}")
    for row, reason in result["skipped"]:
        print(f"  - {row.get('business') or row.get('email')}: {reason}")
    for err in result["errors"]:
        print(f"  ! {err}", file=sys.stderr)
    print(f"Drafts: {result['drafts_path']}")
    print(f"Queue:  {result['queue_path']} "
          f"({len(result['queue'])} slots, {args.gap_minutes} min apart)")
    if result["queue"]:
        print(f"First send: {result['queue'][0]['send_at']}  "
              f"Last send: {result['queue'][-1]['send_at']}")
    if not api_key:
        print("Note: NZ_GEMINI_API_KEY not set — drafts are labelled MOCK. "
              "Set the key for real AI drafts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
