#!/usr/bin/env python3
"""NZ AI Lead Scorer — score CSV leads 0-100 and rank them for outreach.

Lead-automation tool (daily build 2026-11-14). Two scoring layers:

1. Rule-based scoring (always runs, fully offline):
   email quality, phone, website, company size, industry fit, lead
   source, budget signal and TCPA consent flag.
2. AI rationale (optional, real API): when the NZ_GEMINI_API_KEY
   environment variable is set, each lead's top reasons are sent to
   Google Gemini (free tier) which returns a one-line outreach angle.
   Without a key the tool runs in clearly labelled MOCK mode and uses
   a deterministic template rationale instead — it never pretends
   the mock text came from an AI model.

Usage:
    python3 lead_scorer.py leads.csv [--out scored.csv] [--top 10]
    python3 lead_scorer.py --demo            # score the bundled sample
    python3 lead_scorer.py --help

Input CSV columns (headers, case-insensitive):
    name, email, phone, company, website, industry, employees,
    source, budget, consent

    * consent: "yes" / "no" — TCPA consent to contact. Leads without
      consent are scored but flagged DO-NOT-CONTACT and never ranked
      for outreach.
    * budget: free text or a number, e.g. "5000" or "$5k/mo".
    * employees: number, e.g. "25" or "11-50".

Output: a scored CSV (same rows + score, grade, reasons, ai_angle,
contact_ok) sorted by score descending, plus a console summary.

No API key is ever hardcoded or written to disk. Only the Python
standard library is used; no pip installs needed.
"""

import argparse
import csv
import json
import os
import re
import sys
import urllib.error
import urllib.request

VERSION = "1.0.0"

FREE_EMAIL_DOMAINS = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com",
    "icloud.com", "protonmail.com", "mail.com", "gmx.com", "yandex.com",
}

# Industries the user's web-dev / AI-automation business serves best.
TARGET_INDUSTRIES = {
    "ecommerce", "e-commerce", "real estate", "healthcare", "dental",
    "legal", "law", "home services", "plumbing", "hvac", "roofing",
    "saas", "fitness", "restaurant", "hospitality", "education",
    "finance", "insurance", "automotive", "construction",
}

SOURCE_SCORES = {
    "referral": 15,
    "website form": 12,
    "website": 12,
    "inbound": 12,
    "facebook lead ad": 10,
    "facebook": 10,
    "google ads": 10,
    "quiz funnel": 10,
    "trade show": 8,
    "purchased list": 5,
    "cold list": 2,
    "scraped": 0,
}

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")
PHONE_DIGITS_RE = re.compile(r"\D")
URL_RE = re.compile(r"^(https?://)?([\w-]+\.)+[\w-]{2,}(/\S*)?$", re.I)
BUDGET_RE = re.compile(r"[\d,]+(?:\.\d+)?")

GEMINI_MODEL = "gemini-2.0-flash"
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)


# ---------------------------------------------------------------- scoring

def _clean(value):
    return (value or "").strip()


def _domain(email):
    return email.rsplit("@", 1)[-1].lower() if "@" in email else ""


def _employees_number(raw):
    """Parse '25', '11-50', '50+' into an int (upper bound of a range)."""
    raw = _clean(raw)
    if not raw:
        return None
    nums = [int(n.replace(",", "")) for n in re.findall(r"\d[\d,]*", raw)]
    if not nums:
        return None
    return max(nums)


def _budget_number(raw):
    """Parse '$5k/mo' / '5000' into a rough USD number (k = thousands)."""
    raw = _clean(raw).lower()
    if not raw:
        return None
    match = BUDGET_RE.search(raw)
    if not match:
        return None
    value = float(match.group(0).replace(",", ""))
    if "k" in raw:
        value *= 1000
    return value


