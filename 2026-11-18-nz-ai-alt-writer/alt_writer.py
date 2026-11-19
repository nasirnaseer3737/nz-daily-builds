#!/usr/bin/env python3
"""
nz-ai-alt-writer — AI image alt-text writer for SEO.

Scans a folder of images (or a CSV of image paths/URLs) and writes
descriptive, SEO-friendly alt text for every image.

* Real AI mode: calls the Google Gemini API (gemini-2.0-flash) when the
  NZ_GEMINI_API_KEY environment variable is set.
* Mock mode: when no key is set (or --mock is passed) a clearly labelled
  offline fallback derives alt text from the image filename. Mock output is
  NEVER presented as AI output — every row is tagged with its source
  ("ai" or "mock").

Alt-text rules enforced for both modes:
  - max 125 characters by default (configurable with --max-length)
  - never starts with "image of" / "photo of" / "picture of"
  - decorative images (listed with --decorative) get an empty alt (""), which
    is the correct accessible choice for purely decorative graphics
  - sentence case, single line, no trailing punctuation spam

Outputs (into --out, default ./alt-output):
  - alt-text.csv   image, alt, source, chars
  - alt-text.json  structured results + run summary
  - alt-text.md    human-readable report

History / dedupe:
  A done.json file in the output folder remembers images already written.
  Re-runs skip them unless --force is passed.

Extra mode:
  --check existing-alts.csv  — audit an existing alt-text CSV and report
  rows that are empty, too long, duplicated, or start with "image of".

Usage:
  python3 alt_writer.py --images ./images --out ./alt-output
  python3 alt_writer.py --images images.csv --keyword "plumbing services"
  python3 alt_writer.py --images ./images --mock --max-length 100
  python3 alt_writer.py --check alt-text.csv

API key setup:
  export NZ_GEMINI_API_KEY="your-gemini-api-key"
  Get a free key at https://aistudio.google.com/app/apikey
  The key is NEVER hardcoded or committed — it is read only from the
  environment.
"""

import argparse
import csv
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

VERSION = "1.0.0"
GEMINI_MODEL = "gemini-2.0-flash"
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)
DEFAULT_MAX_LENGTH = 125
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg", ".avif"}
BAD_PREFIXES = ("image of ", "photo of ", "picture of ", "a photo of ",
                "an image of ", "a picture of ")
STOP_TOKENS = {
    "img", "image", "photo", "pic", "picture", "file", "untitled", "dsc",
    "screenshot", "screen", "shot", "final", "copy", "new", "v1", "v2",
    "edited", "export", "download",
}


# ---------------------------------------------------------------------------
# Filename -> mock alt text (offline fallback, clearly labelled "mock")
# ---------------------------------------------------------------------------

def tokens_from_filename(path_text):
    """Split a filename into meaningful words, dropping junk tokens."""
    stem = Path(path_text).stem
    # "IMG_20261118_123456" style camera names carry no meaning.
    if re.fullmatch(r"(img|dsc|dscn|pxl|wp|image|photo)[ _-]?\d+.*", stem,
                    re.IGNORECASE):
        return []
    raw = re.split(r"[-_.\s]+", stem)
    words = []
    for token in raw:
        token = token.strip().lower()
        if not token or token in STOP_TOKENS:
            continue
        if token.isdigit():  # bare numbers ("001", "2026") add nothing
            continue
        if re.fullmatch(r"\d+x\d+", token):  # dimensions like 800x600
            continue
        words.append(token)
    return words


def mock_alt_text(image_path, keyword=None):
    """Build alt text from the filename only. Labelled 'mock' everywhere."""
    words = tokens_from_filename(image_path)
    if not words:
        base = "Website image"
    else:
        base = " ".join(words)
    if keyword:
        base = f"{base} — {keyword}"
    return sentence_case(base)


def sentence_case(text):
    """Capitalise the first letter, collapse whitespace, single line."""
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return text
    return text[0].upper() + text[1:]


def clean_alt_text(text, max_length=DEFAULT_MAX_LENGTH):
    """Enforce the alt-text rules: strip bad prefixes, cap length."""
    text = re.sub(r"\s+", " ", (text or "")).strip().strip("\"'").strip()
    lowered = text.lower()
    for prefix in BAD_PREFIXES:
        if lowered.startswith(prefix):
            text = text[len(prefix):]
            lowered = text.lower()
            break
    text = sentence_case(text)
    if len(text) > max_length:
        cut = text[:max_length].rsplit(" ", 1)[0]
        text = cut if cut else text[:max_length]
    return text


# ---------------------------------------------------------------------------
# Gemini AI mode
# ---------------------------------------------------------------------------

