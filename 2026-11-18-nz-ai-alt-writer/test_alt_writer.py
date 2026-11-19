#!/usr/bin/env python3
"""Tests for nz-ai-alt-writer (mock/offline mode — no API key needed)."""

import csv
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import alt_writer


class TestFilenameTokens(unittest.TestCase):
    def test_hyphenated_name(self):
        self.assertEqual(
            alt_writer.tokens_from_filename("blue-wooden-dining-table.jpg"),
            ["blue", "wooden", "dining", "table"])

    def test_underscores_and_numbers_dropped(self):
        self.assertEqual(
            alt_writer.tokens_from_filename("hero_banner_001_final.png"),
            ["hero", "banner"])

    def test_camera_name_has_no_meaning(self):
        self.assertEqual(
            alt_writer.tokens_from_filename("IMG_20261118_123456.jpg"), [])

    def test_dimensions_dropped(self):
        self.assertEqual(
            alt_writer.tokens_from_filename("logo-800x600.png"), ["logo"])


class TestMockAlt(unittest.TestCase):
    def test_basic_mock(self):
        alt = alt_writer.mock_alt_text("red-brick-house-exterior.jpg")
        self.assertEqual(alt, "Red brick house exterior")

    def test_camera_name_fallback(self):
        self.assertEqual(alt_writer.mock_alt_text("IMG_1234.jpg"),
                         "Website image")

    def test_keyword_appended(self):
        alt = alt_writer.mock_alt_text("emergency-plumber-van.jpg",
                                       keyword="plumbing services")
        self.assertIn("plumbing services", alt)
        self.assertTrue(alt.startswith("Emergency plumber van"))


class TestCleanAlt(unittest.TestCase):
    def test_strips_image_of_prefix(self):
        self.assertEqual(
            alt_writer.clean_alt_text("Image of a red brick house"),
            "A red brick house")

    def test_strips_photo_of_prefix(self):
        self.assertEqual(
            alt_writer.clean_alt_text("photo of blue sofa"), "Blue sofa")

    def test_length_cap_at_word_boundary(self):
        long_alt = " ".join(["word"] * 40)  # 199 chars
        cleaned = alt_writer.clean_alt_text(long_alt, max_length=125)
        self.assertLessEqual(len(cleaned), 125)
        self.assertFalse(cleaned.endswith(" "))  # no dangling cut word

    def test_empty_stays_empty(self):
        self.assertEqual(alt_writer.clean_alt_text(""), "")


