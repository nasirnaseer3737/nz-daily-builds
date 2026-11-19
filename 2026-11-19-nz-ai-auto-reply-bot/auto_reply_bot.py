#!/usr/bin/env python3
"""
nz-ai-auto-reply-bot — AI auto-reply bot for a lead inbox (WhatsApp / email).

Small businesses miss leads when an enquiry sits unanswered overnight. This
CLI reads an inbox export (CSV or JSON), classifies each incoming message,
drafts a helpful reply, and builds a paced send queue — so no lead waits
until morning and no angry customer gets a robot answer.

* Real AI mode: calls the Google Gemini API (gemini-2.0-flash) when the
  NZ_GEMINI_API_KEY environment variable is set. Gemini classifies the
  intent AND drafts the reply in the business's voice.
* Mock mode: when no key is set (or --mock is passed) a clearly labelled
  offline fallback classifies by keyword rules and drafts from intent
  templates. Mock rows are tagged "mock" in every output and are NEVER
  presented as AI output.

Safety rules (the bot never sends anything itself — it only drafts):

  - Escalation: messages containing refund / complaint / angry / lawyer /
    cancel / scam words are NEVER auto-replied. They are flagged
    "escalate" for a human, with a short holding reply suggested only.
  - WhatsApp 24h window: a WhatsApp message older than 24 hours cannot be
    answered with a free-form reply any more. It is flagged
    "outside_window" — the draft is kept but marked as needing an approved
    template message instead.
  - Quiet hours: replies are never scheduled between 22:00 and 08:00 PKT.
    Messages received overnight are queued for 08:00 the next morning.
  - Send pacing: queued replies are spaced 10 minutes apart (one message,
    then a 10-minute gap), matching the user's outreach rule.
  - Dedupe: replied.json remembers every message already answered. Re-runs
    skip them unless --force is passed.

Inputs (CSV columns or JSON objects):
  id, channel (whatsapp/email), sender, name, message, received_at (ISO 8601)

Outputs (into --out, default ./replies):
  - replies.csv   one row per message: id, channel, sender, intent, source,
                  status, scheduled_for, reply
  - replies.json  structured results + run summary
  - replies.md    human-readable report, escalations on top
  - queue.json    the paced send queue (only auto-replyable messages)

Usage:
  python3 auto_reply_bot.py --inbox messages.csv --business "NZ Plumbing" \\
      --services "plumbing, drain cleaning, bathroom fitting" \\
      --whatsapp "923339845505" --out ./replies
  python3 auto_reply_bot.py --inbox messages.json --mock --start "2026-11-20 08:00"
  python3 auto_reply_bot.py --inbox messages.csv --check replies.csv

API key setup:
  export NZ_GEMINI_API_KEY=<your key>
  Get a free key at https://aistudio.google.com/app/apikey
  The key is NEVER hardcoded or committed — it is read only from the
  environment.
"""

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

VERSION = "1.0.0"

GEMINI_MODEL = "gemini-2.0-flash"
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)

# Quiet hours (PKT): never schedule a reply between 22:00 and 08:00.
QUIET_START_HOUR = 22
QUIET_END_HOUR = 8
SEND_GAP_MINUTES = 10
WHATSAPP_WINDOW_HOURS = 24

PKT = timezone(timedelta(hours=5))

ESCALATION_WORDS = (
    "refund", "complaint", "complain", "angry", "furious", "lawyer",
    "court", "scam", "fraud", "cheated", "cancel my", "cancelled my",
    "worst", "terrible service", "report you", "police",
)

SPAM_WORDS = (
    "free money", "crypto giveaway", "double your money", "lottery win",
    "you have won", "claim your prize", "bitcoin investment",
)

# intent -> keywords (checked in this order; first match wins)
INTENT_KEYWORDS = [
    ("pricing", ("price", "cost", "rate", "quote", "how much", "charges",
                 "fee", "package", "discount", "estimate")),
    ("booking", ("book", "appointment", "schedule", "available", "slot",
                 "visit", "come over", "when can you")),
    ("services", ("service", "services", "what do you do", "do you offer",
                  "do you fix", "can you fix", "repair")),
    ("hours", ("open", "hours", "timing", "timings", "closed", "when do you open",
               "working hours")),
    ("location", ("where", "address", "location", "direction", "how to reach",
                  "area", "near")),
    ("greeting", ("hi", "hello", "hey", "salam", "assalam", "good morning",
                  "good evening", "aoa")),
]

