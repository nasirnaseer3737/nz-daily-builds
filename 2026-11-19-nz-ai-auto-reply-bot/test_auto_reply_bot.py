"""Tests for nz-ai-auto-reply-bot — mock/offline only, no API key needed."""

import csv
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import auto_reply_bot as bot

PKT = bot.PKT


def msg(message, **overrides):
    row = {
        "id": "m1", "channel": "whatsapp", "sender": "+923001234567",
        "name": "Ali", "message": message,
        "received_at": datetime(2026, 11, 19, 12, 0, tzinfo=PKT),
    }
    row.update(overrides)
    return row


class TestIntentClassification(unittest.TestCase):
    def test_pricing(self):
        self.assertEqual(bot.classify_intent("How much does it cost?")[0], "pricing")

    def test_booking(self):
        self.assertEqual(bot.classify_intent("Can I book an appointment?")[0], "booking")

    def test_services(self):
        self.assertEqual(bot.classify_intent("What services do you offer?")[0], "services")

    def test_hours(self):
        self.assertEqual(bot.classify_intent("What are your working hours?")[0], "hours")

    def test_location(self):
        self.assertEqual(bot.classify_intent("Where are you located?")[0], "location")

    def test_greeting(self):
        self.assertEqual(bot.classify_intent("Hello, salam!")[0], "greeting")

    def test_other(self):
        self.assertEqual(bot.classify_intent("Just checking something random")[0], "other")

    def test_complaint_escalates(self):
        intent, escalate, spam = bot.classify_intent("I want a refund, terrible service!")
        self.assertEqual(intent, "complaint")
        self.assertTrue(escalate)
        self.assertFalse(spam)

    def test_spam_flagged(self):
        intent, escalate, spam = bot.classify_intent("You have won free money, claim your prize")
        self.assertEqual(intent, "spam")
        self.assertTrue(spam)


class TestMockReplies(unittest.TestCase):
    def test_pricing_reply_mentions_name_and_services(self):
        reply = bot.mock_reply("pricing", "Ali", "NZ Plumbing", "plumbing")
        self.assertIn("Ali", reply)
        self.assertIn("plumbing", reply)

    def test_mock_never_says_call_us(self):
        for intent in bot.MOCK_TEMPLATES:
            reply = bot.mock_reply(intent, "Ali", "Biz", "plumbing")
            self.assertNotIn("call us", reply.lower())

    def test_escalation_gets_holding_reply_not_auto_reply(self):
        intent, reply, source, escalate, spam = bot.generate_reply(
            msg("I want a refund now"), "Biz", "plumbing", None, True)
        self.assertTrue(escalate)
        self.assertIn("flagged", reply.lower())


class TestSchedulingRules(unittest.TestCase):
    def test_quiet_hours_night(self):
        self.assertTrue(bot.in_quiet_hours(datetime(2026, 11, 19, 23, 30, tzinfo=PKT)))

    def test_quiet_hours_early_morning(self):
        self.assertTrue(bot.in_quiet_hours(datetime(2026, 11, 19, 3, 0, tzinfo=PKT)))

    def test_quiet_hours_daytime_is_open(self):
        self.assertFalse(bot.in_quiet_hours(datetime(2026, 11, 19, 14, 0, tzinfo=PKT)))

    def test_next_open_slot_pushes_night_to_8am(self):
        slot = bot.next_open_slot(datetime(2026, 11, 19, 23, 30, tzinfo=PKT))
        self.assertEqual((slot.day, slot.hour), (20, 8))

    def test_whatsapp_window_expired_after_24h(self):
        received = datetime(2026, 11, 17, 12, 0, tzinfo=PKT)
        now = datetime(2026, 11, 19, 12, 0, tzinfo=PKT)
        self.assertTrue(bot.outside_whatsapp_window(received, now))

    def test_whatsapp_window_open_within_24h(self):
        received = datetime(2026, 11, 19, 10, 0, tzinfo=PKT)
        now = datetime(2026, 11, 19, 12, 0, tzinfo=PKT)
        self.assertFalse(bot.outside_whatsapp_window(received, now))


