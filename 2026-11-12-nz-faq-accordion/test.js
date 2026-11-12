// Tests for faq-accordion.js pure helpers — run with: node test.js
// No dependencies, no DOM needed: only the exported pure functions are tested.
'use strict';

var faq = require('./faq-accordion.js');

var passed = 0;
var failed = 0;

function check(name, actual, expected) {
  var ok = JSON.stringify(actual) === JSON.stringify(expected);
  if (ok) {
    passed++;
    console.log('ok   - ' + name);
  } else {
    failed++;
    console.log('FAIL - ' + name + ' (got ' + JSON.stringify(actual) +
      ', expected ' + JSON.stringify(expected) + ')');
  }
}

/* slugify */
check('slugify: basic question', faq.slugify('How much does a website cost?'), 'how-much-does-a-website-cost');
check('slugify: trims punctuation', faq.slugify('  Will it rank?!  '), 'will-it-rank');
check('slugify: empty input', faq.slugify(''), 'faq');
check('slugify: collapses separators', faq.slugify('A  --  B'), 'a-b');

/* filterItems */
var items = [
  { question: 'How much does a website cost?', answer: 'A fixed quote before work starts.' },
  { question: 'How long does it take?', answer: 'Most sites launch in 1-2 weeks.' },
  { question: 'Will my site rank on Google?', answer: 'On-page SEO is included: headings, meta tags, sitemaps.' }
];

check('filter: empty query returns all', faq.filterItems(items, '').length, 3);
check('filter: matches question word', faq.filterItems(items, 'cost').length, 1);
check('filter: matches answer word', faq.filterItems(items, 'sitemaps').length, 1);
check('filter: case-insensitive', faq.filterItems(items, 'GOOGLE').length, 1);
check('filter: every word must match', faq.filterItems(items, 'website quote').length, 1);
check('filter: no match returns empty', faq.filterItems(items, 'refund policy').length, 0);
check('filter: whitespace-only query returns all', faq.filterItems(items, '   ').length, 3);

/* nextOpenState */
check('toggle: opens closed item', faq.nextOpenState([false, false], 0, false), [true, false]);
check('toggle: closes open item', faq.nextOpenState([true, false], 0, false), [false, false]);
check('toggle: single-open closes others', faq.nextOpenState([true, false], 1, false), [false, true]);
check('toggle: multi-open keeps others', faq.nextOpenState([true, false], 1, true), [true, true]);

console.log('\n' + passed + ' passed, ' + failed + ' failed');
process.exit(failed === 0 ? 0 : 1);
