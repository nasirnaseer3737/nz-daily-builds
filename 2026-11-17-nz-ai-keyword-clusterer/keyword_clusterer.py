#!/usr/bin/env python3
"""NZ AI Keyword Clusterer — group SEO keywords into topic clusters.

Reads a CSV of keywords (keyword, search_volume, difficulty) and groups them
into topic clusters, one pillar page per cluster, with a short content brief.

With NZ_GEMINI_API_KEY set it asks the Gemini API (free tier) to cluster the
keywords semantically; without a key (or with --mock) it uses a clearly
labelled offline heuristic: token overlap + shared head/tail phrases, merged
with a union-find pass. The heuristic is a real working fallback, not a
placeholder — it just cannot judge meaning the way an LLM can.

Usage:
    python3 keyword_clusterer.py --input sample_keywords.csv --out-dir out
    NZ_GEMINI_API_KEY=<key> python3 keyword_clusterer.py -i keywords.csv -o out
    python3 keyword_clusterer.py -i keywords.csv -o out --mock --max-clusters 8

Outputs (in --out-dir):
    clusters.json  machine-readable clusters
    clusters.csv   one row per keyword with its cluster
    clusters.md    human report: pillar page + brief per cluster

The API key is NEVER hardcoded or written to any output file — it is read
only from the NZ_GEMINI_API_KEY environment variable.
"""

import argparse
import csv
import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections import Counter, defaultdict

VERSION = "1.0.0"
GEMINI_MODEL = "gemini-2.0-flash"
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    + GEMINI_MODEL
    + ":generateContent"
)

# Words that carry no topic meaning on their own.
STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "for", "to", "in", "on", "with",
    "how", "what", "why", "when", "best", "top", "free", "near", "me",
    "is", "are", "do", "does", "can", "should", "vs", "versus", "by",
}

# Common English suffixes stripped for a light stem (offline fallback only).
SUFFIXES = ("ing", "ies", "es", "ed", "er", "ers", "ly", "s")


def stem(word):
    """Very light stemmer: strip one common suffix if the root stays long.

    Guards: words ending in "ss" (e.g. wordpress) are left alone, and
    words ending in "ices" (e.g. services) lose only the final "s".
    """
    if word.endswith("ss"):
        return word
    if word.endswith("ies") and len(word) - 3 >= 3:
        return word[:-3] + "y"
    if word.endswith("ices") and len(word) - 1 >= 3:
        return word[:-1]
    for suffix in SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def tokenize(keyword):
    """Lowercase a keyword into a set of meaningful stemmed tokens."""
    words = re.findall(r"[a-z0-9]+", keyword.lower())
    return {stem(w) for w in words if w not in STOPWORDS and len(w) > 1}


def load_keywords(path):
    """Load keywords from CSV. Returns list of dicts.

    Columns: keyword (required), search_volume (optional int),
    difficulty (optional 0-100 int), url (optional).
    Blank rows, duplicate keywords (case-insensitive) and rows without a
    keyword are skipped; the skip count is returned for reporting.
    """
    keywords = []
    seen = set()
    skipped = 0
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("empty CSV file: %s" % path)
        lowered = {name.strip().lower(): name for name in reader.fieldnames}
        if "keyword" not in lowered:
            raise ValueError("CSV must have a 'keyword' column")
        key_col = lowered["keyword"]
        vol_col = lowered.get("search_volume")
        diff_col = lowered.get("difficulty")
        url_col = lowered.get("url")
        for row in reader:
            raw = (row.get(key_col) or "").strip()
            if not raw:
                skipped += 1
                continue
            if raw.lower() in seen:
                skipped += 1
                continue
            seen.add(raw.lower())
            try:
                volume = int(float(row.get(vol_col) or 0)) if vol_col else 0
            except ValueError:
                volume = 0
            try:
                difficulty = int(float(row.get(diff_col) or 0)) if diff_col else 0
            except ValueError:
                difficulty = 0
            difficulty = max(0, min(100, difficulty))
            keywords.append({
                "keyword": raw,
                "search_volume": max(0, volume),
                "difficulty": difficulty,
                "url": (row.get(url_col) or "").strip() if url_col else "",
            })
    return keywords, skipped


