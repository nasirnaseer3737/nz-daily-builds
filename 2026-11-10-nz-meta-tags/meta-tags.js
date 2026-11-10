#!/usr/bin/env node
/**
 * nz-meta-tags — generate SEO meta tags for a web page.
 *
 * A zero-dependency Node.js CLI (stdlib only). Give it a page title,
 * description and URL and it prints a ready-to-paste block of HTML:
 * standard meta tags, Open Graph, Twitter Card, canonical link and
 * JSON-LD (Schema.org WebPage). It also warns when the title or
 * description is too long for Google's search results.
 *
 * Usage:
 *   node meta-tags.js --title "My Page" --description "..." --url "https://example.com/page"
 *   node meta-tags.js --input page.json [--out tags.html]
 *   node meta-tags.js --check existing-snippet.html
 *
 * Options:
 *   --title       Page title (recommended: 50-60 characters)
 *   --description Meta description (recommended: 120-160 characters)
 *   --url         Canonical URL of the page
 *   --image       Open Graph / Twitter image URL (absolute)
 *   --type        Open Graph type: website (default) or article
 *   --site-name   Site name for og:site_name
 *   --author      Author name (article only)
 *   --date        Publication date, e.g. 2026-11-10 (article only)
 *   --input       JSON file with the same fields
 *   --out         Write the tags to a file instead of stdout
 *   --check       Validate an existing HTML file's meta tags and exit
 */

'use strict';

const fs = require('node:fs');
const path = require('node:path');

const TITLE_MAX = 60;
const DESCRIPTION_MAX = 160;
const DESCRIPTION_MIN = 120;

