#!/usr/bin/env python3
"""Tests for nz-ai-keyword-clusterer. Run: python3 -m unittest -v test_keyword_clusterer"""

import csv
import io
import json
import os
import tempfile
import unittest

from keyword_clusterer import (
    build_clusters,
    cluster_label,
    gemini_cluster,
    head_tail_phrase,
    jaccard,
    load_keywords,
    mock_brief,
    mock_cluster,
    pillar_keyword,
    run,
    slugify,
    stem,
    tokenize,
)

SAMPLE = """keyword,search_volume,difficulty
wordpress seo plugin,8100,45
best wordpress seo plugin,5400,52
wordpress seo plugin free,2900,38
yoast seo vs rank math,6600,41
rank math seo setup guide,1900,33
local seo for plumbers,2400,29
plumber seo services,1800,35
how to rank a plumbing website,900,27
ai lead generation tools,4400,58
best ai lead generation software,3600,61
lead generation automation,2700,49
whatsapp marketing for clinics,1500,31
dental clinic website design,2200,36
dentist website design cost,1300,28
"""


def write_sample(directory, content=SAMPLE):
    path = os.path.join(directory, "keywords.csv")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)
    return path


class TestTextHelpers(unittest.TestCase):
    def test_stem_strips_suffixes(self):
        self.assertEqual(stem("plugins"), "plugin")
        self.assertEqual(stem("ranking"), "rank")
        self.assertEqual(stem("services"), "service")
        self.assertEqual(stem("seo"), "seo")

    def test_tokenize_drops_stopwords(self):
        tokens = tokenize("Best WordPress SEO Plugin Free")
        self.assertEqual(tokens, {"wordpress", "seo", "plugin"})

    def test_jaccard(self):
        self.assertAlmostEqual(jaccard({"a", "b"}, {"b", "c"}), 1 / 3)
        self.assertEqual(jaccard({"a"}, {"a"}), 1.0)
        self.assertEqual(jaccard(set(), {"a"}), 0.0)

    def test_slugify(self):
        self.assertEqual(slugify("WordPress SEO Plugin"), "wordpress-seo-plugin")
        self.assertEqual(slugify("  AI & Lead Gen! "), "ai-lead-gen")

    def test_head_tail_phrase(self):
        phrases = head_tail_phrase("best wordpress seo plugin free")
        self.assertIn("wordpress seo", phrases)
        self.assertIn("seo plugin", phrases)


