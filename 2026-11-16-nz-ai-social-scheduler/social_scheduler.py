#!/usr/bin/env python3
"""nz-ai-social-scheduler — AI social post drafter + scheduler.

Turns a CSV of topics into platform-ready social posts and a timed posting
schedule.

* Input: a CSV of topics — topic, platforms, tone, link, hashtags.
* For each topic x platform it drafts one post:
    - with NZ_GEMINI_API_KEY set it calls the Gemini API (free tier),
    - otherwise it uses a clearly labelled MOCK generator (offline fallback).
* Platform rules are enforced: X posts stay within 280 characters,
  LinkedIn posts are professional and <= 3000 characters, Facebook posts are
  conversational and <= 2000 characters.
* Posts are slotted into a schedule (default: one slot every 4 hours,
  starting tomorrow 14:00 Asia/Karachi) and written to schedule.json,
  drafts.md and posts.csv.
* A history file (posted.json) dedupes: a topic already scheduled/posted for
  a platform is skipped, so the same post is never drafted twice.

Usage:
    python3 social_scheduler.py topics.csv --out out/
    python3 social_scheduler.py topics.csv --out out/ --start 2026-11-17T14:00 --gap-hours 4
    python3 social_scheduler.py topics.csv --out out/ --mock        # force mock mode
    python3 social_scheduler.py topics.csv --out out/ --limit 5     # first 5 topics only

API key setup (never hardcode it):
    export NZ_GEMINI_API_KEY=<redacted>
    Get a free key at https://aistudio.google.com/app/apikey

Python standard library only — no third-party packages.
"""

import argparse
import csv
import json
import os
import re
import sys
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python < 3.9 fallback
    ZoneInfo = None

PKT = ZoneInfo("Asia/Karachi") if ZoneInfo else timezone(timedelta(hours=5))

GEMINI_MODEL = "gemini-2.0-flash"
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    + GEMINI_MODEL
    + ":generateContent"
)

# Platform rules: character limit, hashtag cap, voice hint.
PLATFORMS = {
    "linkedin": {
        "limit": 3000,
        "max_hashtags": 5,
        "voice": "professional, helpful, confident; short paragraphs; "
                 "end with a question or a clear takeaway",
    },
    "x": {
        "limit": 280,
        "max_hashtags": 2,
        "voice": "punchy and direct; one idea only; no fluff; "
                 "a hook in the first line",
    },
    "facebook": {
        "limit": 2000,
        "max_hashtags": 3,
        "voice": "warm and conversational, like talking to a friend; "
                 "one short story or example",
    },
}

VALID_TONES = {"professional", "friendly", "bold", "educational", "funny"}
DEFAULT_TONE = "professional"
DEFAULT_GAP_HOURS = 4
DEFAULT_START_HOUR = 14  # 14:00 PKT — the user's usual daily-post time


def parse_platforms(raw):
    """Split a platforms cell ('linkedin; x' or 'linkedin, x') into a clean
    ordered list."""
    seen = []
    for piece in re.split(r"[,;]", raw or ""):
        name = piece.strip().lower()
        if name in PLATFORMS and name not in seen:
            seen.append(name)
    return seen


def parse_hashtags(raw):
    """Normalise a hashtags cell into ['#WordPress', ...] (no dupes)."""
    tags = []
    for piece in (raw or "").replace(";", ",").split(","):
        tag = piece.strip().lstrip("#").strip()
        if tag and re.fullmatch(r"[A-Za-z0-9_]+", tag):
            tag = "#" + tag
            if tag.lower() not in [t.lower() for t in tags]:
                tags.append(tag)
    return tags


def load_topics(path):
    """Read topics CSV. Required column: topic. Optional: platforms, tone,
    link, hashtags. Returns a list of dicts."""
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None or "topic" not in reader.fieldnames:
            raise ValueError("topics CSV must have a 'topic' column")
        topics = []
        for row in reader:
            topic = (row.get("topic") or "").strip()
            if not topic:
                continue
            tone = (row.get("tone") or DEFAULT_TONE).strip().lower()
            topics.append({
                "topic": topic,
                "platforms": parse_platforms(row.get("platforms") or "linkedin"),
                "tone": tone if tone in VALID_TONES else DEFAULT_TONE,
                "link": (row.get("link") or "").strip(),
                "hashtags": parse_hashtags(row.get("hashtags") or ""),
            })
    return topics


def load_history(path):
    """Read posted.json history: {'topic|platform': 'YYYY-MM-DDTHH:MM'}."""
    if not path or not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return data if isinstance(data, dict) else {}


def save_history(path, history):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(history, fh, indent=2, sort_keys=True)
        fh.write("\n")


def history_key(topic, platform):
    return topic.strip().lower() + "|" + platform


def build_prompt(topic, platform, tone):
    rules = PLATFORMS[platform]
    return (
        "Write one social media post for {platform} about this topic: {topic}\n"
        "Tone: {tone}. Voice: {voice}.\n"
        "Keep it under {limit} characters including hashtags. "
        "Use at most {max_tags} hashtags, placed at the end. "
        "Return only the post text, no introduction, no quotes around it."
    ).format(
        platform=platform, topic=topic["topic"], tone=topic["tone"],
        voice=rules["voice"], limit=rules["limit"],
        max_tags=rules["max_hashtags"],
    )