MOCK_TEMPLATES = {
    "pricing": (
        "Hi {name}, thanks for asking! Our {services} pricing depends on the "
        "job — could you share a few details (what needs doing and your area)? "
        "I'll send you an exact quote. You can also chat with us on WhatsApp."
    ),
    "booking": (
        "Hi {name}, happy to book you in! Please share your preferred day/time "
        "and your address, and I'll confirm a slot for {services}. "
        "You can also chat with us on WhatsApp."
    ),
    "services": (
        "Hi {name}, yes — we offer {services}. Tell me a little about what "
        "you need and I'll point you to the right option. "
        "You can also chat with us on WhatsApp."
    ),
    "hours": (
        "Hi {name}, we're open Mon–Sat, 9am–7pm. Evenings and Sundays are by "
        "appointment. What can we help you with?"
    ),
    "location": (
        "Hi {name}, we're based locally and serve the surrounding areas. "
        "Share your area and I'll confirm coverage and travel time for you."
    ),
    "greeting": (
        "Hi {name}, thanks for messaging {business}! How can we help you "
        "today — pricing, booking, or something else?"
    ),
    "other": (
        "Hi {name}, thanks for reaching out to {business}! Could you share a "
        "little more detail so I can help you properly? "
        "You can also chat with us on WhatsApp."
    ),
}

ESCALATION_HOLDING_REPLY = (
    "Hi {name}, I'm really sorry about this — thank you for letting us know. "
    "I've flagged this for the owner, who will contact you personally within "
    "a few hours. Your message matters to us."
)


# ---------------------------------------------------------------------------
# Inbox loading
# ---------------------------------------------------------------------------

def parse_time(value):
    """Parse an ISO 8601 time; naive values are treated as PKT."""
    if not value:
        return None
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=PKT)
    return parsed