def score_lead(lead):
    """Score one lead dict. Returns (score 0-100, grade, reasons list,
    contact_ok bool)."""
    reasons = []
    score = 0

    email = _clean(lead.get("email"))
    if email and EMAIL_RE.match(email):
        domain = _domain(email)
        if domain in FREE_EMAIL_DOMAINS:
            score += 5
            reasons.append("free email domain (+5)")
        else:
            score += 15
            reasons.append("business email domain (+15)")
    elif email:
        score -= 10
        reasons.append("invalid email (-10)")
    else:
        reasons.append("no email (+0)")

    phone = PHONE_DIGITS_RE.sub("", _clean(lead.get("phone")))
    if len(phone) >= 10:
        score += 10
        reasons.append("reachable phone (+10)")
    elif phone:
        score += 3
        reasons.append("partial phone (+3)")
    else:
        reasons.append("no phone (+0)")

    website = _clean(lead.get("website"))
    if website and URL_RE.match(website):
        score += 10
        reasons.append("has website (+10)")
    elif website:
        score += 2
        reasons.append("website looks malformed (+2)")
    else:
        reasons.append("no website (+0)")

    employees = _employees_number(lead.get("employees"))
    if employees is None:
        reasons.append("company size unknown (+0)")
    elif employees <= 10:
        score += 5
        reasons.append("small team 1-10 (+5)")
    elif employees <= 50:
        score += 10
        reasons.append("team 11-50 (+10)")
    elif employees <= 200:
        score += 15
        reasons.append("team 51-200 (+15)")
    else:
        score += 10
        reasons.append("large team 200+ (+10)")

    industry = _clean(lead.get("industry")).lower()
    if industry in TARGET_INDUSTRIES:
        score += 15
        reasons.append(f"target industry '{industry}' (+15)")
    elif industry:
        score += 5
        reasons.append(f"non-target industry '{industry}' (+5)")
    else:
        reasons.append("industry unknown (+0)")

    source = _clean(lead.get("source")).lower()
    source_points = SOURCE_SCORES.get(source, 5 if source else 0)
    score += source_points
    reasons.append(f"source '{source or 'unknown'}' (+{source_points})")

    budget = _budget_number(lead.get("budget"))
    if budget is None:
        reasons.append("no budget signal (+0)")
    elif budget >= 1000:
        score += 15
        reasons.append("budget >= $1000 (+15)")
    else:
        score += 8
        reasons.append("budget stated, under $1000 (+8)")

    consent = _clean(lead.get("consent")).lower()
    contact_ok = consent in ("yes", "y", "true", "1", "opt-in", "opt in")
    if contact_ok:
        score += 5
        reasons.append("TCPA consent given (+5)")
    else:
        reasons.append("NO consent — do not contact (+0)")

    score = max(0, min(100, score))
    grade = "A" if score >= 80 else "B" if score >= 60 else "C" if score >= 40 else "D"
    return score, grade, reasons, contact_ok


# ---------------------------------------------------------------- AI angle

def mock_angle(lead, score, grade, reasons):
    """Deterministic offline rationale. Always labelled MOCK."""
    industry = _clean(lead.get("industry")) or "their business"
    company = _clean(lead.get("company")) or "this lead"
    top = reasons[0].split(" (")[0] if reasons else "general fit"
    return (
        f"[MOCK — no API key] Pitch {company} on a {industry} website / "
        f"automation upgrade; strongest signal: {top} (grade {grade}, {score}/100)."
    )