def jaccard(a, b):
    """Jaccard similarity of two token sets (0.0 - 1.0)."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def head_tail_phrase(keyword):
    """First two / last two words of a keyword, for phrase-overlap checks."""
    words = re.findall(r"[a-z0-9]+", keyword.lower())
    words = [w for w in words if w not in STOPWORDS]
    if len(words) < 2:
        return set()
    return {" ".join(words[:2]), " ".join(words[-2:])}


def mock_cluster(keywords, min_similarity=0.34):
    """Offline heuristic clustering.

    Two keywords join the same cluster when their stemmed-token Jaccard
    similarity reaches min_similarity, or when they share a head/tail
    two-word phrase. Union-find merges the pairs transitively.
    Returns a list of clusters (lists of keyword dicts), largest first.
    """
    n = len(keywords)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    tokens = [tokenize(k["keyword"]) for k in keywords]
    phrases = [head_tail_phrase(k["keyword"]) for k in keywords]
    for i in range(n):
        for j in range(i + 1, n):
            if jaccard(tokens[i], tokens[j]) >= min_similarity:
                union(i, j)
            elif phrases[i] & phrases[j]:
                union(i, j)

    groups = defaultdict(list)
    for i, keyword in enumerate(keywords):
        groups[find(i)].append(keyword)
    clusters = sorted(groups.values(),
                      key=lambda g: (-len(g), -sum(k["search_volume"] for k in g)))
    return clusters


def cluster_label(cluster):
    """Label a cluster from its most common stemmed tokens, then top keyword."""
    counts = Counter()
    for item in cluster:
        counts.update(tokenize(item["keyword"]))
    if counts:
        top = [w for w, _ in counts.most_common(2)]
        return " ".join(top)
    return cluster[0]["keyword"]


def pillar_keyword(cluster):
    """The keyword that should anchor the cluster's pillar page: most volume,
    ties broken by lowest difficulty, then shortest keyword."""
    return sorted(cluster,
                  key=lambda k: (-k["search_volume"], k["difficulty"],
                                 len(k["keyword"])))[0]


def slugify(text):
    """Turn a label into a URL-friendly slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "topic"


def mock_brief(label, cluster):
    """Labelled offline brief: pillar title, slug and a 2-sentence brief."""
    pillar = pillar_keyword(cluster)
    total_volume = sum(k["search_volume"] for k in cluster)
    avg_diff = (sum(k["difficulty"] for k in cluster) / len(cluster)
                if cluster else 0)
    others = [k["keyword"] for k in cluster if k is not pillar][:4]
    brief = (
        "Cover \"%s\" as the pillar topic (about %d monthly searches across "
        "%d keywords, average difficulty %d/100). " % (
            pillar["keyword"], total_volume, len(cluster), round(avg_diff))
        + ("Link supporting pages for %s back to this pillar page."
           % ", ".join('"%s"' % o for o in others) if others else
           "Answer the main question fully on one page.")
    )
    return {
        "label": label,
        "pillar_keyword": pillar["keyword"],
        "pillar_title": "The Complete Guide to %s" % pillar["keyword"].title(),
        "pillar_slug": "/%s/" % slugify(pillar["keyword"]),
        "total_volume": total_volume,
        "avg_difficulty": round(avg_diff, 1),
        "brief": brief,
        "source": "mock",
    }


