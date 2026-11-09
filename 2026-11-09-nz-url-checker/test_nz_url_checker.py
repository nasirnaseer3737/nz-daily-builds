#!/usr/bin/env python3
"""Tests for nz_url_checker — run with: python3 -m unittest test_nz_url_checker -v

Uses a tiny local HTTP server so no internet is needed for the tests.
"""

import csv
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

import nz_url_checker as checker


class _Handler(BaseHTTPRequestHandler):
    """Serves /ok (200), /moved (301 -> /ok), /gone (404), /slow (200)."""

    def do_GET(self):
        if self.path == "/ok":
            self._send(200, b"fine")
        elif self.path == "/moved":
            self.send_response(301)
            self.send_header("Location", "/ok")
            self.end_headers()
        elif self.path == "/gone":
            self._send(404, b"not here")
        else:
            self._send(500, b"boom")

    def _send(self, code, body):
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # keep test output clean
        pass


class CheckerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), _Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def test_ok_page(self):
        result = checker.check_url(self.url("/ok"))
        self.assertEqual(result.status, 200)
        self.assertEqual(result.summary, "OK")
        self.assertTrue(result.ok)

    def test_redirect_followed(self):
        result = checker.check_url(self.url("/moved"))
        self.assertEqual(result.status, 200)
        self.assertEqual(result.summary, "REDIRECT")
        self.assertTrue(result.redirects)

    def test_broken_page(self):
        result = checker.check_url(self.url("/gone"))
        self.assertEqual(result.status, 404)
        self.assertEqual(result.summary, "BROKEN")
        self.assertFalse(result.ok)

    def test_server_error_is_broken(self):
        result = checker.check_url(self.url("/other"))
        self.assertEqual(result.status, 500)
        self.assertEqual(result.summary, "BROKEN")

    def test_unreachable_host_is_error(self):
        result = checker.check_url("http://127.0.0.1:1/", timeout=2)
        self.assertEqual(result.summary, "ERROR")
        self.assertTrue(result.error)

    def test_normalise_adds_scheme(self):
        self.assertEqual(checker.normalise_url("example.com"), "https://example.com")
        self.assertEqual(checker.normalise_url("http://x.test"), "http://x.test")

    def test_read_url_list_skips_comments_and_blanks(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as tmp:
            tmp.write("# comment\n\nhttps://a.test\nb.test\n")
            path = tmp.name
        try:
            urls = checker.read_url_list(path)
        finally:
            os.unlink(path)
        self.assertEqual(urls, ["https://a.test", "https://b.test"])

    def test_collect_urls_dedupes(self):
        urls = checker.collect_urls(["https://a.test", "a.test", "https://b.test"])
        self.assertEqual(urls, ["https://a.test", "https://b.test"])

    def test_write_csv_roundtrip(self):
        results = checker.check_all([self.url("/ok"), self.url("/gone")])
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as tmp:
            path = tmp.name
        try:
            checker.write_csv(results, path)
            with open(path, newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
        finally:
            os.unlink(path)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["summary"], "OK")
        self.assertEqual(rows[0]["status"], "200")
        self.assertEqual(rows[1]["summary"], "BROKEN")
        self.assertEqual(rows[1]["status"], "404")

    def test_main_exit_code(self):
        self.assertEqual(checker.main([self.url("/ok")]), 0)
        self.assertEqual(checker.main([self.url("/gone")]), 1)
        # No inputs at all: argparse itself exits with code 2.
        with self.assertRaises(SystemExit) as ctx:
            checker.main([])
        self.assertEqual(ctx.exception.code, 2)
        # A file with only comments resolves to zero URLs: main returns 2.
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as tmp:
            tmp.write("# nothing here\n")
            path = tmp.name
        try:
            self.assertEqual(checker.main([path]), 2)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
