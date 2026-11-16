"""Tests for nz-ai-social-scheduler (mock/offline only — no API calls)."""
import csv
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from social_scheduler import (  # noqa: E402
    PLATFORMS, default_start, draft_post, enforce_limits, history_key,
    load_history, load_topics, mock_generate, parse_hashtags,
    parse_platforms, parse_start, run, schedule_slots,
)

SAMPLE_TOPICS = """topic,platforms,tone,link,hashtags
WordPress 7.2 is coming — check plugin compatibility before December,linkedin,professional,https://nzgenix.digital,"WordPress, SEO"
AI agents can now complete purchases with ChatGPT Wallet,linkedin; x,educational,,"AI, ChatGPT"
How small clinics can automate appointment reminders,facebook, friendly,https://nzgenix.digital,Automation
"""


def write_csv(content):
    fd, path = tempfile.mkstemp(suffix=".csv")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(content)
    return path


class TestParsing(unittest.TestCase):
    def test_parse_platforms(self):
        self.assertEqual(parse_platforms("linkedin, x"), ["linkedin", "x"])
        self.assertEqual(parse_platforms("X, x, tiktok"), ["x"])
        self.assertEqual(parse_platforms(""), [])

    def test_parse_hashtags(self):
        self.assertEqual(parse_hashtags("WordPress, #SEO, seo"),
                         ["#WordPress", "#SEO"])
        self.assertEqual(parse_hashtags("bad tag!, ok_tag"), ["#ok_tag"])

    def test_load_topics(self):
        path = write_csv(SAMPLE_TOPICS)
        try:
            topics = load_topics(path)
        finally:
            os.unlink(path)
        self.assertEqual(len(topics), 3)
        self.assertEqual(topics[0]["platforms"], ["linkedin"])
        self.assertEqual(topics[1]["platforms"], ["linkedin", "x"])
        self.assertEqual(topics[1]["tone"], "educational")
        self.assertEqual(topics[2]["tone"], "friendly")  # trims spaces
        self.assertEqual(topics[0]["hashtags"], ["#WordPress", "#SEO"])

    def test_load_topics_missing_column(self):
        path = write_csv("headline,platforms\nHello,linkedin\n")
        try:
            with self.assertRaises(ValueError):
                load_topics(path)
        finally:
            os.unlink(path)

    def test_load_topics_bad_tone_defaults(self):
        path = write_csv("topic,platforms,tone\nHello world,linkedin,shouty\n")
        try:
            topics = load_topics(path)
        finally:
            os.unlink(path)
        self.assertEqual(topics[0]["tone"], "professional")

    def test_load_topics_empty_platforms_default_linkedin(self):
        path = write_csv("topic,platforms\nHello world,\n")
        try:
            topics = load_topics(path)
        finally:
            os.unlink(path)
        self.assertEqual(topics[0]["platforms"], ["linkedin"])


class TestGeneration(unittest.TestCase):
    def setUp(self):
        self.topic = {"topic": "AI SEO tips for WordPress sites",
                      "platforms": ["linkedin", "x"],
                      "tone": "professional",
                      "link": "https://nzgenix.digital",
                      "hashtags": ["#WordPress", "#SEO", "#AI"]}

    def test_mock_all_platforms_within_limits(self):
        for platform in PLATFORMS:
            text = mock_generate(self.topic, platform)
            self.assertLessEqual(len(text), PLATFORMS[platform]["limit"],
                                 platform)
            self.assertIn("AI SEO tips", text)

    def test_mock_x_short_and_has_link(self):
        text = mock_generate(self.topic, "x")
        self.assertLessEqual(len(text), 280)
        self.assertIn("https://nzgenix.digital", text)

    def test_mock_hashtag_cap(self):
        text = mock_generate(self.topic, "x")
        self.assertLessEqual(text.count("#"), 2)

    def test_draft_post_mock_when_no_key(self):
        post = draft_post(self.topic, "linkedin", api_key="")
        self.assertEqual(post["source"], "mock")
        self.assertIn("AI SEO tips", post["text"])

    def test_draft_post_forced_mock(self):
        post = draft_post(self.topic, "x", api_key="fake-key", force_mock=True)
        self.assertEqual(post["source"], "mock")