def gemini_cluster(keywords, api_key, max_clusters):
    """Ask Gemini to cluster keywords. Returns list of clusters or None.

    The prompt demands strict JSON so the result is machine-readable. Any
    failure (network, HTTP error, bad JSON, empty result) returns None and
    the caller falls back to the mock clusterer.
    """
    listing = "\n".join(
        "%d. %s (volume %d, difficulty %d)" % (
            i + 1, k["keyword"], k["search_volume"], k["difficulty"])
        for i, k in enumerate(keywords))
    prompt = (
        "You are an SEO strategist. Group these keywords into at most %d "
        "topic clusters by search intent and meaning, so each cluster can be "
        "one pillar page. Reply with ONLY a JSON object, no markdown fences, "
        "no extra text: {\"clusters\": [{\"label\": \"short topic label\", "
        "\"pillar_keyword\": \"exact keyword from the list\", "
        "\"brief\": \"one or two sentences: what the pillar page should cover "
        "and which supporting keywords to link\"}, ...]}. Every keyword index "
        "must appear in exactly one cluster, referenced by its number in a "
        "\"members\": [1, 2, ...] list inside each cluster.\n\nKeywords:\n%s"
        % (max_clusters, listing))
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2},
    }).encode("utf-8")
    req = urllib.request.Request(
        GEMINI_URL + "?key=" + api_key,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, ValueError,
            TimeoutError, OSError):
        return None
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        return None
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    try:
        parsed = json.loads(text)
    except ValueError:
        return None
    raw_clusters = parsed.get("clusters") if isinstance(parsed, dict) else None
    if not raw_clusters:
        return None
    used = set()
    clusters = []
    for raw in raw_clusters:
        members = [keywords[i - 1] for i in raw.get("members", [])
                   if isinstance(i, int) and 1 <= i <= len(keywords)
                   and (i - 1) not in used]
        for i in raw.get("members", []):
            if isinstance(i, int) and 1 <= i <= len(keywords):
                used.add(i - 1)
        if not members:
            continue
        pillar_name = (raw.get("pillar_keyword") or "").strip().lower()
        pillar = next((m for m in members
                       if m["keyword"].lower() == pillar_name),
                      pillar_keyword(members))
        clusters.append({
            "label": (raw.get("label") or cluster_label(members)).strip(),
            "pillar_keyword": pillar["keyword"],
            "pillar_title": "The Complete Guide to %s" % pillar["keyword"].title(),
            "pillar_slug": "/%s/" % slugify(pillar["keyword"]),
            "total_volume": sum(k["search_volume"] for k in members),
            "avg_difficulty": round(
                sum(k["difficulty"] for k in members) / len(members), 1),
            "brief": (raw.get("brief") or "").strip() or
                     mock_brief(cluster_label(members), members)["brief"],
            "source": "gemini",
            "_members": members,
        })
    # Any keyword Gemini dropped goes into its own single-keyword cluster.
    leftovers = [k for i, k in enumerate(keywords) if i not in used]
    for item in leftovers:
        clusters.append(mock_brief(item["keyword"], [item]))
    return clusters


def build_clusters(keywords, api_key, max_clusters, min_similarity,
                   force_mock=False):
    """Cluster keywords. Returns (clusters, source) where source is
    'gemini' or 'mock' (labelled in every output)."""
    if api_key and not force_mock:
        ai_clusters = gemini_cluster(keywords, api_key, max_clusters)
        if ai_clusters:
            return ai_clusters, "gemini"
    raw = mock_cluster(keywords, min_similarity)
    clusters = []
    for group in raw[:max_clusters] if max_clusters else raw:
        label = cluster_label(group)
        info = mock_brief(label, group)
        info["_members"] = group
        clusters.append(info)
    # If max_clusters cut groups off, merge the tail into the largest cluster.
    if max_clusters and len(raw) > max_clusters:
        tail = [k for group in raw[max_clusters:] for k in group]
        if tail:
            clusters[0]["_members"].extend(tail)
            clusters[0]["total_volume"] = sum(
                k["search_volume"] for k in clusters[0]["_members"])
            clusters[0]["avg_difficulty"] = round(
                sum(k["difficulty"] for k in clusters[0]["_members"])
                / len(clusters[0]["_members"]), 1)
            clusters[0]["brief"] = mock_brief(
                clusters[0]["label"], clusters[0]["_members"])["brief"]
    return clusters, "mock"