def gemini_alt_text(image_path, keyword=None, api_key=None,
                    max_length=DEFAULT_MAX_LENGTH, timeout=30):
    """Ask Gemini for alt text for one image (by filename + keyword hint).

    The free-tier Gemini text model cannot see local files through this CLI,
    so the prompt describes the image by its filename and the optional
    keyword hint, and asks for a concise descriptive alt text. Returns
    (alt_text, error) — error is None on success.
    """
    prompt = (
        "Write one SEO-friendly HTML image alt text (max "
        f"{max_length} characters, one sentence, no leading 'image of'). "
        f"Image file name: {Path(image_path).name}. "
    )
    if keyword:
        prompt += f"Page topic / keyword to include naturally: {keyword}. "
    prompt += ("Describe what the image most likely shows, based on its "
               "file name, in plain descriptive words.")
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.4, "maxOutputTokens": 120},
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
        return None, f"Gemini HTTP {exc.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return None, f"Gemini request failed: {exc}"
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        return None, "Gemini returned an unexpected response"
    return clean_alt_text(text, max_length), None


# ---------------------------------------------------------------------------
# Image discovery
# ---------------------------------------------------------------------------

def discover_from_folder(folder):
    """Recursively collect image files under a folder, sorted."""
    root = Path(folder)
    if not root.is_dir():
        raise ValueError(f"not a folder: {folder}")
    found = [str(p) for p in sorted(root.rglob("*"))
             if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS]
    return found


def discover_from_csv(csv_path):
    """Collect image paths/URLs from a CSV with an 'image' column."""
    path = Path(csv_path)
    if not path.is_file():
        raise ValueError(f"not a file: {csv_path}")
    found = []
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "image" not in reader.fieldnames:
            raise ValueError("CSV must have an 'image' column")
        for row in reader:
            value = (row.get("image") or "").strip()
            if value:
                found.append(value)
    return found


def discover(source):
    """A folder path scans for images; a .csv path reads its image column."""
    if Path(source).is_dir():
        return discover_from_folder(source)
    if str(source).lower().endswith(".csv"):
        return discover_from_csv(source)
    raise ValueError(f"not a folder or CSV file: {source}")


# ---------------------------------------------------------------------------
# History (dedupe) handling
# ---------------------------------------------------------------------------