/** Escape text for safe use inside HTML attributes and elements. */
function escapeHtml(text) {
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/**
 * Shorten text to at most `max` characters, cutting at the last word
 * boundary before the limit and appending an ellipsis. Short text is
 * returned unchanged.
 */
function truncateSmart(text, max) {
  const clean = String(text).trim().replace(/\s+/g, ' ');
  if (clean.length <= max) return clean;
  const cut = clean.slice(0, max - 1);
  const lastSpace = cut.lastIndexOf(' ');
  const shortened = lastSpace > max * 0.5 ? cut.slice(0, lastSpace) : cut;
  return shortened.trimEnd() + '…';
}

/** Collect warnings about lengths and missing fields. */
function validate(data) {
  const warnings = [];
  if (!data.title) warnings.push('missing --title');
  else if (data.title.length > TITLE_MAX) {
    warnings.push(`title is ${data.title.length} chars (over ${TITLE_MAX}); Google truncates it`);
  }
  if (!data.description) warnings.push('missing --description');
  else if (data.description.length > DESCRIPTION_MAX) {
    warnings.push(`description is ${data.description.length} chars (over ${DESCRIPTION_MAX}); Google truncates it`);
  } else if (data.description.length < DESCRIPTION_MIN) {
    warnings.push(`description is only ${data.description.length} chars (under ${DESCRIPTION_MIN}); a fuller one ranks better`);
  }
  if (!data.url) warnings.push('missing --url (no canonical link will be emitted)');
  else if (!/^https?:\/\//.test(data.url)) warnings.push('url should be absolute (start with https://)');
  if (data.image && !/^https?:\/\//.test(data.image)) {
    warnings.push('image should be an absolute URL or social previews may fail');
  }
  if (data.type === 'article' && !data.date) warnings.push('article type without --date (no article:published_time)');
  return warnings;
}

/** Build the full HTML tag block from validated page data. */
function buildTags(data) {
  const title = truncateSmart(data.title || '', TITLE_MAX);
  const description = truncateSmart(data.description || '', DESCRIPTION_MAX);
  const url = data.url || '';
  const image = data.image || '';
  const type = data.type === 'article' ? 'article' : 'website';
  const siteName = data.siteName || '';
  const lines = [];

  lines.push(`<title>${escapeHtml(title)}</title>`);
  if (description) lines.push(`<meta name="description" content="${escapeHtml(description)}">`);
  if (url) lines.push(`<link rel="canonical" href="${escapeHtml(url)}">`);
  lines.push('<meta property="og:type" content="' + type + '">');
  lines.push(`<meta property="og:title" content="${escapeHtml(title)}">`);
  if (description) lines.push(`<meta property="og:description" content="${escapeHtml(description)}">`);
  if (url) lines.push(`<meta property="og:url" content="${escapeHtml(url)}">`);
  if (siteName) lines.push(`<meta property="og:site_name" content="${escapeHtml(siteName)}">`);
  if (image) {
    lines.push(`<meta property="og:image" content="${escapeHtml(image)}">`);
    lines.push('<meta name="twitter:card" content="summary_large_image">');
  } else {
    lines.push('<meta name="twitter:card" content="summary">');
  }
  lines.push(`<meta name="twitter:title" content="${escapeHtml(title)}">`);
  if (description) lines.push(`<meta name="twitter:description" content="${escapeHtml(description)}">`);
  if (image) lines.push(`<meta name="twitter:image" content="${escapeHtml(image)}">`);
  if (type === 'article' && data.date) {
    lines.push(`<meta property="article:published_time" content="${escapeHtml(data.date)}">`);
  }
  if (type === 'article' && data.author) {
    lines.push(`<meta property="article:author" content="${escapeHtml(data.author)}">`);
  }

  const jsonLd = {
    '@context': 'https://schema.org',
    '@type': type === 'article' ? 'Article' : 'WebPage',
    headline: title,
  };
  if (description) jsonLd.description = description;
  if (url) jsonLd.url = url;
  if (image) jsonLd.image = image;
  if (data.author) jsonLd.author = { '@type': 'Person', name: data.author };
  if (data.date) jsonLd.datePublished = data.date;
  lines.push('<script type="application/ld+json">');
  lines.push(JSON.stringify(jsonLd, null, 2));
  lines.push('</script>');

  return lines.join('\n');
}

/** Parse `--flag value` / `--flag=value` arguments into an object. */
function parseArgs(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (!arg.startsWith('--')) continue;
    const eq = arg.indexOf('=');
    const key = eq === -1 ? arg.slice(2) : arg.slice(2, eq);
    const value = eq === -1 ? argv[++i] : arg.slice(eq + 1);
    if (value === undefined) throw new Error(`missing value for --${key}`);
    out[key] = value;
  }
  return out;
}

/** Check an existing HTML file's meta tags and report lengths/problems. */
function checkFile(file) {
  const html = fs.readFileSync(file, 'utf8');
  const grab = (re) => {
    const m = html.match(re);
    return m ? m[1] : '';
  };
  const title = grab(/<title>([^<]*)<\/title>/i);
  const description = grab(/<meta[^>]*name=["']description["'][^>]*content=["']([^"']*)["']/i)
    || grab(/<meta[^>]*content=["']([^"']*)["'][^>]*name=["']description["']/i);
  const canonical = grab(/<link[^>]*rel=["']canonical["'][^>]*href=["']([^"']*)["']/i);
  const ogImage = grab(/<meta[^>]*property=["']og:image["'][^>]*content=["']([^"']*)["']/i);
  const problems = [];
  if (!title) problems.push('no <title> found');
  else if (title.length > TITLE_MAX) problems.push(`title ${title.length} chars — over ${TITLE_MAX}, will be truncated`);
  if (!description) problems.push('no meta description found');
  else if (description.length > DESCRIPTION_MAX) problems.push(`description ${description.length} chars — over ${DESCRIPTION_MAX}`);
  if (!canonical) problems.push('no canonical link found');
  if (!ogImage) problems.push('no og:image — social shares will show no preview image');
  return { title, description, canonical, ogImage, problems };
}

function printUsage() {
  console.log('Usage: node meta-tags.js --title "T" --description "D" --url "https://…" [options]');
  console.log('       node meta-tags.js --input page.json [--out tags.html]');
  console.log('       node meta-tags.js --check existing.html');
  console.log('Options: --image URL --type website|article --site-name NAME --author NAME --date YYYY-MM-DD');
}

function main() {
  const args = parseArgs(process.argv.slice(2));

  if (args.check) {
    const result = checkFile(args.check);
    console.log(`File: ${args.check}`);
    console.log(`  title:       ${result.title ? `${result.title} (${result.title.length} chars)` : '(missing)'}`);
    console.log(`  description: ${result.description ? `${result.description.length} chars` : '(missing)'}`);
    console.log(`  canonical:   ${result.canonical || '(missing)'}`);
    console.log(`  og:image:    ${result.ogImage || '(missing)'}`);
    if (result.problems.length === 0) {
      console.log('OK — meta tags look good.');
    } else {
      console.log('Problems:');
      result.problems.forEach((p) => console.log(`  - ${p}`));
      process.exitCode = 1;
    }
    return;
  }

  let data = {};
  if (args.input) {
    const raw = fs.readFileSync(args.input, 'utf8');
    data = JSON.parse(raw);
  }
  // CLI flags override JSON file values.
  const flagMap = { title: 'title', description: 'description', url: 'url', image: 'image', type: 'type', author: 'author', date: 'date' };
  for (const [flag, key] of Object.entries(flagMap)) {
    if (args[flag] !== undefined) data[key] = args[flag];
  }
  if (args['site-name'] !== undefined) data.siteName = args['site-name'];

  if (!data.title && !data.description && !data.url) {
    printUsage();
    process.exitCode = 2;
    return;
  }

  const warnings = validate(data);
  warnings.forEach((w) => console.error(`warning: ${w}`));

  const tags = buildTags(data);
  if (args.out) {
    fs.writeFileSync(args.out, tags + '\n', 'utf8');
    console.log(`Wrote ${tags.split('\n').length} lines to ${args.out}`);
  } else {
    console.log(tags);
  }
}

if (require.main === module) {
  try {
    main();
  } catch (err) {
    console.error(`error: ${err.message}`);
    process.exitCode = 1;
  }
}

module.exports = { escapeHtml, truncateSmart, validate, buildTags, parseArgs, checkFile };