def mock_generate(topic, platform):
    """Clearly labelled offline fallback — no AI involved.

    Produces a deterministic, platform-shaped post from the topic so the
    scheduler, limits and outputs can be tested without an API key.
    """
    rules = PLATFORMS[platform]
    text = topic["topic"]
    link = topic["link"]
    if platform == "x":
        body = "Quick take: {t}".format(t=text)
        if link:
            body += " {link}".format(link=link)
    elif platform == "facebook":
        body = (
            "Something worth sharing today:\n\n{t}\n\n"
            "If this helps your business, save it for later — "
            "and tell me in the comments what you would add."
        ).format(t=text)
    else:  # linkedin
        body = (
            "{t}\n\n"
            "Here is the practical side of it: start small, measure what "
            "changes, and keep the part that works. Most teams overthink "
            "the tool and underthink the workflow.\n\n"
            "What has worked best for you?"
        ).format(t=text)
        if link:
            body += "\n\nRead more: {link}".format(link=link)
    tags = topic["hashtags"][: rules["max_hashtags"]]
    if tags:
        body += "\n\n" + " ".join(tags)
    return body


def gemini_generate(topic, platform, api_key):
    """Call the Gemini API for one post. Raises on HTTP/API failure."""
    payload = json.dumps({
        "contents": [{
            "parts": [{"text": build_prompt(topic, platform, topic["tone"])}]
        }],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 600},
    }).encode("utf-8")
    req = urllib.request.Request(
        GEMINI_URL + "?key=" + api_key,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as exc:
        raise RuntimeError("Gemini API HTTP {0}".format(exc.code)) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError("Gemini API unreachable: {0}".format(exc.reason)) from exc
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("Gemini API returned an unexpected response") from exc
    return text.strip()


def enforce_limits(text, platform):
    """Enforce the platform character limit and hashtag cap.

    Truncates the body (keeping hashtags) so the final post fits, and caps
    the hashtag count. Returns the cleaned post text.
    """
    rules = PLATFORMS[platform]
    limit = rules["limit"]
    text = text.strip()
    if len(text) <= limit:
        return text
    # Split trailing hashtag block off so it survives truncation.
    match = re.search(r"(?:\n\s*)((?:#[A-Za-z0-9_]+\s*)+)\s*$", text)
    tags, body = "", text
    if match:
        tags = match.group(1).strip()
        body = text[: match.start()].rstrip()
    tag_list = tags.split()[: rules["max_hashtags"]]
    tags = " ".join(tag_list)
    room = limit - (len(tags) + 2 if tags else 0)
    if room < 20:  # pathological: hashtags alone nearly fill the limit
        return tags[:limit]
    body = body[:room].rstrip()
    if len(body) < len(text[: match.start()].rstrip() if match else text):
        body = body.rstrip(".,;:") + "…"
    return (body + "\n\n" + tags) if tags else body


def draft_post(topic, platform, api_key, force_mock=False):
    """Draft one post. Returns {'text': ..., 'source': 'gemini'|'mock'}.

    Falls back to the labelled mock generator if the API key is missing or
    the API call fails — the scheduler never crashes on an AI outage.
    """
    if api_key and not force_mock:
        try:
            text = gemini_generate(topic, platform, api_key)
            return {"text": enforce_limits(text, platform), "source": "gemini"}
        except RuntimeError as exc:
            print("  ! Gemini failed for {0}/{1}: {2} — using MOCK".format(
                topic["topic"][:40], platform, exc), file=sys.stderr)
    return {"text": enforce_limits(mock_generate(topic, platform), platform),
            "source": "mock"}


def schedule_slots(count, start, gap_hours):
    """Return `count` datetimes: start, start+gap, start+2*gap, ..."""
    return [start + timedelta(hours=gap_hours * i) for i in range(count)]


def default_start(now=None):
    """Tomorrow at 14:00 PKT (the user's usual daily-post time)."""
    now = now or datetime.now(PKT)
    return (now + timedelta(days=1)).replace(
        hour=DEFAULT_START_HOUR, minute=0, second=0, microsecond=0)


def parse_start(raw, now=None):
    """Parse 'YYYY-MM-DDTHH:MM' (assumed PKT) or 'YYYY-MM-DD' (14:00 PKT)."""
    try:
        if "T" in raw:
            dt = datetime.strptime(raw, "%Y-%m-%dT%H:%M")
        else:
            dt = datetime.strptime(raw, "%Y-%m-%d")
            dt = dt.replace(hour=DEFAULT_START_HOUR, minute=0)
    except ValueError as exc:
        raise ValueError(
            "bad --start value {0!r}: use YYYY-MM-DD or YYYY-MM-DDTHH:MM".format(raw)
        ) from exc
    return dt.replace(tzinfo=PKT)


def run(input_path, out_dir, history_path, start, gap_hours, limit,
        api_key, force_mock=False):
    """Full pipeline: load topics -> dedupe -> draft -> schedule -> write."""
    topics = load_topics(input_path)
    if limit:
        topics = topics[:limit]
    history = load_history(history_path)

    jobs = []  # (topic, platform) pairs not already in history
    skipped = 0
    for topic in topics:
        for platform in topic["platforms"]:
            if history_key(topic["topic"], platform) in history:
                skipped += 1
                continue
            jobs.append((topic, platform))

    slots = schedule_slots(len(jobs), start, gap_hours)
    posts = []
    for (topic, platform), slot in zip(jobs, slots):
        drafted = draft_post(topic, platform, api_key, force_mock=force_mock)
        posts.append({
            "topic": topic["topic"],
            "platform": platform,
            "tone": topic["tone"],
            "link": topic["link"],
            "scheduled_for": slot.isoformat(),
            "scheduled_for_pkt": slot.strftime("%Y-%m-%d %H:%M PKT"),
            "chars": len(drafted["text"]),
            "source": drafted["source"],
            "text": drafted["text"],
        })
        history[history_key(topic["topic"], platform)] = slot.isoformat()

    os.makedirs(out_dir, exist_ok=True)

    schedule_path = os.path.join(out_dir, "schedule.json")
    with open(schedule_path, "w", encoding="utf-8") as fh:
        json.dump(posts, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    drafts_path = os.path.join(out_dir, "drafts.md")
    with open(drafts_path, "w", encoding="utf-8") as fh:
        fh.write("# Scheduled social posts\n\n")
        fh.write("Generated by nz-ai-social-scheduler. "
                 "Posts marked MOCK were written by the offline fallback, "
                 "not by Gemini — review before posting.\n\n")
        for post in posts:
            fh.write("## {0} — {1} ({2})\n\n".format(
                post["scheduled_for_pkt"], post["platform"].title(),
                post["source"].upper()))
            fh.write(post["text"] + "\n\n---\n\n")

    csv_path = os.path.join(out_dir, "posts.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["scheduled_for_pkt", "platform", "topic", "chars",
                         "source", "text"])
        for post in posts:
            writer.writerow([post["scheduled_for_pkt"], post["platform"],
                             post["topic"], post["chars"], post["source"],
                             post["text"]])

    if history_path:
        save_history(history_path, history)

    return {
        "topics": len(topics),
        "posts": len(posts),
        "skipped": skipped,
        "mock_posts": sum(1 for p in posts if p["source"] == "mock"),
        "ai_posts": sum(1 for p in posts if p["source"] == "gemini"),
        "first_slot": posts[0]["scheduled_for_pkt"] if posts else None,
        "last_slot": posts[-1]["scheduled_for_pkt"] if posts else None,
        "schedule_path": schedule_path,
        "drafts_path": drafts_path,
        "csv_path": csv_path,
    }


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Draft AI social posts from a topics CSV and schedule them.")
    parser.add_argument("input", help="topics CSV (columns: topic, platforms, "
                                      "tone, link, hashtags)")
    parser.add_argument("--out", default="out", help="output directory")
    parser.add_argument("--history", default="posted.json",
                        help="history JSON for dedupe (default: posted.json)")
    parser.add_argument("--start", default=None,
                        help="first slot, YYYY-MM-DD or YYYY-MM-DDTHH:MM "
                             "(PKT; default tomorrow 14:00)")
    parser.add_argument("--gap-hours", type=float, default=DEFAULT_GAP_HOURS,
                        help="hours between slots (default 4)")
    parser.add_argument("--limit", type=int, default=0,
                        help="draft only the first N topics")
    parser.add_argument("--mock", action="store_true",
                        help="force the labelled mock generator (no API call)")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    api_key = os.environ.get("NZ_GEMINI_API_KEY", "").strip()
    start = parse_start(args.start) if args.start else default_start()
    if args.gap_hours <= 0:
        print("error: --gap-hours must be positive", file=sys.stderr)
        return 2
    try:
        result = run(args.input, args.out, args.history, start,
                     args.gap_hours, args.limit, api_key,
                     force_mock=args.mock)
    except (OSError, ValueError) as exc:
        print("error: {0}".format(exc), file=sys.stderr)
        return 1
    print("Topics read: {0}".format(result["topics"]))
    print("Posts drafted: {0} ({1} Gemini, {2} mock)".format(
        result["posts"], result["ai_posts"], result["mock_posts"]))
    print("Skipped (already scheduled): {0}".format(result["skipped"]))
    if result["posts"]:
        print("Schedule: {0} -> {1}".format(
            result["first_slot"], result["last_slot"]))
    print("Wrote: {0}, {1}, {2}".format(
        result["schedule_path"], result["drafts_path"], result["csv_path"]))
    if not api_key or args.mock:
        print("Note: NZ_GEMINI_API_KEY not set (or --mock used) — "
              "posts are labelled MOCK. Set the key for real Gemini drafts.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