class TestLimits(unittest.TestCase):
    def test_enforce_limits_truncates_long_x_post(self):
        long_text = "word " * 100 + "\n\n#AI #SEO"
        out = enforce_limits(long_text, "x")
        self.assertLessEqual(len(out), 280)
        self.assertIn("#AI", out)  # hashtags survive truncation

    def test_enforce_limits_keeps_short_post_untouched(self):
        text = "Short post.\n\n#WordPress"
        self.assertEqual(enforce_limits(text, "linkedin"), text)


class TestScheduling(unittest.TestCase):
    def test_slots_spacing(self):
        start = datetime(2026, 11, 17, 14, 0)
        slots = schedule_slots(3, start, 4)
        self.assertEqual(slots[1] - slots[0], timedelta(hours=4))
        self.assertEqual(slots[2] - slots[0], timedelta(hours=8))

    def test_default_start_is_tomorrow_14(self):
        now = datetime(2026, 11, 16, 10, 30)
        start = default_start(now)
        self.assertEqual((start.day, start.hour), (17, 14))

    def test_parse_start_date_only(self):
        start = parse_start("2026-11-17")
        self.assertEqual((start.day, start.hour), (17, 14))

    def test_parse_start_bad_value(self):
        with self.assertRaises(ValueError):
            parse_start("tomorrow")


class TestPipeline(unittest.TestCase):
    def test_full_run_mock_and_outputs(self):
        csv_path = write_csv(SAMPLE_TOPICS)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                out_dir = os.path.join(tmp, "out")
                history = os.path.join(tmp, "posted.json")
                result = run(csv_path, out_dir, history,
                             parse_start("2026-11-17T14:00"),
                             gap_hours=4, limit=0, api_key="",
                             force_mock=True)
                # 3 topics -> 1 + 2 + 1 = 4 posts
                self.assertEqual(result["posts"], 4)
                self.assertEqual(result["mock_posts"], 4)
                self.assertEqual(result["skipped"], 0)
                self.assertEqual(result["first_slot"], "2026-11-17 14:00 PKT")
                self.assertEqual(result["last_slot"], "2026-11-18 02:00 PKT")
                for name in ("schedule.json", "drafts.md", "posts.csv"):
                    self.assertTrue(os.path.exists(os.path.join(out_dir, name)))
                with open(os.path.join(out_dir, "schedule.json"),
                          encoding="utf-8") as fh:
                    posts = json.load(fh)
                self.assertEqual(len(posts), 4)
                self.assertTrue(all(p["source"] == "mock" for p in posts))
                self.assertTrue(all(p["chars"] <= PLATFORMS[p["platform"]]["limit"]
                                    for p in posts))
                with open(os.path.join(out_dir, "posts.csv"),
                          encoding="utf-8") as fh:
                    rows = list(csv.DictReader(fh))
                self.assertEqual(len(rows), 4)
                history_data = load_history(history)
                self.assertEqual(len(history_data), 4)
        finally:
            os.unlink(csv_path)

    def test_dedupe_skips_already_scheduled(self):
        csv_path = write_csv(SAMPLE_TOPICS)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                out_dir = os.path.join(tmp, "out")
                history = os.path.join(tmp, "posted.json")
                first = run(csv_path, out_dir, history,
                            parse_start("2026-11-17T14:00"),
                            gap_hours=4, limit=0, api_key="",
                            force_mock=True)
                self.assertEqual(first["posts"], 4)
                second = run(csv_path, os.path.join(tmp, "out2"), history,
                             parse_start("2026-11-18T14:00"),
                             gap_hours=4, limit=0, api_key="",
                             force_mock=True)
                self.assertEqual(second["posts"], 0)
                self.assertEqual(second["skipped"], 4)
        finally:
            os.unlink(csv_path)

    def test_limit_caps_topics(self):
        csv_path = write_csv(SAMPLE_TOPICS)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                result = run(csv_path, os.path.join(tmp, "out"),
                             os.path.join(tmp, "posted.json"),
                             parse_start("2026-11-17T14:00"),
                             gap_hours=4, limit=1, api_key="",
                             force_mock=True)
                self.assertEqual(result["posts"], 1)
        finally:
            os.unlink(csv_path)

    def test_history_key_is_case_insensitive(self):
        self.assertEqual(history_key("Hello World", "x"),
                         history_key("hello world", "x"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
