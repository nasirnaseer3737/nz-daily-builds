#!/usr/bin/env python3
"""Tests for nz-ai-seo-auditor (offline, stdlib unittest only)."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import seo_auditor as sa

GOOD = Path(__file__).resolve().parent / "sample_pages" / "good-page.html"
BAD = Path(__file__).resolve().parent / "sample_pages" / "bad-page.html"


def parse(path):
    return sa.parse_html(Path(path).read_text(encoding="utf-8"))


def by_name(result, name):
    for c in result["checks"]:
        if c["check"] == name:
            return c
    raise AssertionError(f"check {name!r} not found")


class TestParsing(unittest.TestCase):
    def test_good_page_title_and_meta(self):
        page = parse(GOOD)
        self.assertIn("WordPress Developer", page.title)
        self.assertTrue(30 <= len(page.title) <= 60)
        self.assertTrue(120 <= len(page.meta_description) <= 160)
        self.assertEqual(page.canonical,
                         "https://nzgenix.digital/wordpress-developer/")
        self.assertTrue(page.has_json_ld)
        self.assertIn("og:title", page.meta)
        self.assertIn("twitter:card", page.meta)

    def test_good_page_headings_and_images(self):
        page = parse(GOOD)
        self.assertEqual(len(page.h1), 1)
        self.assertEqual([lvl for lvl, _ in page.headings],
                         [1, 2, 3, 3, 2])
        self.assertEqual(len(page.images), 2)
        self.assertTrue(all(alt for _, alt in page.images))

    def test_bad_page_parsing(self):
        page = parse(BAD)
        self.assertEqual(page.title, "Home")
        self.assertEqual(page.meta_description, "")
        self.assertEqual(len(page.h1), 2)
        self.assertEqual(len(page.images), 2)
        self.assertFalse(page.has_json_ld)
        self.assertEqual(page.canonical, "")

    def test_empty_html(self):
        page = sa.parse_html("")
        self.assertEqual(page.title, "")
        self.assertEqual(page.headings, [])
        self.assertEqual(page.images, [])

    def test_word_count(self):
        self.assertEqual(sa.word_count("one two three"), 3)
        self.assertEqual(sa.word_count(""), 0)

    def test_flesch_easy_text(self):
        text = ("The cat sat on the mat. The dog ran in the park. "
                "We like to play all day long in the sun.")
        score = sa.flesch_reading_ease(text)
        self.assertIsNotNone(score)
        self.assertGreater(score, 80)

    def test_flesch_too_short(self):
        self.assertIsNone(sa.flesch_reading_ease("Too short."))

    def test_keyword_stats(self):
        occ, density = sa.keyword_stats(
            "WordPress developer builds WordPress sites.", "wordpress")
        self.assertEqual(occ, 2)
        self.assertGreater(density, 0)


class TestAudit(unittest.TestCase):
    def test_good_page_scores_high(self):
        result = sa.audit_page(parse(GOOD), "good-page.html",
                               "WordPress developer")
        self.assertGreaterEqual(result["score"], 85)
        self.assertIn(result["grade"], ("A", "B"))
        self.assertEqual(result["failed_checks"], [])
        self.assertEqual(by_name(result, "Title tag")["status"], "pass")
        self.assertEqual(by_name(result, "H1 heading")["status"], "pass")
        self.assertEqual(by_name(result, "Image alt text")["status"], "pass")
        self.assertEqual(by_name(result, "Schema.org markup")["status"], "pass")
        self.assertEqual(by_name(result, "Target keyword")["status"], "pass")

    def test_bad_page_scores_low(self):
        result = sa.audit_page(parse(BAD), "bad-page.html", "wordpress developer")
        self.assertLessEqual(result["score"], 60)
        self.assertIn(result["grade"], ("D", "F"))
        self.assertIn("Title tag", result["warning_checks"])
        self.assertIn("Meta description", result["failed_checks"])
        self.assertIn("H1 heading", result["warning_checks"])
        self.assertIn("Image alt text", result["failed_checks"])
        self.assertIn("Target keyword", result["failed_checks"])
        self.assertIn("Canonical URL", result["warning_checks"])
        self.assertIn("Schema.org markup", result["warning_checks"])

    def test_heading_skip_is_warn(self):
        page = parse(BAD)
        result = sa.audit_page(page, "bad-page.html")
        self.assertEqual(by_name(result, "Heading order")["status"], "warn")

    def test_keyword_absent_is_fail(self):
        page = parse(GOOD)
        result = sa.audit_page(page, "good-page.html", "plumber chicago")
        self.assertEqual(by_name(result, "Target keyword")["status"], "fail")

    def test_no_keyword_means_no_keyword_check(self):
        result = sa.audit_page(parse(GOOD), "good-page.html")
        names = [c["check"] for c in result["checks"]]
        self.assertNotIn("Target keyword", names)

    def test_fixes_listed_for_failures(self):
        result = sa.audit_page(parse(BAD), "bad-page.html", "wordpress developer")
        self.assertTrue(len(result["fixes"]) >= 4)
        self.assertTrue(all(isinstance(f, str) and f for f in result["fixes"]))

    def test_score_bounds(self):
        for path in (GOOD, BAD):
            result = sa.audit_page(parse(path), str(path))
            self.assertGreaterEqual(result["score"], 0)
            self.assertLessEqual(result["score"], 100)


class TestSuggestions(unittest.TestCase):
    def test_mock_labelled(self):
        result = sa.audit_page(parse(BAD), "bad-page.html", "wordpress developer")
        sug = sa.get_suggestions(result, api_key="")
        self.assertIn("MOCK", sug["mode"])
        self.assertTrue(len(sug["suggestions"]) >= 4)

    def test_mock_good_page(self):
        result = sa.audit_page(parse(GOOD), "good-page.html", "WordPress developer")
        sug = sa.get_suggestions(result, api_key="")
        self.assertIn("MOCK", sug["mode"])
        self.assertTrue(sug["suggestions"])

    def test_gemini_failure_falls_back_to_mock(self):
        # Invalid key / no network must never crash — labelled mock instead.
        result = sa.audit_page(parse(BAD), "bad-page.html")
        sug = sa.gemini_suggestions(result, api_key="invalid-key-for-test")
        self.assertIn("MOCK", sug["mode"])
        self.assertTrue(sug["suggestions"])


class TestEndToEnd(unittest.TestCase):
    def test_audit_sources_writes_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = sa.audit_sources(
                [str(GOOD), str(BAD)], "WordPress developer",
                os.path.join(tmp, "out"), api_key="")
            self.assertEqual(len(report["pages"]), 2)
            self.assertEqual(report["errors"], [])
            self.assertEqual(report["ai_mode"], "MOCK (offline fallback)")
            out = Path(tmp) / "out"
            self.assertTrue((out / "report.json").is_file())
            self.assertTrue((out / "report.md").is_file())
            data = json.loads((out / "report.json").read_text())
            self.assertEqual(data["pages"][0]["score"], report["pages"][0]["score"])
            md = (out / "report.md").read_text()
            self.assertIn("NZ AI SEO Audit Report", md)
            self.assertIn("bad-page.html", md)

    def test_missing_source_is_error_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = sa.audit_sources(
                ["no-such-file.html"], "", os.path.join(tmp, "out"), api_key="")
            self.assertEqual(report["pages"], [])
            self.assertEqual(len(report["errors"]), 1)

    def test_cli_folder_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc = sa.main(["--folder", str(GOOD.parent),
                          "--keyword", "WordPress developer",
                          "--out", os.path.join(tmp, "out")])
            self.assertEqual(rc, 0)
            self.assertTrue((Path(tmp) / "out" / "report.json").is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