def gemini_angle(lead, score, grade, reasons, api_key):
    """Ask Gemini for a one-line outreach angle. Returns None on any
    failure so the caller can fall back to the labelled mock."""
    prompt = (
        "You write outreach angles for a web developer selling websites "
        "and AI automation. Given this lead, reply with ONE short sentence "
        "(max 25 words) naming the best pitch angle. No greeting, no "
        "explanation.\n"
        f"Company: {_clean(lead.get('company')) or 'unknown'}\n"
        f"Industry: {_clean(lead.get('industry')) or 'unknown'}\n"
        f"Employees: {_clean(lead.get('employees')) or 'unknown'}\n"
        f"Budget: {_clean(lead.get('budget')) or 'unknown'}\n"
        f"Source: {_clean(lead.get('source')) or 'unknown'}\n"
        f"Score: {score}/100 (grade {grade}). Top signals: "
        + "; ".join(reasons[:3])
    )
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": 80, "temperature": 0.7},
    }).encode("utf-8")
    request = urllib.request.Request(
        f"{GEMINI_URL}?key={api_key}",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
        text = (
            data["candidates"][0]["content"]["parts"][0]["text"]
            .strip()
            .splitlines()[0]
        )
        return f"[AI — Gemini {GEMINI_MODEL}] {text}"
    except (urllib.error.URLError, urllib.error.HTTPError,
            KeyError, IndexError, ValueError, TimeoutError):
        return None


# ---------------------------------------------------------------- pipeline

def read_leads(path):
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        rows = []
        for row in reader:
            rows.append({(k or "").strip().lower(): (v or "")
                         for k, v in row.items()})
        return rows


def score_all(leads, api_key=None):
    """Score every lead, attach AI/mock angle, sort best first."""
    scored = []
    for lead in leads:
        score, grade, reasons, contact_ok = score_lead(lead)
        if api_key:
            angle = gemini_angle(lead, score, grade, reasons, api_key)
            if angle is None:
                angle = mock_angle(lead, score, grade, reasons) + \
                    " (AI call failed, fell back to mock)"
        else:
            angle = mock_angle(lead, score, grade, reasons)
        scored.append({
            **lead,
            "score": score,
            "grade": grade,
            "reasons": "; ".join(reasons),
            "ai_angle": angle,
            "contact_ok": "yes" if contact_ok else "NO - no consent",
        })
    scored.sort(key=lambda row: row["score"], reverse=True)
    return scored


def write_scored(scored, path):
    fields = ["name", "email", "phone", "company", "website", "industry",
              "employees", "source", "budget", "consent",
              "score", "grade", "reasons", "ai_angle", "contact_ok"]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(scored)


def print_summary(scored, top_n):
    contactable = [row for row in scored if row["contact_ok"] == "yes"]
    blocked = len(scored) - len(contactable)
    grades = {g: sum(1 for row in scored if row["grade"] == g)
              for g in "ABCD"}
    print(f"\nScored {len(scored)} leads | "
          f"A:{grades['A']} B:{grades['B']} C:{grades['C']} D:{grades['D']} | "
          f"contactable: {len(contactable)} | blocked (no consent): {blocked}")
    print(f"\nTop {min(top_n, len(contactable))} contactable leads:")
    print(f"{'Score':>5}  {'Grade':<5}  {'Name':<22} {'Company':<24} Email")
    for row in contactable[:top_n]:
        print(f"{row['score']:>5}  {row['grade']:<5}  "
              f"{(row.get('name') or '')[:22]:<22} "
              f"{(row.get('company') or '')[:24]:<24} {row.get('email') or ''}")
    if blocked:
        print(f"\n{blocked} lead(s) flagged DO-NOT-CONTACT (no TCPA consent) "
              "— scored but excluded from outreach.")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Score CSV leads 0-100 with an optional Gemini AI angle.")
    parser.add_argument("csv", nargs="?", help="input leads CSV")
    parser.add_argument("--out", default="scored_leads.csv",
                        help="output scored CSV (default: scored_leads.csv)")
    parser.add_argument("--top", type=int, default=10,
                        help="how many top leads to show (default: 10)")
    parser.add_argument("--demo", action="store_true",
                        help="score the bundled sample_leads.csv")
    parser.add_argument("--version", action="store_true",
                        help="print version and exit")
    args = parser.parse_args(argv)

    if args.version:
        print(f"nz-ai-lead-scorer {VERSION}")
        return 0

    input_path = "sample_leads.csv" if args.demo else args.csv
    if not input_path:
        parser.error("give a leads CSV, or use --demo")

    api_key = os.environ.get("NZ_GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if api_key:
        print("AI mode: Gemini (key from environment)")
    else:
        print("MOCK mode: no NZ_GEMINI_API_KEY set — AI angles are "
              "labelled mock templates, not model output.")

    leads = read_leads(input_path)
    if not leads:
        print(f"No leads found in {input_path}")
        return 1
    scored = score_all(leads, api_key=api_key)
    write_scored(scored, args.out)
    print_summary(scored, args.top)
    print(f"\nFull scored list written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
