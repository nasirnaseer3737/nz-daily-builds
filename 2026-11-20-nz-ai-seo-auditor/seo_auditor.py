#!/usr/bin/env python3
"""
nz-ai-seo-auditor — AI-powered on-page SEO auditor.

Reads one or more HTML pages (local files and/or live URLs) and audits them
against on-page SEO best practice:

  * title tag present + length 30-60 chars
  * meta description present + length 120-160 chars
  * exactly one H1, sensible heading order (no skipped levels)
  * images: every <img> has non-empty alt text
  * canonical link present, Open Graph + Twitter Card tags present
  * JSON-LD schema.org markup present
  * internal / external link counts, broken-looking hrefs (#, javascript:)
  * word count, target-keyword usage in title / H1 / body + density
  * readability estimate (Flesch reading-ease approximation)

Each check is pass / warn / fail and rolls up into a 0-100 score with a
grade (A/B/C/D/F). The tool then asks Gemini (gemini-2.0-flash) for short,
concrete fix suggestions for the failed checks. When no API key is set
(NZ_GEMINI_API_KEY) it uses a clearly labelled OFFLINE MOCK fallback that
builds the same suggestions from the rule results — the mock never pretends
to be AI output.

Outputs (into --out, default ./audit-output/):
  report.json  — machine-readable results for every page
  report.md    — human-readable report with scores and fix suggestions

Usage:
  python3 seo_auditor.py page1.html page2.html --keyword "wordpress developer"
  python3 seo_auditor.py https://example.com --keyword "plumber chicago"
  python3 seo_auditor.py --folder sample_pages --keyword "seo audit"
  python3 seo_auditor.py --list pages.txt --keyword "local seo"

Only the Python standard library is used. Set NZ_GEMINI_API_KEY to enable
real AI suggestions; without it the mock fallback is used and labelled.
"""

import argparse
import html as html_lib
import json
import os
import re
import sys
import urllib.request
import urllib.error
from html.parser import HTMLParser
from pathlib import Path

VERSION = "1.0.0"
GEMINI_MODEL = "gemini-2.0-flash"
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)
DEFAULT_TIMEOUT = 15

# ---------------------------------------------------------------------------
# HTML parsing
# ---------------------------------------------------------------------------

VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}


class PageData:
    """Everything the audit needs from one HTML document."""

    def __init__(self):
        self.title = ""
        self.meta_description = ""
        self.meta = {}            # name/property -> content
        self.canonical = ""
        self.h1 = []
        self.headings = []        # list of (level, text)
        self.images = []          # list of (src, alt or None)
        self.links = []           # list of (href, text)
        self.has_json_ld = False
        self.body_text = ""
        self.raw_length = 0


class _PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.data = PageData()
        self._in_title = False
        self._in_body = False
        self._in_script_style = False
        self._heading_level = 0
        self._heading_buf = []
        self._link_href = None
        self._link_buf = []
        self._body_chunks = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("script", "style"):
            self._in_script_style = True
            if tag == "script" and attrs.get("type") == "application/ld+json":
                self.data.has_json_ld = True
            return
        if tag == "title":
            self._in_title = True
        elif tag == "body":
            self._in_body = True
        elif tag == "meta":
            name = attrs.get("name") or attrs.get("property") or ""
            content = attrs.get("content", "")
            if name:
                self.data.meta[name.lower()] = content
            if name.lower() == "description":
                self.data.meta_description = content
        elif tag == "link" and attrs.get("rel") == "canonical":
            self.data.canonical = attrs.get("href", "")
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._heading_level = int(tag[1])
            self._heading_buf = []
        elif tag == "img":
            self.data.images.append((attrs.get("src", ""), attrs.get("alt")))
        elif tag == "a":
            self._link_href = attrs.get("href", "")
            self._link_buf = []

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._in_script_style = False
        elif tag == "title":
            self._in_title = False
        elif tag == "body":
            self._in_body = False
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6") and self._heading_level:
            text = " ".join("".join(self._heading_buf).split())
            self.data.headings.append((self._heading_level, text))
            if self._heading_level == 1:
                self.data.h1.append(text)
            self._heading_level = 0
        elif tag == "a" and self._link_href is not None:
            text = " ".join("".join(self._link_buf).split())
            self.data.links.append((self._link_href, text))
            self._link_href = None

    def handle_data(self, text):
        if self._in_script_style:
            return
        if self._in_title:
            self.data.title += text
        if self._heading_level:
            self._heading_buf.append(text)
        if self._link_href is not None:
            self._link_buf.append(text)
        if self._in_body:
            self._body_chunks.append(text)

    def finish(self):
        self.data.title = " ".join(self.data.title.split())
        self.data.meta_description = " ".join(
            self.data.meta_description.split())
        self.data.body_text = " ".join("".join(self._body_chunks).split())
        return self.data


