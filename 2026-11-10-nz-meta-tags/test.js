/**
 * Tests for nz-meta-tags — run with: node --test test.js
 * Uses only Node's built-in test runner and assert (no dependencies).
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { escapeHtml, truncateSmart, validate, buildTags, checkFile } = require('./meta-tags.js');

const SCRIPT = path.join(__dirname, 'meta-tags.js');

test('escapeHtml escapes attribute-breaking characters', () => {
  assert.equal(escapeHtml('a "quoted" <b> & \'thing\''), 'a &quot;quoted&quot; &lt;b&gt; &amp; &#39;thing&#39;');
});

test('truncateSmart leaves short text alone', () => {
  assert.equal(truncateSmart('Short title', 60), 'Short title');
});

test('truncateSmart cuts at a word boundary and adds an ellipsis', () => {
  const long = 'WordPress SEO Services That Help Small Businesses Rank Higher On Google Every Day';
  const out = truncateSmart(long, 60);
  assert.ok(out.length <= 60, `got ${out.length} chars: ${out}`);
  assert.ok(out.endsWith('…'));
  assert.ok(!out.includes('  '));
});

test('buildTags emits title, description, canonical, OG and Twitter tags', () => {
  const tags = buildTags({
    title: 'Web Design Services',
    description: 'Affordable WordPress websites for small businesses.',
    url: 'https://nzgenix.digital/services/',
    image: 'https://nzgenix.digital/og.jpg',
    siteName: 'NZGenix',
  });
  assert.match(tags, /<title>Web Design Services<\/title>/);
  assert.match(tags, /<meta name="description" content="Affordable WordPress websites/);
  assert.match(tags, /<link rel="canonical" href="https:\/\/nzgenix\.digital\/services\/">/);
  assert.match(tags, /<meta property="og:type" content="website">/);
  assert.match(tags, /<meta property="og:image" content="https:\/\/nzgenix\.digital\/og\.jpg">/);
  assert.match(tags, /<meta name="twitter:card" content="summary_large_image">/);
  assert.match(tags, /"@type": "WebPage"/);
});

test('buildTags uses summary card when no image is given', () => {
  const tags = buildTags({ title: 'T', description: 'D', url: 'https://example.com/' });
  assert.match(tags, /<meta name="twitter:card" content="summary">/);
  assert.doesNotMatch(tags, /og:image/);
});

test('buildTags adds article fields for article type', () => {
  const tags = buildTags({
    title: 'AI SEO in 2026', description: 'How AI search changes SEO.',
    url: 'https://example.com/blog/ai-seo', type: 'article',
    author: 'Nasir Naseer', date: '2026-11-10',
  });
  assert.match(tags, /<meta property="article:published_time" content="2026-11-10">/);
  assert.match(tags, /<meta property="article:author" content="Nasir Naseer">/);
  assert.match(tags, /"@type": "Article"/);
});

test('validate flags an over-long title and a missing URL', () => {
  const warnings = validate({ title: 'x'.repeat(80), description: 'ok' });
  assert.ok(warnings.some((w) => w.includes('title is 80 chars')));
  assert.ok(warnings.some((w) => w.includes('missing --url')));
});

test('validate is quiet for a well-formed page', () => {
  const warnings = validate({
    title: 'Web Design Services',
    description: 'Affordable WordPress websites for small businesses, designed fast, mobile-friendly and ranked on Google for local search.',
    url: 'https://nzgenix.digital/services/',
    image: 'https://nzgenix.digital/og.jpg',
  });
  assert.deepEqual(warnings, []);
});

test('checkFile reports problems in a bare HTML file', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'nz-meta-'));
  const file = path.join(dir, 'page.html');
  fs.writeFileSync(file, '<html><head><title>' + 'x'.repeat(90) + '</title></head></html>');
  const result = checkFile(file);
  assert.ok(result.problems.some((p) => p.includes('over 60')));
  assert.ok(result.problems.some((p) => p.includes('no meta description')));
  assert.ok(result.problems.some((p) => p.includes('no canonical')));
  fs.rmSync(dir, { recursive: true, force: true });
});

test('CLI generates tags from flags and from a JSON file', () => {
  const out = execFileSync('node', [SCRIPT, '--title', 'Hello', '--description', 'World page.', '--url', 'https://example.com/'], { encoding: 'utf8' });
  assert.match(out, /<title>Hello<\/title>/);
  assert.match(out, /og:url/);

  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'nz-meta-'));
  const json = path.join(dir, 'page.json');
  fs.writeFileSync(json, JSON.stringify({ title: 'From JSON', description: 'Loaded from a file.', url: 'https://example.com/json' }));
  const out2 = execFileSync('node', [SCRIPT, '--input', json], { encoding: 'utf8' });
  assert.match(out2, /<title>From JSON<\/title>/);
  fs.rmSync(dir, { recursive: true, force: true });
});

test('CLI --check exits non-zero on a page with problems', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'nz-meta-'));
  const file = path.join(dir, 'bad.html');
  fs.writeFileSync(file, '<html><head></head><body>no meta at all</body></html>');
  let code = 0;
  try {
    execFileSync('node', [SCRIPT, '--check', file], { encoding: 'utf8' });
  } catch (err) {
    code = err.status;
  }
  assert.equal(code, 1);
  fs.rmSync(dir, { recursive: true, force: true });
});
