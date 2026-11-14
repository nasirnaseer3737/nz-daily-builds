"""Tests for nz-ai-lead-scorer (mock/offline mode only — no API calls).

Run:  python3 -m unittest test_lead_scorer.py -v
       or: python3 test_lead_scorer.py
"""

import csv
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lead_scorer import (  # noqa: E402
    _budget_number,
    _employees_number,
    gemini_angle,
    mock_angle,
    read_leads,
    score_all,
    score_lead,
    write_scored,
)

STRONG = {
    "name": "Sara Ahmed", "email": "sara@brightdental.com",
    "phone": "+1 713-555-0142", "company": "Bright Dental",
    "website": "https://brightdental.com", "industry": "dental",
    "employees": "51-200", "source": "referral",
    "budget": "$5000", "consent": "yes",
}

WEAK = {
    "name": "John Doe", "email": "not-an-email", "phone": "",
    "company": "", "website": "", "industry": "unknown-niche",
    "employees": "", "source": "scraped", "budget": "",
    "consent": "no",
}


class TestParsing(unittest.TestCase):
    def test_employees_plain(self):
        self.assertEqual(_employees_number("25"), 25)

    def test_employees_range_takes_upper(self):
        self.assertEqual(_employees_number("11-50"), 50)

    def test_employees_plus(self):
        self.assertEqual(_employees_number("200+"), 200)

    def test_employees_empty(self):
        self.assertIsNone(_employees_number(""))

    def test_budget_plain(self):
        self.assertEqual(_budget_number("5000"), 5000)

    def test_budget_k_suffix(self):
        self.assertEqual(_budget_number("$5k/mo"), 5000)

    def test_budget_empty(self):
        self.assertIsNone(_budget_number(""))


class TestScoring(unittest.TestCase):
    def test_strong_lead_scores_high(self):
        score, grade, reasons, contact_ok = score_lead(STRONG)
        self.assertGreaterEqual(score, 80)
        self.assertEqual(grade, "A")
        self.assertTrue(contact_ok)
        self.assertTrue(any("business email" in r for r in reasons))

    def test_weak_lead_scores_low(self):
        score, grade, reasons, contact_ok = score_lead(WEAK)
        self.assertLessEqual(score, 25)
        self.assertEqual(grade, "D")
        self.assertFalse(contact_ok)

    def test_free_email_scores_less_than_business(self):
        free = dict(STRONG, email="sara@gmail.com")
        business = dict(STRONG, email="sara@brightdental.com")
        self.assertLess(score_lead(free)[0], score_lead(business)[0])

    def test_no_consent_blocks_contact(self):
        lead = dict(STRONG, consent="no")
        score, grade, reasons, contact_ok = score_lead(lead)
        self.assertFalse(contact_ok)
        self.assertIn("NO consent", " ".join(reasons))

    def test_score_never_out_of_range(self):
        for lead in (STRONG, WEAK, {}, dict(STRONG, email="x@y.zz")):
            score, _, _, _ = score_lead(lead)
            self.assertGreaterEqual(score, 0)
            self.assertLessEqual(score, 100)

    def test_referral_beats_scraped(self):
        ref = dict(STRONG, source="referral")
        scr = dict(STRONG, source="scraped")
        self.assertGreater(score_lead(ref)[0], score_lead(scr)[0])


class TestAngles(unittest.TestCase):
    def test_mock_angle_is_labelled_mock(self):
        angle = mock_angle(STRONG, 90, "A", ["business email domain (+15)"])
        self.assertIn("[MOCK", angle)
        self.assertIn("Bright Dental", angle)

    def test_gemini_angle_returns_none_without_network(self):
        # Invalid key + unreachable in offline env must fail gracefully.
        result = gemini_angle(STRONG, 90, "A", ["x"], api_key="bad-key")
        self.assertIsNone(result)


class TestPipeline(unittest.TestCase):
    def test_score_all_sorts_descending(self):
        scored = score_all([WEAK, STRONG, dict(STRONG, email="a@gmail.com")])
        scores = [row["score"] for row in scored]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertEqual(scored[0]["company"], "Bright Dental")

    def test_score_all_mock_angles_labelled(self):
        scored = score_all([STRONG, WEAK])
        for row in scored:
            self.assertIn("[MOCK", row["ai_angle"])

    def test_roundtrip_csv(self):
        scored = score_all([STRONG, WEAK])
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out.csv")
            write_scored(scored, out)
            with open(out, newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["grade"], "A")
            self.assertEqual(rows[1]["contact_ok"], "NO - no consent")

    def test_read_sample_csv(self):
        sample = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "sample_leads.csv")
        leads = read_leads(sample)
        self.assertGreaterEqual(len(leads), 5)
        scored = score_all(leads)
        self.assertTrue(all(0 <= row["score"] <= 100 for row in scored))
        self.assertTrue(any(row["grade"] == "A" for row in scored))


if __name__ == "__main__":
    unittest.main(verbosity=2)