def parse_html(html_text):
    """Parse an HTML string into a PageData object."""
    parser = _PageParser()
    parser.feed(html_text)
    parser.close()
    page = parser.finish()
    page.raw_length = len(html_text)
    return page


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def word_count(text):
    return len(re.findall(r"[A-Za-z0-9']+", text))


def count_syllables(word):
    """Rough syllable count for readability estimation."""
    word = word.lower().strip()
    word = re.sub(r"[^a-z]", "", word)
    if not word:
        return 0
    if len(word) <= 3:
        return 1
    word = re.sub(r"(?:[^laeiouy]es|ed|[^laeiouy]e)$", "", word)
    word = re.sub(r"^y", "", word)
    groups = re.findall(r"[aeiouy]+", word)
    return max(1, len(groups))


def flesch_reading_ease(text):
    """Approximate Flesch reading-ease score (0-100, higher = easier)."""
    words = re.findall(r"[A-Za-z0-9']+", text)
    if len(words) < 10:
        return None
    sentences = [s for s in re.split(r"[.!?]+", text) if s.strip()]
    sentences = sentences or [text]
    syllables = sum(count_syllables(w) for w in words)
    avg_words = len(words) / len(sentences)
    avg_syll = syllables / len(words)
    score = 206.835 - 1.015 * avg_words - 84.6 * avg_syll
    return round(max(0.0, min(100.0, score)), 1)


def keyword_stats(text, keyword):
    """Return (occurrences, density %) of keyword (case-insensitive)."""
    if not keyword:
        return 0, 0.0
    words = word_count(text)
    if words == 0:
        return 0, 0.0
    pattern = re.compile(re.escape(keyword), re.IGNORECASE)
    occ = len(pattern.findall(text))
    return occ, round(occ / words * 100, 2)


# ---------------------------------------------------------------------------
# Audit checks
# ---------------------------------------------------------------------------

def check(title, status, detail, weight=1, fix=""):
    return {
        "check": title, "status": status, "detail": detail,
        "weight": weight, "fix": fix,
    }