class TestRunEndToEnd(unittest.TestCase):
    def run_bot(self, messages, **kwargs):
        tmp = tempfile.mkdtemp()
        out = os.path.join(tmp, "replies")
        now = datetime(2026, 11, 19, 14, 0, tzinfo=PKT)
        summary, results = bot.run(
            messages, out, "NZ Plumbing", "plumbing, drain cleaning",
            use_mock=True, now=now, **kwargs)
        return tmp, out, summary, results

    def test_full_run_queues_pricing_and_booking(self):
        messages = [
            msg("How much for drain cleaning?", id="m1"),
            msg("Can I book tomorrow?", id="m2", sender="+923009999999", name="Sara"),
        ]
        _tmp, out, summary, results = self.run_bot(messages)
        self.assertEqual(summary["queued"], 2)
        self.assertEqual(summary["mock"], 2)
        self.assertTrue(Path(out, "replies.csv").is_file())
        self.assertTrue(Path(out, "replies.json").is_file())
        self.assertTrue(Path(out, "replies.md").is_file())
        self.assertTrue(Path(out, "queue.json").is_file())
        with open(Path(out, "queue.json"), encoding="utf-8") as handle:
            queue = json.load(handle)["queue"]
        self.assertEqual(len(queue), 2)
        first = datetime.strptime(queue[0]["scheduled_for"], "%Y-%m-%d %H:%M")
        second = datetime.strptime(queue[1]["scheduled_for"], "%Y-%m-%d %H:%M")
        self.assertEqual((second - first).total_seconds(), 600)

    def test_escalation_and_spam_never_queued(self):
        messages = [
            msg("I want a refund, worst service", id="m1"),
            msg("You have won free money", id="m2", sender="+923001111111", name="X"),
            msg("Hi there", id="m3", sender="+923002222222", name="Zara"),
        ]
        _tmp, out, summary, _results = self.run_bot(messages)
        self.assertEqual(summary["escalate"], 1)
        self.assertEqual(summary["spam"], 1)
        self.assertEqual(summary["queued"], 1)
        with open(Path(out, "queue.json"), encoding="utf-8") as handle:
            queue = json.load(handle)["queue"]
        self.assertEqual([q["id"] for q in queue], ["m3"])

    def test_old_whatsapp_message_flagged_outside_window(self):
        old = msg("What is the price?", id="m1",
                  received_at=datetime(2026, 11, 17, 10, 0, tzinfo=PKT))
        _tmp, _out, summary, results = self.run_bot([old])
        self.assertEqual(summary["outside_window"], 1)
        self.assertEqual(summary["queued"], 0)
        self.assertEqual(results[0]["status"],
                         "outside_window — needs approved template")

    def test_old_email_message_still_queued(self):
        old = msg("What is the price?", id="m1", channel="email",
                  received_at=datetime(2026, 11, 17, 10, 0, tzinfo=PKT))
        _tmp, _out, summary, _results = self.run_bot([old])
        self.assertEqual(summary["queued"], 1)

    def test_overnight_messages_start_at_8am(self):
        night = msg("Hello", id="m1",
                    received_at=datetime(2026, 11, 19, 1, 0, tzinfo=PKT))
        _tmp, out, summary, _results = self.run_bot(
            [night], start=datetime(2026, 11, 19, 1, 30, tzinfo=PKT))
        self.assertEqual(summary["queue_start"], "2026-11-19 08:00")

    def test_dedupe_skips_already_replied(self):
        messages = [msg("How much?", id="m1")]
        tmp, out, summary, _results = self.run_bot(messages)
        summary2, _results2 = bot.run(
            messages, out, "NZ Plumbing", "plumbing",
            use_mock=True, now=datetime(2026, 11, 19, 14, 0, tzinfo=PKT))
        self.assertEqual(summary2["skipped_already_replied"], 1)
        self.assertEqual(summary2["queued"], 0)

    def test_gemini_failure_falls_back_to_mock(self):
        with mock.patch.object(bot, "gemini_reply",
                               return_value=(None, None, "Gemini HTTP 400")):
            intent, reply, source, _esc, _spam = bot.generate_reply(
                msg("How much?"), "Biz", "plumbing", "bad-key", False)
        self.assertEqual(source, "mock")
        self.assertIn("Ali", reply)

    def test_load_csv_and_json_inbox(self):
        tmp = tempfile.mkdtemp()
        csv_path = Path(tmp, "inbox.csv")
        with open(csv_path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["id", "channel", "sender", "name", "message", "received_at"])
            writer.writerow(["a1", "whatsapp", "+92", "Ali", "Hi", "2026-11-19T12:00:00+05:00"])
        json_path = Path(tmp, "inbox.json")
        json_path.write_text(json.dumps([{
            "id": "b1", "channel": "email", "sender": "x@y.com",
            "name": "Sara", "message": "What is the price?",
            "received_at": "2026-11-19T12:00:00+05:00"}]), encoding="utf-8")
        self.assertEqual(len(bot.load_inbox(str(csv_path))), 1)
        self.assertEqual(len(bot.load_inbox(str(json_path))), 1)
        self.assertEqual(bot.load_inbox(str(json_path))[0]["intent"] if False else
                         bot.load_inbox(str(json_path))[0]["channel"], "email")

    def test_check_mode_catches_bad_rows(self):
        tmp = tempfile.mkdtemp()
        bad = Path(tmp, "replies.csv")
        with open(bad, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=[
                "id", "channel", "sender", "intent", "source", "status",
                "scheduled_for", "reply"])
            writer.writeheader()
            writer.writerow({"id": "x1", "channel": "whatsapp", "sender": "s",
                             "intent": "pricing", "source": "mock",
                             "status": "queued", "scheduled_for": "2026-11-19 14:00",
                             "reply": ""})
            writer.writerow({"id": "x2", "channel": "whatsapp", "sender": "s",
                             "intent": "complaint", "source": "rule",
                             "status": "escalate — human only",
                             "scheduled_for": "2026-11-19 14:10",
                             "reply": "sorry"})
        total, problems = bot.check_replies(str(bad))
        self.assertEqual(total, 2)
        self.assertEqual(len(problems), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