def write_outputs(clusters, source, out_dir):
    """Write clusters.json, clusters.csv and clusters.md. Returns paths."""
    os.makedirs(out_dir, exist_ok=True)
    serializable = []
    csv_rows = []
    for idx, cluster in enumerate(clusters, start=1):
        members = sorted(cluster["_members"],
                         key=lambda k: (-k["search_volume"], k["keyword"]))
        serializable.append({
            "id": idx,
            "label": cluster["label"],
            "pillar_keyword": cluster["pillar_keyword"],
            "pillar_title": cluster["pillar_title"],
            "pillar_slug": cluster["pillar_slug"],
            "total_volume": cluster["total_volume"],
            "avg_difficulty": cluster["avg_difficulty"],
            "keywords": [m["keyword"] for m in members],
            "brief": cluster["brief"],
            "source": cluster["source"],
        })
        for member in members:
            csv_rows.append({
                "cluster_id": idx,
                "cluster_label": cluster["label"],
                "keyword": member["keyword"],
                "search_volume": member["search_volume"],
                "difficulty": member["difficulty"],
                "pillar": "yes" if member["keyword"] == cluster["pillar_keyword"]
                          else "",
            })

    json_path = os.path.join(out_dir, "clusters.json")
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump({"source": source, "clusters": serializable}, handle,
                  indent=2, ensure_ascii=False)

    csv_path = os.path.join(out_dir, "clusters.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "cluster_id", "cluster_label", "keyword", "search_volume",
            "difficulty", "pillar"])
        writer.writeheader()
        writer.writerows(csv_rows)

    md_path = os.path.join(out_dir, "clusters.md")
    lines = ["# Keyword Clusters\n",
             "Source: %s (%s)\n" % (
                 "Gemini AI" if source == "gemini" else "offline mock heuristic",
                 "real AI clustering" if source == "gemini"
                 else "labelled mock — set NZ_GEMINI_API_KEY for AI clustering"),
             "| # | Cluster | Pillar keyword | Keywords | Total volume | "
             "Avg difficulty |",
             "|---|---------|---------------|----------|--------------|---------------|"]
    for item in serializable:
        lines.append("| %d | %s | %s | %d | %d | %.1f |" % (
            item["id"], item["label"], item["pillar_keyword"],
            len(item["keywords"]), item["total_volume"],
            item["avg_difficulty"]))
    lines.append("")
    for item in serializable:
        lines.append("## %d. %s\n" % (item["id"], item["label"]))
        lines.append("- **Pillar page:** %s (`%s`)" % (
            item["pillar_title"], item["pillar_slug"]))
        lines.append("- **Pillar keyword:** %s" % item["pillar_keyword"])
        lines.append("- **Keywords (%d):** %s" % (
            len(item["keywords"]), ", ".join(item["keywords"])))
        lines.append("- **Brief:** %s\n" % item["brief"])
    with open(md_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    return json_path, csv_path, md_path


def run(input_path, out_dir, api_key, max_clusters, min_similarity,
        force_mock=False):
    """Full pipeline. Returns a summary dict."""
    keywords, skipped = load_keywords(input_path)
    if not keywords:
        raise ValueError("no usable keywords in %s" % input_path)
    clusters, source = build_clusters(keywords, api_key, max_clusters,
                                      min_similarity, force_mock)
    json_path, csv_path, md_path = write_outputs(clusters, source, out_dir)
    return {
        "keywords": len(keywords),
        "skipped": skipped,
        "clusters": len(clusters),
        "source": source,
        "largest_cluster": max(len(c["_members"]) for c in clusters)
                         if clusters else 0,
        "outputs": [json_path, csv_path, md_path],
    }


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Cluster SEO keywords into pillar-page topic clusters "
                    "(Gemini AI with a labelled offline mock fallback).")
    parser.add_argument("-i", "--input", required=True,
                        help="keywords CSV (keyword, search_volume, difficulty)")
    parser.add_argument("-o", "--out-dir", default="out",
                        help="output directory (default: out)")
    parser.add_argument("--max-clusters", type=int, default=10,
                        help="maximum number of clusters (default: 10)")
    parser.add_argument("--min-similarity", type=float, default=0.34,
                        help="mock token-overlap threshold 0-1 (default: 0.34)")
    parser.add_argument("--mock", action="store_true",
                        help="force the labelled offline mock, ignore the API key")
    parser.add_argument("--version", action="version",
                        version="nz-ai-keyword-clusterer " + VERSION)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    api_key = os.environ.get("NZ_GEMINI_API_KEY", "").strip()
    if not (0.0 <= args.min_similarity <= 1.0):
        print("error: --min-similarity must be between 0 and 1",
              file=sys.stderr)
        return 2
    try:
        summary = run(args.input, args.out_dir, api_key, args.max_clusters,
                      args.min_similarity, args.mock)
    except (OSError, ValueError) as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1
    if summary["source"] == "gemini":
        print("Clustered with Gemini AI.")
    else:
        print("Note: NZ_GEMINI_API_KEY not set (or --mock used / AI call "
              "failed) — using the labelled offline mock clusterer.")
    print("Keywords: %d (%d skipped), clusters: %d, source: %s"
          % (summary["keywords"], summary["skipped"], summary["clusters"],
             summary["source"]))
    for path in summary["outputs"]:
        print("Wrote %s" % path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