def audit_page(page, source, keyword=""):
    """Run all checks on a parsed page. Returns a result dict."""
    checks = []
    title = page.title
    if not title:
        checks.append(check("Title tag", "fail", "No <title> tag found.",
                            3, "Add a unique <title> of 30-60 characters."))
    elif len(title) < 30:
        checks.append(check("Title tag", "warn",
                            f"Title is {len(title)} chars (too short, aim 30-60).",
                            2, "Expand the title to 30-60 chars, lead with the keyword."))
    elif len(title) > 60:
        checks.append(check("Title tag", "warn",
                            f"Title is {len(title)} chars (too long, aim 30-60).",
                            2, "Trim the title to under 60 chars; keep the keyword near the front."))
    else:
        checks.append(check("Title tag", "pass",
                            f"Title is {len(title)} chars.", 1))

    desc = page.meta_description
    if not desc:
        checks.append(check("Meta description", "fail", "No meta description.",
                            3, "Add a 120-160 char meta description with a call to action."))
    elif len(desc) < 120:
        checks.append(check("Meta description", "warn",
                            f"Meta description is {len(desc)} chars (aim 120-160).",
                            2, "Expand the meta description to 120-160 chars."))
    elif len(desc) > 160:
        checks.append(check("Meta description", "warn",
                            f"Meta description is {len(desc)} chars (aim 120-160).",
                            2, "Trim the meta description to under 160 chars."))
    else:
        checks.append(check("Meta description", "pass",
                            f"Meta description is {len(desc)} chars.", 1))

    if len(page.h1) == 0:
        checks.append(check("H1 heading", "fail", "No H1 on the page.",
                            3, "Add exactly one H1 that states the page topic."))
    elif len(page.h1) > 1:
        checks.append(check("H1 heading", "warn",
                            f"{len(page.h1)} H1 tags found (aim for exactly one).",
                            2, "Keep one H1; demote the others to H2."))
    else:
        checks.append(check("H1 heading", "pass",
                            f'One H1: "{page.h1[0][:60]}"', 1))

    # Heading order: no skipped levels (H1 -> H3 with no H2).
    levels = [lvl for lvl, _ in page.headings]
    skipped = any(levels[i + 1] > levels[i] + 1 for i in range(len(levels) - 1))
    if skipped:
        checks.append(check("Heading order", "warn",
                            "Heading levels are skipped (e.g. H1 straight to H3).",
                            1, "Use headings in order: H1, then H2, then H3."))
    else:
        checks.append(check("Heading order", "pass",
                            f"{len(page.headings)} headings in order.", 1))

    missing_alt = [src for src, alt in page.images if alt is None or not alt.strip()]
    if page.images and missing_alt:
        checks.append(check("Image alt text", "fail",
                            f"{len(missing_alt)} of {len(page.images)} images "
                            "have no alt text.",
                            2, "Write descriptive alt text (under 125 chars) for every image."))
    elif page.images:
        checks.append(check("Image alt text", "pass",
                            f"All {len(page.images)} images have alt text.", 1))
    else:
        checks.append(check("Image alt text", "pass",
                            "No images on the page.", 1))

    if not page.canonical:
        checks.append(check("Canonical URL", "warn", "No canonical link tag.",
                            1, "Add <link rel=\"canonical\" href=\"...\"> with the preferred URL."))
    else:
        checks.append(check("Canonical URL", "pass",
                            f"Canonical set: {page.canonical[:60]}", 1))

    og_missing = [t for t in ("og:title", "og:description", "og:image")
                  if t not in page.meta]
    tw_missing = [t for t in ("twitter:card", "twitter:title")
                  if t not in page.meta]
    if og_missing or tw_missing:
        missing = ", ".join(og_missing + tw_missing)
        checks.append(check("Social tags (OG/Twitter)", "warn",
                            f"Missing social tags: {missing}.",
                            1, "Add Open Graph + Twitter Card tags so shares look right."))
    else:
        checks.append(check("Social tags (OG/Twitter)", "pass",
                            "Open Graph and Twitter Card tags present.", 1))

    if page.has_json_ld:
        checks.append(check("Schema.org markup", "pass",
                            "JSON-LD structured data found.", 1))
    else:
        checks.append(check("Schema.org markup", "warn",
                            "No JSON-LD structured data found.",
                            1, "Add JSON-LD schema (e.g. LocalBusiness, Article or WebPage)."))

    words = word_count(page.body_text)
    if words < 300:
        checks.append(check("Content length", "warn",
                            f"Only {words} words of body text (aim 300+).",
                            2, "Add useful content — aim for at least 300 words on the topic."))
    else:
        checks.append(check("Content length", "pass",
                            f"{words} words of body text.", 1))

    internal = [h for h, _ in page.links
                if h.startswith("/") or h.startswith("#") or not h.startswith("http")]
    external = [h for h, _ in page.links if h.startswith("http")]
    broken = [h for h, _ in page.links
              if h.strip() in ("", "#") or h.startswith("javascript:")]
    if broken:
        checks.append(check("Links", "warn",
                            f"{len(broken)} placeholder/broken-looking links "
                            f"({len(internal)} internal, {len(external)} external).",
                            1, "Fix or remove placeholder links (#, javascript:)."))
    else:
        checks.append(check("Links", "pass",
                            f"{len(internal)} internal, {len(external)} external links.", 1))

    ease = flesch_reading_ease(page.body_text)
    if ease is None:
        checks.append(check("Readability", "warn",
                            "Too little text to judge readability.", 1,
                            "Add more body text."))
    elif ease < 50:
        checks.append(check("Readability", "warn",
                            f"Flesch reading ease {ease} (hard to read, aim 60+).",
                            1, "Shorten sentences and use simpler words."))
    else:
        checks.append(check("Readability", "pass",
                            f"Flesch reading ease {ease}.", 1))

    kw_detail = ""
    if keyword:
        occ, density = keyword_stats(page.body_text, keyword)
        in_title = keyword.lower() in title.lower()
        in_h1 = any(keyword.lower() in h.lower() for h in page.h1)
        kw_detail = (f'"{keyword}" appears {occ}x in body '
                     f"(density {density}%), "
                     f"in title: {'yes' if in_title else 'no'}, "
                     f"in H1: {'yes' if in_h1 else 'no'}.")
        if occ == 0:
            checks.append(check("Target keyword", "fail",
                                kw_detail, 3,
                                f'Use "{keyword}" in the title, H1 and naturally in the body.'))
        elif not in_title or not in_h1:
            checks.append(check("Target keyword", "warn", kw_detail, 2,
                                f'Put "{keyword}" in the title and the H1.'))
        else:
            checks.append(check("Target keyword", "pass", kw_detail, 1))

    # Score: weighted — pass = full weight, warn = half, fail = 0.
    total_weight = sum(c["weight"] for c in checks)
    earned = sum(c["weight"] for c in checks if c["status"] == "pass")
    earned += sum(c["weight"] * 0.5 for c in checks if c["status"] == "warn")
    score = round(earned / total_weight * 100) if total_weight else 0
    grade = "A" if score >= 90 else "B" if score >= 75 else \
        "C" if score >= 60 else "D" if score >= 40 else "F"

    fails = [c for c in checks if c["status"] == "fail"]
    warns = [c for c in checks if c["status"] == "warn"]

    return {
        "source": source,
        "keyword": keyword,
        "score": score,
        "grade": grade,
        "word_count": words,
        "readability": ease,
        "images": len(page.images),
        "images_missing_alt": len(missing_alt),
        "links_internal": len(internal),
        "links_external": len(external),
        "checks": checks,
        "failed_checks": [c["check"] for c in fails],
        "warning_checks": [c["check"] for c in warns],
        "fixes": [c["fix"] for c in fails + warns if c["fix"]],
    }