class TestLoadKeywords(unittest.TestCase):
    def test_loads_sample(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_sample(tmp)
            keywords, skipped = load_keywords(path)
            self.assertEqual(len(keywords), 14)
            self.assertEqual(skipped, 0)
            self.assertEqual(keywords[0]["keyword"], "wordpress seo plugin")
            self.assertEqual(keywords[0]["search_volume"], 8100)
            self.assertEqual(keywords[0]["difficulty"], 45)

    def test_dedupes_and_skips_blanks(self):
        content = ("keyword,search_volume,difficulty\n"
                   "WordPress SEO,100,10\nwordpress seo,200,20\n"
                   "   ,50,5\nlocal seo,50,5\n")
        with tempfile.TemporaryDirectory() as tmp:
            path = write_sample(tmp, content)
            keywords, skipped = load_keywords(path)
            self.assertEqual(len(keywords), 2)
            self.assertEqual(skipped, 2)

    def test_missing_keyword_column(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_sample(tmp, "term,volume\nfoo,1\n")
            with self.assertRaises(ValueError):
                load_keywords(path)

    def test_bad_numbers_become_zero(self):
        content = "keyword,search_volume,difficulty\nfoo bar,abc,xyz\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = write_sample(tmp, content)
            keywords, _ = load_keywords(path)
            self.assertEqual(keywords[0]["search_volume"], 0)
            self.assertEqual(keywords[0]["difficulty"], 0)

    def test_difficulty_clamped(self):
        content = "keyword,search_volume,difficulty\nfoo bar,10,150\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = write_sample(tmp, content)
            keywords, _ = load_keywords(path)
            self.assertEqual(keywords[0]["difficulty"], 100)


class TestMockClustering(unittest.TestCase):
    def setUp(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.keywords, _ = load_keywords(write_sample(tmp))

    def test_groups_related_keywords(self):
        clusters = mock_cluster(self.keywords)
        flat = [sorted(k["keyword"] for k in c) for c in clusters]
        wp = [g for g in flat if "wordpress seo plugin" in g][0]
        self.assertIn("best wordpress seo plugin", wp)
        self.assertIn("wordpress seo plugin free", wp)

    def test_separates_unrelated_topics(self):
        clusters = mock_cluster(self.keywords)
        flat = [set(k["keyword"] for k in c) for c in clusters]
        wp = next(g for g in flat if "wordpress seo plugin" in g)
        self.assertNotIn("local seo for plumbers", wp)
        self.assertNotIn("ai lead generation tools", wp)

    def test_clusters_cover_all_keywords(self):
        clusters = mock_cluster(self.keywords)
        total = sum(len(c) for c in clusters)
        self.assertEqual(total, len(self.keywords))

    def test_clusters_sorted_largest_first(self):
        clusters = mock_cluster(self.keywords)
        sizes = [len(c) for c in clusters]
        self.assertEqual(sizes, sorted(sizes, reverse=True))

    def test_pillar_is_highest_volume(self):
        clusters = mock_cluster(self.keywords)
        wp = next(c for c in clusters
                  if any(k["keyword"] == "wordpress seo plugin" for k in c))
        self.assertEqual(pillar_keyword(wp)["keyword"],
                         "wordpress seo plugin")

    def test_label_and_brief(self):
        clusters = mock_cluster(self.keywords)
        info = mock_brief(cluster_label(clusters[0]), clusters[0])
        self.assertTrue(info["label"])
        self.assertTrue(info["pillar_slug"].startswith("/"))
        self.assertTrue(info["pillar_slug"].endswith("/"))
        self.assertIn(str(info["total_volume"]), info["brief"])
        self.assertEqual(info["source"], "mock")


class TestBuildClusters(unittest.TestCase):
    def setUp(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.keywords, _ = load_keywords(write_sample(tmp))

    def test_mock_mode_returns_mock_source(self):
        clusters, source = build_clusters(self.keywords, "", 10, 0.34,
                                          force_mock=True)
        self.assertEqual(source, "mock")
        self.assertTrue(2 <= len(clusters) <= 10)
        for cluster in clusters:
            self.assertEqual(cluster["source"], "mock")
            self.assertIn("_members", cluster)

    def test_max_clusters_merges_tail(self):
        clusters, _ = build_clusters(self.keywords, "", 3, 0.34,
                                     force_mock=True)
        self.assertEqual(len(clusters), 3)
        total = sum(len(c["_members"]) for c in clusters)
        self.assertEqual(total, len(self.keywords))

    def test_gemini_failure_falls_back_to_mock(self):
        clusters, source = build_clusters(self.keywords, "bad-key", 10, 0.34)
        self.assertEqual(source, "mock")
        self.assertTrue(len(clusters) >= 2)

    def test_gemini_cluster_rejects_garbage(self):
        self.assertIsNone(gemini_cluster(self.keywords, "bad-key", 10))


class TestFullRun(unittest.TestCase):
    def test_run_writes_all_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_path = write_sample(tmp)
            out_dir = os.path.join(tmp, "out")
            summary = run(input_path, out_dir, "", 10, 0.34, force_mock=True)
            self.assertEqual(summary["keywords"], 14)
            self.assertEqual(summary["source"], "mock")
            self.assertTrue(summary["clusters"] >= 2)
            for name in ("clusters.json", "clusters.csv", "clusters.md"):
                self.assertTrue(os.path.exists(os.path.join(out_dir, name)))
            with open(os.path.join(out_dir, "clusters.json"),
                      encoding="utf-8") as handle:
                data = json.load(handle)
            self.assertEqual(data["source"], "mock")
            total = sum(len(c["keywords"]) for c in data["clusters"])
            self.assertEqual(total, 14)
            with open(os.path.join(out_dir, "clusters.csv"),
                      encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 14)
            pillars = [r for r in rows if r["pillar"] == "yes"]
            self.assertEqual(len(pillars), len(data["clusters"]))
            with open(os.path.join(out_dir, "clusters.md"),
                      encoding="utf-8") as handle:
                md = handle.read()
            self.assertIn("Pillar page", md)
            self.assertIn("wordpress seo plugin", md.lower())

    def test_run_empty_csv_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_path = write_sample(tmp, "keyword,search_volume\n")
            with self.assertRaises(ValueError):
                run(input_path, os.path.join(tmp, "out"), "", 10, 0.34, True)


if __name__ == "__main__":
    unittest.main()