def load_inbox(path):
    """Load messages from a CSV or JSON inbox export."""
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"not a file: {path}")
    if path.suffix.lower() == ".json":
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        rows = data if isinstance(data, list) else data.get("messages", [])
    elif path.suffix.lower() == ".csv":
        with open(path, newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
    else:
        raise ValueError("inbox must be a .csv or .json file")
    messages = []
    for row in rows:
        message = {
            "id": str(row.get("id") or "").strip(),
            "channel": str(row.get("channel") or "whatsapp").strip().lower(),
            "sender": str(row.get("sender") or "").strip(),
            "name": str(row.get("name") or "").strip() or "there",
            "message": str(row.get("message") or "").strip(),
            "received_at": parse_time(row.get("received_at")),
        }
        if not message["id"]:
            message["id"] = hashlib.sha256(
                (message["sender"] + "|" + message["message"]).encode()
            ).hexdigest()[:12]
        if message["message"]:
            messages.append(message)
    return messages


# ---------------------------------------------------------------------------
# Intent classification (offline rules — also the mock fallback)
# ---------------------------------------------------------------------------

def classify_intent(text):
    """Return (intent, escalate, spam) for a message using keyword rules."""
    lowered = " " + re.sub(r"[^a-z0-9 ]", " ", text.lower()) + " "
    if any(word in lowered for word in SPAM_WORDS):
        return "spam", False, True
    if any(word in lowered for word in ESCALATION_WORDS):
        return "complaint", True, False
    for intent, keywords in INTENT_KEYWORDS:
        # Whole-word/phrase match: bare substring matching would catch
        # "hi" inside "something" or "open" inside "opening".
        if any(re.search(r"\b" + re.escape(kw) + r"\b", lowered)
               for kw in keywords):
            return intent, False, False
    return "other", False, False


def mock_reply(intent, name, business, services):
    """Draft a reply from the intent template. Labelled 'mock' everywhere."""
    template = MOCK_TEMPLATES.get(intent, MOCK_TEMPLATES["other"])
    return template.format(name=name, business=business, services=services)


# ---------------------------------------------------------------------------
# Gemini AI mode
# ---------------------------------------------------------------------------

def gemini_reply(message, intent, business, services, api_key, timeout=30):
    """Ask Gemini to classify + draft a reply. Returns (intent, reply, error)."""
    prompt = (
        f"You are the auto-reply assistant for the business '{business}' "
        f"(services: {services}). A customer wrote: \"{message}\". "
        "First classify the intent as one word: pricing, booking, services, "
        "hours, location, greeting, complaint, spam, or other. "
        "Then write one short, friendly reply (max 3 sentences, no 'call us' "
        "— instead invite them to reply here or chat on WhatsApp). "
        "Reply ONLY as JSON: {\"intent\": \"...\", \"reply\": \"...\"}."
    )
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 300},
    }).encode("utf-8")
    request = urllib.request.Request(
        f"{GEMINI_URL}?key={api_key}",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return None, None, f"Gemini HTTP {exc.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return None, None, f"Gemini request failed: {exc}"
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        parsed = json.loads(text.strip().strip("`").replace("json\n", "", 1))
        return parsed.get("intent", "other"), parsed.get("reply", ""), None
    except (KeyError, IndexError, TypeError, json.JSONDecodeError, AttributeError):
        return None, None, "Gemini returned an unexpected response"


# ---------------------------------------------------------------------------
# Scheduling rules
# ---------------------------------------------------------------------------

def in_quiet_hours(moment):
    """True when a PKT time falls inside 22:00–08:00 quiet hours."""
    hour = moment.astimezone(PKT).hour
    return hour >= QUIET_START_HOUR or hour < QUIET_END_HOUR


def next_open_slot(moment):
    """Move a PKT time forward to 08:00 if it falls in quiet hours."""
    local = moment.astimezone(PKT)
    if in_quiet_hours(local):
        if local.hour >= QUIET_START_HOUR:
            local = local + timedelta(days=1)
        return local.replace(hour=QUIET_END_HOUR, minute=0,
                             second=0, microsecond=0)
    return local


def outside_whatsapp_window(received_at, now):
    """WhatsApp free-form replies are only allowed within 24h of receipt."""
    if received_at is None:
        return False
    return (now - received_at) > timedelta(hours=WHATSAPP_WINDOW_HOURS)


# ---------------------------------------------------------------------------
# History (dedupe) handling
# ---------------------------------------------------------------------------

def load_history(out_dir):
    """Return {message_id: reply} already answered, or {} when none exists."""
    history_path = Path(out_dir) / "replied.json"
    if not history_path.is_file():
        return {}
    try:
        with open(history_path, encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_history(out_dir, history):
    """Persist the replied.json history file."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "replied.json", "w", encoding="utf-8") as handle:
        json.dump(history, handle, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Core run
# ---------------------------------------------------------------------------

def generate_reply(message, business, services, api_key, use_mock):
    """Return (intent, reply, source, escalate, spam) for one message."""
    intent, escalate, spam = classify_intent(message["message"])
    if spam:
        return intent, "", "rule", escalate, spam
    if escalate:
        reply = ESCALATION_HOLDING_REPLY.format(name=message["name"])
        return intent, reply, "rule", escalate, spam
    if use_mock or not api_key:
        return (intent,
                mock_reply(intent, message["name"], business, services),
                "mock", escalate, spam)
    ai_intent, ai_reply, error = gemini_reply(
        message["message"], intent, business, services, api_key)
    if error or not ai_reply:
        if error:
            print(f"  ! Gemini failed for {message['id']} ({error})"
                  " — mock fallback", file=sys.stderr)
        return (intent,
                mock_reply(intent, message["name"], business, services),
                "mock", escalate, spam)
    # Gemini may reclassify; keep its intent when it is a known one.
    if ai_intent in MOCK_TEMPLATES or ai_intent in ("complaint", "spam"):
        intent = ai_intent
        if ai_intent == "complaint":
            escalate = True
    return intent, ai_reply.strip(), "ai", escalate, spam


def run(messages, out_dir, business, services, whatsapp=None, api_key=None,
        use_mock=False, start=None, force=False, now=None):
    """Classify, draft and schedule replies; write CSV/JSON/Markdown + queue."""
    now = now or datetime.now(PKT)
    start = start or now
    start = next_open_slot(start)
    history = load_history(out_dir)

    results = []
    queue = []
    slot = start
    counts = {"ai": 0, "mock": 0, "rule": 0, "escalate": 0, "spam": 0,
              "outside_window": 0, "skipped": 0}

    for message in messages:
        if message["id"] in history and not force:
            counts["skipped"] += 1
            results.append({
                "id": message["id"], "channel": message["channel"],
                "sender": message["sender"], "name": message["name"],
                "message": message["message"], "intent": "already_replied",
                "source": "done", "status": "skipped",
                "scheduled_for": "", "reply": history[message["id"]],
            })
            continue

        intent, reply, source, escalate, spam = generate_reply(
            message, business, services, api_key, use_mock)

        if spam:
            status = "spam — no reply"
            counts["spam"] += 1
            scheduled = ""
        elif escalate:
            status = "escalate — human only"
            counts["escalate"] += 1
            scheduled = ""
        elif (message["channel"] == "whatsapp"
              and outside_whatsapp_window(message["received_at"], now)):
            status = "outside_window — needs approved template"
            counts["outside_window"] += 1
            scheduled = ""
        else:
            status = "queued"
            scheduled = slot.astimezone(PKT).strftime("%Y-%m-%d %H:%M")
            queue.append({
                "id": message["id"], "channel": message["channel"],
                "sender": message["sender"], "scheduled_for": scheduled,
                "reply": reply,
            })
            slot = next_open_slot(slot + timedelta(minutes=SEND_GAP_MINUTES))

        if source in counts:
            counts[source] += 1
        history[message["id"]] = reply
        results.append({
            "id": message["id"], "channel": message["channel"],
            "sender": message["sender"], "name": message["name"],
            "message": message["message"], "intent": intent,
            "source": source, "status": status,
            "scheduled_for": scheduled, "reply": reply,
        })

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    save_history(out_dir, history)

    with open(out / "replies.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "id", "channel", "sender", "intent", "source", "status",
            "scheduled_for", "reply"])
        writer.writeheader()
        for row in results:
            writer.writerow({k: row[k] for k in writer.fieldnames})

    summary = {
        "total": len(results),
        "queued": len(queue),
        "ai": counts["ai"], "mock": counts["mock"], "rule": counts["rule"],
        "escalate": counts["escalate"], "spam": counts["spam"],
        "outside_window": counts["outside_window"],
        "skipped_already_replied": counts["skipped"],
        "business": business,
        "queue_start": queue[0]["scheduled_for"] if queue else None,
        "queue_end": queue[-1]["scheduled_for"] if queue else None,
    }
    with open(out / "replies.json", "w", encoding="utf-8") as handle:
        json.dump({"summary": summary, "results": results}, handle,
                  indent=2, ensure_ascii=False)
    with open(out / "queue.json", "w", encoding="utf-8") as handle:
        json.dump({"send_gap_minutes": SEND_GAP_MINUTES, "queue": queue},
                  handle, indent=2, ensure_ascii=False)

    lines = [f"# Auto-replies — {business}\n"]
    lines.append(f"Total messages: {summary['total']} — queued: "
                 f"{summary['queued']}, escalate: {summary['escalate']}, "
                 f"spam: {summary['spam']}, outside 24h window: "
                 f"{summary['outside_window']}, already replied: "
                 f"{summary['skipped_already_replied']}\n")
    if queue:
        lines.append(f"Queue: {summary['queue_start']} → "
                     f"{summary['queue_end']} PKT "
                     f"({SEND_GAP_MINUTES}-minute gaps, no quiet hours)\n")
    escalations = [r for r in results if r["status"].startswith("escalate")]
    if escalations:
        lines.append("## Needs a human\n")
        for row in escalations:
            lines.append(f"- **{row['name']}** ({row['channel']}): "
                         f"{row['message']}")
    lines.append("\n## Replies\n")
    lines.append("| ID | Sender | Intent | Source | Status | Scheduled | Reply |")
    lines.append("|---|---|---|---|---|---|---|")
    for row in results:
        reply = row["reply"].replace("|", "/").replace("\n", " ")
        lines.append(f"| {row['id']} | {row['sender']} | {row['intent']} | "
                     f"{row['source']} | {row['status']} | "
                     f"{row['scheduled_for']} | {reply} |")
    with open(out / "replies.md", "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")

    return summary, results


# ---------------------------------------------------------------------------
# --check mode: audit an existing replies.csv
# ---------------------------------------------------------------------------

def check_replies(csv_path):
    """Audit a replies.csv: report rows missing a reply or wrongly queued."""
    path = Path(csv_path)
    if not path.is_file():
        raise ValueError(f"not a file: {csv_path}")
    problems = []
    with open(path, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        status = (row.get("status") or "").strip()
        reply = (row.get("reply") or "").strip()
        if status == "queued" and not reply:
            problems.append(f"{row.get('id')}: queued but reply is empty")
        if status.startswith("escalate") and (row.get("scheduled_for") or "").strip():
            problems.append(f"{row.get('id')}: escalated but scheduled")
        if status.startswith("spam") and reply:
            problems.append(f"{row.get('id')}: spam but a reply was drafted")
        if status.startswith("outside_window") and (row.get("scheduled_for") or "").strip():
            problems.append(f"{row.get('id')}: outside 24h window but scheduled")
    return len(rows), problems


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        description="AI auto-reply bot for a lead inbox (WhatsApp/email).")
    parser.add_argument("--inbox", required=True,
                        help="messages CSV or JSON export")
    parser.add_argument("--business", default="our business",
                        help="business name used in replies")
    parser.add_argument("--services", default="our services",
                        help="services offered, used in replies")
    parser.add_argument("--whatsapp", default="",
                        help="business WhatsApp number (for reference only)")
    parser.add_argument("--out", default="replies",
                        help="output folder (default: replies)")
    parser.add_argument("--mock", action="store_true",
                        help="force the labelled mock/offline mode")
    parser.add_argument("--start",
                        help="queue start time, e.g. '2026-11-20 08:00' (PKT)")
    parser.add_argument("--force", action="store_true",
                        help="re-draft messages already in replied.json")
    parser.add_argument("--check", metavar="REPLIES_CSV",
                        help="audit an existing replies.csv instead of running")
    parser.add_argument("--version", action="version",
                        version=f"nz-ai-auto-reply-bot {VERSION}")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.check:
        total, problems = check_replies(args.check)
        print(f"checked {total} rows in {args.check}")
        if problems:
            print(f"{len(problems)} problem(s):")
            for problem in problems:
                print(f"  - {problem}")
            return 1
        print("no problems found")
        return 0

    messages = load_inbox(args.inbox)
    api_key = os.environ.get("NZ_GEMINI_API_KEY", "").strip()
    mode = "mock (labelled offline fallback)" if (args.mock or not api_key) \
        else f"AI ({GEMINI_MODEL})"
    start = parse_time(args.start) if args.start else None
    summary, _results = run(
        messages, args.out, args.business, args.services,
        whatsapp=args.whatsapp, api_key=api_key or None,
        use_mock=args.mock, start=start)
    print(f"nz-ai-auto-reply-bot {VERSION} — {summary['total']} message(s), "
          f"mode: {mode}")
    print(f"done: {summary['queued']} queued, {summary['escalate']} escalate, "
          f"{summary['spam']} spam, {summary['outside_window']} outside 24h "
          f"window, {summary['skipped_already_replied']} already replied "
          f"(AI {summary['ai']}, mock {summary['mock']}, rule {summary['rule']})")
    if summary["queue_start"]:
        print(f"queue: {summary['queue_start']} → {summary['queue_end']} PKT")
    print(f"outputs: {args.out}/replies.csv, replies.json, replies.md, queue.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