# ---------------------------------------------------------------------------
# AI fix suggestions (Gemini) + labelled mock fallback
# ---------------------------------------------------------------------------

def mock_suggestions(result):
    """OFFLINE MOCK fallback — rule-based suggestions, clearly labelled."""
    suggestions = []
    for fix in result["fixes"]:
        suggestions.append(fix)
    if result["score"] >= 90:
        suggestions.append(
            "Page is in good shape — re-check after the next content update.")
    return {
        "mode": "MOCK (offline fallback — no AI API key set)",
        "suggestions": suggestions,
    }


def gemini_suggestions(result, api_key):
    """Ask Gemini for short concrete fix suggestions for failed checks."""
    failed = result["failed_checks"] + result["warning_checks"]
    if not failed:
        return {"mode": "Gemini (real AI)", "suggestions": [
            "No failed checks — page is in good shape."]}
    prompt = (
        "You are an SEO consultant. This page scored "
        f"{result['score']}/100 (grade {result['grade']}) in an on-page SEO audit. "
        f"Target keyword: {result['keyword'] or 'none'}. "
        "Failed/warning checks: " + "; ".join(failed) + ". "
        "Give one short, concrete fix per check (max 25 words each), "
        "as a plain list, no intro text."
    )
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 600},
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{GEMINI_URL}?key={api_key}",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        lines = [ln.strip(" -•\t") for ln in text.strip().splitlines()
                 if ln.strip()]
        return {"mode": "Gemini (real AI)", "suggestions": lines}
    except Exception as exc:  # network/API failure -> labelled mock
        fallback = mock_suggestions(result)
        fallback["mode"] = (
            f"MOCK (offline fallback — Gemini call failed: {exc})")
        return fallback


def get_suggestions(result, api_key):
    if api_key:
        return gemini_suggestions(result, api_key)
    return mock_suggestions(result)


# ---------------------------------------------------------------------------
# Input loading
# ---------------------------------------------------------------------------

def fetch_url(url):
    req = urllib.request.Request(url, headers={"User-Agent": "nz-ai-seo-auditor/1.0"})
    with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")


