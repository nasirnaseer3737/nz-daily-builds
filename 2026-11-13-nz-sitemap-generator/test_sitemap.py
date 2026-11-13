#!/usr/bin/env python3
"""Tests for nz-sitemap-generator (stdlib unittest). Run: python3 -m unittest -v test_sitemap"""

import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import sitemap as sm

NS = {"s": sm.SITEMAP_NS}


class TestValidation(unittest.TestCase):
    def test_valid_url_kept_and_lowercased(self):
        self.assertEqual(sm.validate_url("HTTPS://Example.COM/Blog/"),
                         "https://example.com/Blog/")

    def test_fragment_dropped(self):
        self.assertEqual(sm.validate_url("https://example.com/page#top"),
                         "https://example.com/page")

    def test_bad_scheme_rejected(self):
        with self.assertRaises(sm.SitemapError):
            sm.validate_url("ftp://example.com/x")

    def test_no_host_rejected(self):
        with self.assertRaises(sm.SitemapError):
            sm.validate_url("https://")

    def test_good_lastmod(self):
        self.assertEqual(sm.validate_lastmod("2026-11-13"), "2026-11-13")

    def test_bad_lastmod_format(self):
        with self.assertRaises(sm.SitemapError):
            sm.validate_lastmod("13/11/2026")

    def test_impossible_lastmod(self):
        with self.assertRaises(sm.SitemapError):
            sm.validate_lastmod("2026-02-30")

    def test_future_lastmod_rejected(self):
        with self.assertRaises(sm.SitemapError):
            sm.validate_lastmod("2999-01-01")


class TestHeuristics(unittest.TestCase):
    def test_priority_by_depth(self):
        self.assertEqual(sm.priority_for("https://example.com/"), "1.0")
        self.assertEqual(sm.priority_for("https://example.com/about"), "0.9")
        self.assertEqual(sm.priority_for("https://example.com/a/b/c/d/e/f/g"), "0.3")

    def test_changefreq(self):
        self.assertEqual(sm.changefreq_for("https://example.com/"), "daily")
        self.assertEqual(sm.changefreq_for("https://example.com/blog/post"), "weekly")
        self.assertEqual(sm.changefreq_for("https://example.com/services/seo"), "monthly")


class TestUrlList(unittest.TestCase):
    def test_comments_blanks_and_duplicates(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "urls.txt"
            p.write_text("# comment\n\nhttps://example.com/\n"
                         "https://example.com/about,2026-11-01\n"
                         "https://example.com/\n", encoding="utf-8")
            entries = sm.read_url_list(p)
        self.assertEqual([e["loc"] for e in entries],
                         ["https://example.com/", "https://example.com/about"])
        self.assertEqual(entries[1]["lastmod"], "2026-11-01")

    def test_bad_line_reports_lineno(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "urls.txt"
            p.write_text("https://example.com/\nnot-a-url\n", encoding="utf-8")
            with self.assertRaises(sm.SitemapError) as ctx:
                sm.read_url_list(p)
        self.assertIn(":2:", str(ctx.exception))


class TestScanFolder(unittest.TestCase):
    def test_index_html_maps_to_directory(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "blog").mkdir()
            (root / "index.html").write_text("<h1>home</h1>")
            (root / "blog" / "index.html").write_text("<h1>blog</h1>")
            (root / "blog" / "post.html").write_text("<h1>post</h1>")
            (root / "style.css").write_text("body{}")
            entries = sm.scan_folder(root, "https://example.com")
        self.assertEqual([e["loc"] for e in entries], [
            "https://example.com/",
            "https://example.com/blog/",
            "https://example.com/blog/post.html",
        ])
        self.assertTrue(all("lastmod" in e for e in entries))


class TestXmlOutput(unittest.TestCase):
    def test_sitemap_xml_is_valid_and_complete(self):
        entries = [{"loc": "https://example.com/", "lastmod": "2026-11-13"},
                   {"loc": "https://example.com/blog/post"}]
        xml = sm.build_sitemap_xml(entries)
        root = ET.fromstring(xml)
        self.assertEqual(root.tag, f"{{{sm.SITEMAP_NS}}}urlset")
        urls = root.findall("s:url", NS)
        self.assertEqual(len(urls), 2)
        self.assertEqual(urls[0].findtext("s:loc", namespaces=NS),
                         "https://example.com/")
        self.assertEqual(urls[0].findtext("s:priority", namespaces=NS), "1.0")
        self.assertEqual(urls[1].findtext("s:changefreq", namespaces=NS), "weekly")
        self.assertIsNone(urls[1].find("s:lastmod", NS))

    def test_too_many_urls_rejected(self):
        with self.assertRaises(sm.SitemapError):
            sm.build_sitemap_xml([{"loc": "https://example.com/"}]
                                 * (sm.MAX_URLS_PER_SITEMAP + 1))

    def test_index_xml(self):
        xml = sm.build_index_xml(["sitemap-1.xml", "sitemap-2.xml"],
                                 "https://example.com", "2026-11-13")
        root = ET.fromstring(xml)
        self.assertEqual(len(root.findall("s:sitemap", NS)), 2)
        self.assertEqual(root.find("s:sitemap/s:loc", NS).text,
                         "https://example.com/sitemap-1.xml")

    def test_split_chunks(self):
        entries = [{"loc": f"https://example.com/p{i}"} for i in range(3)]
        self.assertEqual(len(sm.split_entries(entries)), 1)


class TestGenerateEndToEnd(unittest.TestCase):
    def test_single_file_and_split_modes(self):
        entries = [{"loc": f"https://example.com/page-{i}"} for i in range(5)]
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "sitemap.xml"
            written = sm.generate(entries, out)
            self.assertEqual(len(written), 1)
            self.assertTrue(written[0].read_bytes().startswith(b'<?xml'))
            root = ET.parse(written[0]).getroot()
            self.assertEqual(len(root.findall("s:url", NS)), 5)

    def test_generate_empty_raises(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(sm.SitemapError):
                sm.generate([], Path(td) / "sitemap.xml")

    def test_cli_happy_path(self):
        with tempfile.TemporaryDirectory() as td:
            urls = Path(td) / "urls.txt"
            urls.write_text("https://example.com/\nhttps://example.com/about\n")
            out = Path(td) / "out.xml"
            self.assertEqual(sm.main([str(urls), "--out", str(out)]), 0)
            self.assertTrue(out.exists())

    def test_cli_missing_input_is_error(self):
        self.assertEqual(sm.main(["--out", "x.xml"]), 1)


if __name__ == "__main__":
    unittest.main()