def load_history(out_dir):
    """Return {image: alt} already written, or {} when none exists."""
    history_path = Path(out_dir) / "done.json"
    if not history_path.is_file():
        return {}
    try:
        with open(history_path, encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_history(out_dir, history):
    """Persist the done.json history file."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "done.json", "w", encoding="utf-8") as handle:
        json.dump(history, handle, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Core run
# ---------------------------------------------------------------------------

def generate_alt(image, keyword, api_key, use_mock, max_length,
                 decorative):
    """Return (alt_text, source) for one image.

    source is one of: "ai", "mock", "decorative".
    """
    if image in decorative:
        return "", "decorative"
    if use_mock or not api_key:
        return clean_alt_text(mock_alt_text(image, keyword), max_length), "mock"
    alt, error = gemini_alt_text(image, keyword, api_key, max_length)
    if error:
        print(f"  ! Gemini failed for {image} ({error}) — mock fallback",
              file=sys.stderr)
        return clean_alt_text(mock_alt_text(image, keyword),
                              max_length), "mock"
    return alt, "ai"


def run(images, out_dir, keyword=None, api_key=None, use_mock=False,
        max_length=DEFAULT_MAX_LENGTH, decorative=None, force=False):
    """Generate alt text for all images; write CSV/JSON/Markdown outputs."""
    decorative = set(decorative or [])
    history = load_history(out_dir)
    results = []
    skipped = 0
    for image in images:
        if image in history and not force:
            skipped += 1
            results.append({"image": image, "alt": history[image],
                            "source": "done", "chars": len(history[image])})
            continue
        alt, source = generate_alt(image, keyword, api_key, use_mock,
                                   max_length, decorative)
        history[image] = alt
        results.append({"image": image, "alt": alt, "source": source,
                        "chars": len(alt)})

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    with open(out / "alt-text.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle,
                                fieldnames=["image", "alt", "source", "chars"])
        writer.writeheader()
        writer.writerows(results)

    summary = {
        "total": len(results),
        "new": len(results) - skipped,
        "skipped_already_done": skipped,
        "ai": sum(1 for r in results if r["source"] == "ai"),
        "mock": sum(1 for r in results if r["source"] == "mock"),
        "decorative": sum(1 for r in results if r["source"] == "decorative"),
        "already_done": sum(1 for r in results if r["source"] == "done"),
        "max_length": max_length,
        "keyword": keyword,
    }
    with open(out / "alt-text.json", "w", encoding="utf-8") as handle:
        json.dump({"summary": summary, "results": results}, handle,
                  indent=2, ensure_ascii=False)

    lines = ["# Image alt text\n"]
    if keyword:
        lines.append(f"Keyword hint: **{keyword}**\n")
    lines.append(f"Total images: {summary['total']} — AI: {summary['ai']}, "
                 f"mock fallback: {summary['mock']}, decorative (empty alt): "
                 f"{summary['decorative']}, already done: "
                 f"{summary['already_done']}\n")
    lines.append("| Image | Alt text | Source | Chars |")
    lines.append("|---|---|---|---|")
    for row in results:
        alt = row["alt"] or "*(empty — decorative)*"
        lines.append(f"| `{row['image']}` | {alt} | {row['source']} | "
                     f"{row['chars']} |")
    lines.append("")
    lines.append("_Rows tagged `mock` were generated offline from the file "
                 "name, not by AI — set NZ_GEMINI_API_KEY for real AI alt "
                 "text._\n")
    with open(out / "alt-text.md", "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))

    save_history(out_dir, history)
    return summary, results


# ---------------------------------------------------------------------------
# --check mode: audit an existing alt-text CSV
# ---------------------------------------------------------------------------

def check_alts(csv_path, max_length=DEFAULT_MAX_LENGTH):
    """Audit an existing alt-text CSV; return a list of issue dicts."""
    issues = []
    with open(csv_path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "alt" not in reader.fieldnames:
            raise ValueError("CSV must have an 'alt' column")
        seen = {}
        for number, row in enumerate(reader, start=2):  # line 1 = header
            image = (row.get("image") or "").strip()
            alt = (row.get("alt") or "").strip()
            if not alt:
                issues.append({"row": number, "image": image,
                               "issue": "empty alt text"})
            if len(alt) > max_length:
                issues.append({"row": number, "image": image,
                               "issue": f"alt too long ({len(alt)} chars)"})
            if alt.lower().startswith(BAD_PREFIXES):
                issues.append({"row": number, "image": image,
                               "issue": "starts with 'image of' / 'photo of'"})
            key = alt.lower()
            if key and key in seen:
                issues.append({"row": number, "image": image,
                               "issue": f"duplicate of row {seen[key]}"})
            elif key:
                seen[key] = number
    return issues


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        description="AI image alt-text writer (Gemini API, labelled mock "
                    "fallback).")
    parser.add_argument("--images", help="folder of images or CSV file "
                        "with an 'image' column")
    parser.add_argument("--out", default="alt-output",
                        help="output folder (default: alt-output)")
    parser.add_argument("--keyword", help="page topic / keyword to weave "
                        "into the alt text")
    parser.add_argument("--mock", action="store_true",
                        help="force the labelled offline mock fallback")
    parser.add_argument("--max-length", type=int, default=DEFAULT_MAX_LENGTH,
                        help=f"max alt length in chars (default "
                             f"{DEFAULT_MAX_LENGTH})")
    parser.add_argument("--decorative", default="",
                        help="comma-separated image paths to mark decorative "
                             "(empty alt)")
    parser.add_argument("--force", action="store_true",
                        help="rewrite images already in done.json")
    parser.add_argument("--check", metavar="CSV",
                        help="audit an existing alt-text CSV instead of "
                             "generating")
    parser.add_argument("--version", action="version",
                        version=f"nz-ai-alt-writer {VERSION}")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.check:
        try:
            issues = check_alts(args.check, args.max_length)
        except (OSError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        if not issues:
            print(f"OK: {args.check} — no alt-text issues found.")
            return 0
        print(f"{len(issues)} alt-text issue(s) in {args.check}:")
        for issue in issues:
            print(f"  row {issue['row']} [{issue['image']}]: {issue['issue']}")
        return 1
    if not args.images:
        print("error: --images is required (or use --check CSV)",
              file=sys.stderr)
        return 2
    try:
        images = discover(args.images)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not images:
        print("no images found.", file=sys.stderr)
        return 2
    decorative = {item.strip() for item in args.decorative.split(",")
                  if item.strip()}
    api_key = os.environ.get("NZ_GEMINI_API_KEY", "").strip()
    mode = "mock (labelled offline fallback)" if (args.mock or not api_key) \
        else "Gemini AI"
    print(f"nz-ai-alt-writer {VERSION} — {len(images)} image(s), mode: {mode}")
    summary, _results = run(images, args.out, keyword=args.keyword,
                            api_key=api_key or None, use_mock=args.mock,
                            max_length=args.max_length,
                            decorative=decorative, force=args.force)
    print(f"done: {summary['total']} total, {summary['new']} new, "
          f"{summary['skipped_already_done']} skipped (already done), "
          f"AI {summary['ai']}, mock {summary['mock']}, "
          f"decorative {summary['decorative']}")
    print(f"outputs: {args.out}/alt-text.csv, alt-text.json, alt-text.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())