def load_source(source):
    """Return (html, error). Local file path wins; else treat as URL."""
    path = Path(source)
    if path.is_file():
        return path.read_text(encoding="utf-8", errors="replace"), None
    if source.startswith("http://") or source.startswith("https://"):
        try:
            return fetch_url(source), None
        except (urllib.error.URLError, OSError, ValueError) as exc:
            return None, f"Could not fetch URL: {exc}"
    return None, "Not a file and not an http(s) URL."


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def render_markdown(results, api_key_used):
    lines = ["# NZ AI SEO Audit Report", ""]
    lines.append(f"Pages audited: **{len(results)}**  |  "
                 f"AI suggestions: **{'Gemini (real AI)' if api_key_used else 'MOCK (offline fallback)'}**")
    lines.append("")
    for r in results:
        lines.append(f"## {r['source']} — {r['score']}/100 (Grade {r['grade']})")
        lines.append("")
        lines.append(f"- Words: {r['word_count']}  |  Readability (Flesch): "
                     f"{r['readability'] if r['readability'] is not None else 'n/a'}")
        lines.append(f"- Images: {r['images']} ({r['images_missing_alt']} missing alt)  |  "
                     f"Links: {r['links_internal']} internal, {r['links_external']} external")
        lines.append("")
        lines.append("| Check | Status | Detail |")
        lines.append("|---|---|---|")
        for c in r["checks"]:
            lines.append(f"| {c['check']} | {c['status'].upper()} | {c['detail']} |")
        lines.append("")
        ai = r.get("ai_suggestions", {})
        lines.append(f"### Fix suggestions ({ai.get('mode', 'n/a')})")
        lines.append("")
        for s in ai.get("suggestions", []):
            lines.append(f"- {s}")
        lines.append("")
    return "\n".join(lines)


def audit_sources(sources, keyword, out_dir, api_key):
    results = []
    errors = []
    for source in sources:
        html_text, err = load_source(source)
        if err:
            errors.append({"source": source, "error": err})
            continue
        page = parse_html(html_text)
        result = audit_page(page, source, keyword)
        result["ai_suggestions"] = get_suggestions(result, api_key)
        results.append(result)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = {
        "tool": "nz-ai-seo-auditor",
        "version": VERSION,
        "keyword": keyword,
        "ai_mode": "Gemini (real AI)" if api_key else "MOCK (offline fallback)",
        "pages": results,
        "errors": errors,
    }
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out / "report.md").write_text(
        render_markdown(results, bool(api_key)), encoding="utf-8")
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def collect_sources(args):
    sources = list(args.sources)
    if args.list:
        for line in Path(args.list).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                sources.append(line)
    if args.folder:
        folder = Path(args.folder)
        for path in sorted(folder.glob("*.html")) + sorted(folder.glob("*.htm")):
            sources.append(str(path))
    return sources


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="AI-powered on-page SEO auditor (Gemini with labelled mock fallback).")
    parser.add_argument("sources", nargs="*", help="HTML files and/or URLs to audit")
    parser.add_argument("--keyword", default="", help="Target keyword to check")
    parser.add_argument("--list", help="Text file with one source per line")
    parser.add_argument("--folder", help="Folder of .html files to audit")
    parser.add_argument("--out", default="audit-output",
                        help="Output folder for report.json / report.md")
    args = parser.parse_args(argv)

    sources = collect_sources(args)
    if not sources:
        parser.error("No pages to audit — pass files, URLs, --list or --folder.")

    api_key = os.environ.get("NZ_GEMINI_API_KEY", "").strip()
    report = audit_sources(sources, args.keyword, args.out, api_key)

    for r in report["pages"]:
        mode = r["ai_suggestions"]["mode"]
        print(f"{r['source']}: {r['score']}/100 (Grade {r['grade']}) — "
              f"{len(r['failed_checks'])} failed, {len(r['warning_checks'])} warnings "
              f"[{mode}]")
    for e in report["errors"]:
        print(f"ERROR {e['source']}: {e['error']}", file=sys.stderr)
    print(f"Report written to {args.out}/report.json and {args.out}/report.md")
    return 0 if not report["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
