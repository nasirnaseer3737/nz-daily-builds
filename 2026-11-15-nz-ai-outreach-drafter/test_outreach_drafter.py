"""Tests for outreach_drafter.py — run with: python3 -m unittest -v test_outreach_drafter"""

import csv
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import outreach_drafter as od


SAMPLE_ROWS = [
    {"name": "Mike Ross", "business": "Lakeshore Plumbing", "niche": "plumbing",
     "city": "Chicago", "email": "mike@lakeshore.example",
     "website": "https://lakeshore.example", "pain_point": "", "consent": "yes"},
    {"name": "Sara Khan", "business": "Bright Smile Dental", "niche": "dental",
     "city": "Dallas", "email": "sara@brightsmile.example",
     "website": "", "pain_point": "no-shows every week", "consent": "opt-in"},
    {"name": "Tom Reed", "business": "Reed Roofing", "niche": "roofing",
     "city": "Houston", "email": "tom@reedroofing.example",
     "website": "", "pain_point": "", "consent": "no"},
    {"name": "Ana Lee", "business": "Cool Air HVAC", "niche": "hvac",
     "city": "Austin", "email": "ana@coolair.example",
     "website": "", "pain_point": "", "consent": "yes"},
]


def write_csv(rows, path):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


class TestLoading(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.csv_path = os.path.join(self.tmp.name, "prospects.csv")
        write_csv(SAMPLE_ROWS, self.csv_path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_loads_all_rows(self):
        prospects, errors = od.load_prospects(self.csv_path)
        self.assertEqual(len(prospects), 4)
        self.assertEqual(errors, [])

    def test_bad_email_rejected(self):
        rows = [dict(SAMPLE_ROWS[0], email="not-an-email")]
        write_csv(rows, self.csv_path)
        prospects, errors = od.load_prospects(self.csv_path)
        self.assertEqual(prospects, [])
        self.assertEqual(len(errors), 1)

    def test_missing_column_reported(self):
        with open(self.csv_path, "w", encoding="utf-8") as fh:
            fh.write("name,business\nMike,Acme\n")
        prospects, errors = od.load_prospects(self.csv_path)
        self.assertEqual(prospects, [])
        self.assertIn("email", errors[0])


class TestConsent(unittest.TestCase):
    def test_yes_variants(self):
        for value in ("yes", "Yes", "Y", "true", "opt-in", "optin"):
            self.assertTrue(od.has_consent({"consent": value}), value)

    def test_no_variants(self):
        for value in ("no", "No", "", "maybe"):
            self.assertFalse(od.has_consent({"consent": value}), value)


class TestMockDraft(unittest.TestCase):
    def test_personalised(self):
        draft = od.mock_draft(SAMPLE_ROWS[0])
        self.assertEqual(draft["source"], "mock")
        self.assertEqual(len(draft["subjects"]), 3)
        self.assertIn("Lakeshore Plumbing", draft["subjects"][0])
        self.assertIn("Mike", draft["body"])
        self.assertIn("Chicago", draft["body"])

    def test_custom_pain_point_used(self):
        draft = od.mock_draft(SAMPLE_ROWS[1])
        self.assertIn("no-shows every week", draft["body"])

    def test_niche_line_for_known_niche(self):
        draft = od.mock_draft(SAMPLE_ROWS[0])
        self.assertIn("missed calls", draft["body"])

    def test_each_draft_unique(self):
        bodies = {od.mock_draft(r)["body"] for r in SAMPLE_ROWS}
        self.assertEqual(len(bodies), 4)


class TestRunEndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.csv_path = os.path.join(self.tmp.name, "prospects.csv")
        write_csv(SAMPLE_ROWS, self.csv_path)
        self.out = os.path.join(self.tmp.name, "out")
        # Ana Lee was already emailed — she must be skipped.
        self.history_path = os.path.join(self.tmp.name, "sent.json")
        with open(self.history_path, "w", encoding="utf-8") as fh:
            json.dump({"ana@coolair.example": "2026-11-10"}, fh)

    def tearDown(self):
        self.tmp.cleanup()

    def test_full_run(self):
        start = datetime(2026, 11, 15, 14, 0)
        result = od.run(self.csv_path, self.out, self.history_path,
                        start, 10, 0, api_key="")
        # 4 prospects: 2 drafted (Mike, Sara), 1 no-consent, 1 already sent.
        self.assertEqual(result["total"], 4)
        self.assertEqual(result["drafted"], 2)
        self.assertEqual(result["mock_drafts"], 2)
        self.assertEqual(result["ai_drafts"], 0)
        self.assertEqual(len(result["skipped"]), 2)
        reasons = " ".join(r for _, r in result["skipped"])
        self.assertIn("NO CONSENT", reasons)
        self.assertIn("already emailed", reasons)

    def test_output_files(self):
        start = datetime(2026, 11, 15, 14, 0)
        od.run(self.csv_path, self.out, self.history_path, start, 10, 0, "")
        with open(os.path.join(self.out, "drafts.csv"), encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["email"], "mike@lakeshore.example")
        self.assertEqual(rows[0]["source"], "mock")
        self.assertTrue(rows[0]["subject_1"])
        self.assertTrue(rows[0]["body"])
        with open(os.path.join(self.out, "queue.json"), encoding="utf-8") as fh:
            queue = json.load(fh)
        self.assertEqual(len(queue["queue"]), 2)
        self.assertEqual(queue["queue"][0]["send_at"], "2026-11-15 14:00")
        self.assertEqual(queue["queue"][1]["send_at"], "2026-11-15 14:10")
        self.assertEqual(queue["gap_minutes"], 10)

    def test_limit(self):
        start = datetime(2026, 11, 15, 14, 0)
        result = od.run(self.csv_path, self.out, self.history_path,
                        start, 10, 1, api_key="")
        self.assertEqual(result["drafted"], 1)
        self.assertEqual(len(result["queue"]), 1)

    def test_gap_minutes(self):
        start = datetime(2026, 11, 15, 14, 0)
        result = od.run(self.csv_path, self.out, self.history_path,
                        start, 30, 0, api_key="")
        self.assertEqual(result["queue"][1]["send_at"], "2026-11-15 14:30")


class TestQueue(unittest.TestCase):
    def test_slots_increment(self):
        drafts = [{"email": "a@x", "business": "A", "subjects": ["s1"]},
                  {"email": "b@x", "business": "B", "subjects": ["s2"]},
                  {"email": "c@x", "business": "C", "subjects": ["s3"]}]
        queue = od.build_queue(drafts, datetime(2026, 11, 15, 9, 0), 10)
        self.assertEqual([q["send_at"] for q in queue],
                         ["2026-11-15 09:00", "2026-11-15 09:10", "2026-11-15 09:20"])
        self.assertTrue(all(q["status"] == "queued" for q in queue))


class TestHistory(unittest.TestCase):
    def test_missing_file_is_empty(self):
        self.assertEqual(od.load_history("/nonexistent/sent.json"), {})

    def test_bad_json_is_empty(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            fh.write("{not json")
            path = fh.name
        try:
            self.assertEqual(od.load_history(path), {})
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