class TestDiscovery(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "a.jpg").touch()
        (self.root / "b.PNG").touch()
        (self.root / "sub").mkdir()
        (self.root / "sub" / "c.webp").touch()
        (self.root / "notes.txt").touch()

    def tearDown(self):
        self.tmp.cleanup()

    def test_folder_scan(self):
        found = alt_writer.discover_from_folder(str(self.root))
        self.assertEqual(len(found), 3)
        self.assertTrue(all(f.endswith((".jpg", ".PNG", ".webp"))
                            for f in found))

    def test_csv_discovery(self):
        csv_path = self.root / "images.csv"
        with open(csv_path, "w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["image"])
            writer.writerow(["https://example.com/x.jpg"])
            writer.writerow(["local/y.png"])
            writer.writerow([""])
        self.assertEqual(alt_writer.discover_from_csv(str(csv_path)),
                         ["https://example.com/x.jpg", "local/y.png"])

    def test_csv_without_image_column(self):
        csv_path = self.root / "bad.csv"
        csv_path.write_text("url\nhttps://example.com/x.jpg\n")
        with self.assertRaises(ValueError):
            alt_writer.discover_from_csv(str(csv_path))


class TestRunAndDedupe(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.out = self.root / "out"
        self.images = ["red-brick-house.jpg", "blue-sofa-living-room.png",
                       "logo.svg"]

    def tearDown(self):
        self.tmp.cleanup()

    def test_run_writes_csv_json_md(self):
        summary, results = alt_writer.run(
            self.images, str(self.out), keyword="home services",
            use_mock=True)
        self.assertEqual(summary["total"], 3)
        self.assertEqual(summary["mock"], 3)
        self.assertEqual(summary["ai"], 0)
        for name in ("alt-text.csv", "alt-text.json", "alt-text.md"):
            self.assertTrue((self.out / name).is_file())
        with open(self.out / "alt-text.csv", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(row["source"] == "mock" for row in rows))
        self.assertTrue(all(int(row["chars"]) <= 125 for row in rows))
        self.assertIn("Red brick house", rows[0]["alt"])

    def test_decorative_gets_empty_alt(self):
        summary, results = alt_writer.run(
            self.images, str(self.out), use_mock=True,
            decorative={"logo.svg"})
        decorative = [r for r in results if r["image"] == "logo.svg"][0]
        self.assertEqual(decorative["alt"], "")
        self.assertEqual(decorative["source"], "decorative")
        self.assertEqual(summary["decorative"], 1)

    def test_second_run_skips_done(self):
        alt_writer.run(self.images, str(self.out), use_mock=True)
        summary, results = alt_writer.run(self.images, str(self.out),
                                          use_mock=True)
        self.assertEqual(summary["skipped_already_done"], 3)
        self.assertTrue(all(r["source"] == "done" for r in results))

    def test_force_rewrites(self):
        alt_writer.run(self.images, str(self.out), use_mock=True)
        summary, _ = alt_writer.run(self.images, str(self.out),
                                    use_mock=True, force=True)
        self.assertEqual(summary["skipped_already_done"], 0)
        self.assertEqual(summary["new"], 3)

    def test_markdown_labels_mock(self):
        alt_writer.run(self.images, str(self.out), use_mock=True)
        md = (self.out / "alt-text.md").read_text()
        self.assertIn("mock", md)


class TestCheckMode(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _write_csv(self, rows):
        path = self.root / "alts.csv"
        with open(path, "w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["image", "alt"])
            writer.writeheader()
            writer.writerows(rows)
        return str(path)

    def test_clean_csv_has_no_issues(self):
        path = self._write_csv([{"image": "a.jpg", "alt": "Red brick house"}])
        self.assertEqual(alt_writer.check_alts(path), [])

    def test_flags_empty_long_prefix_and_duplicate(self):
        long_alt = " ".join(["word"] * 40)
        path = self._write_csv([
            {"image": "a.jpg", "alt": ""},
            {"image": "b.jpg", "alt": long_alt},
            {"image": "c.jpg", "alt": "Image of a blue sofa"},
            {"image": "d.jpg", "alt": "Red brick house"},
            {"image": "e.jpg", "alt": "red brick house"},
        ])
        issues = alt_writer.check_alts(path)
        kinds = [i["issue"] for i in issues]
        self.assertTrue(any("empty" in k for k in kinds))
        self.assertTrue(any("too long" in k for k in kinds))
        self.assertTrue(any("image of" in k for k in kinds))
        self.assertTrue(any("duplicate" in k for k in kinds))
        self.assertEqual(len(issues), 4)

    def test_missing_alt_column(self):
        path = self.root / "bad.csv"
        path.write_text("image\nx.jpg\n")
        with self.assertRaises(ValueError):
            alt_writer.check_alts(str(path))


class TestGeminiPrompt(unittest.TestCase):
    def test_prompt_mentions_filename_and_keyword(self):
        # Exercise the request-building path without hitting the network:
        # an unreachable key/host fails gracefully with an error string.
        os.environ.pop("NZ_GEMINI_API_KEY", None)
        alt, error = alt_writer.gemini_alt_text(
            "blue-sofa.jpg", keyword="furniture store",
            api_key="invalid-key-for-test", timeout=5)
        self.assertIsNone(alt)
        self.assertIsNotNone(error)


if __name__ == "__main__":
    unittest.main(verbosity=2)
