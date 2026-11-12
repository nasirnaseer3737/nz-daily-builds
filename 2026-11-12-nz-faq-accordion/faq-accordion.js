/**
 * NZ FAQ Accordion — dependency-free, accessible FAQ accordion with live search.
 *
 * Features:
 *  - Click / Enter / Space toggles an answer (ARIA expanded + hidden kept in sync)
 *  - Live search filters questions as you type (matches question + answer text)
 *  - Single-open or multi-open mode via data-allow-multiple
 *  - Deep-linking: #faq-<slug> opens that item on load
 *  - "Expand all / Collapse all" buttons, "no results" empty state
 *  - Zero dependencies, no build step, works in any static page or WordPress
 *
 * Usage:
 *   <div class="nz-faq" data-allow-multiple="false">
 *     <input class="nz-faq-search" type="search" placeholder="Search questions…">
 *     <div class="nz-faq-item">
 *       <h3><button class="nz-faq-question" aria-expanded="false">Your question?</button></h3>
 *       <div class="nz-faq-answer" hidden><p>Your answer.</p></div>
 *     </div>
 *     …
 *   </div>
 *   <link rel="stylesheet" href="faq-accordion.css">
 *   <script src="faq-accordion.js"></script>
 */
(function () {
  'use strict';

  /* ------------------------------------------------------------------ */
  /* Pure helpers — also exported for the Node test suite.               */
  /* ------------------------------------------------------------------ */

  /** Turn heading text into a URL-safe slug, e.g. "How much?" -> "how-much". */
  function slugify(text) {
    return String(text || '')
      .toLowerCase()
      .trim()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '')
      .slice(0, 60) || 'faq';
  }

  /**
   * Filter FAQ items by a search query.
   * items: [{ question: string, answer: string }]
   * Returns the items whose question OR answer contains every query word
   * (case-insensitive). An empty query returns every item.
   */
  function filterItems(items, query) {
    var words = String(query || '')
      .toLowerCase()
      .split(/\s+/)
      .filter(function (w) { return w.length > 0; });
    if (words.length === 0) return items.slice();
    return items.filter(function (item) {
      var haystack = (item.question + ' ' + item.answer).toLowerCase();
      return words.every(function (word) { return haystack.indexOf(word) !== -1; });
    });
  }

  /**
   * Decide which items stay open after a toggle.
   * Returns an array of booleans (same length as `open`).
   * allowMultiple=false closes every other item when one opens.
   */
  function nextOpenState(open, index, allowMultiple) {
    var next = open.slice();
    var willOpen = !open[index];
    if (willOpen && !allowMultiple) {
      for (var i = 0; i < next.length; i++) next[i] = false;
    }
    next[index] = willOpen;
    return next;
  }

  /* ------------------------------------------------------------------ */
  /* Browser wiring.                                                     */
  /* ------------------------------------------------------------------ */

  function initAccordion(root) {
    var allowMultiple = root.getAttribute('data-allow-multiple') === 'true';
    var items = Array.prototype.slice.call(root.querySelectorAll('.nz-faq-item'));
    var buttons = items.map(function (item) {
      return item.querySelector('.nz-faq-question');
    });
    var answers = items.map(function (item) {
      return item.querySelector('.nz-faq-answer');
    });

    // Give every button/answer a stable id so aria-controls works.
    items.forEach(function (item, i) {
      var slug = slugify(buttons[i].textContent);
      var qId = 'nz-faq-q-' + slug + '-' + i;
      var aId = 'nz-faq-a-' + slug + '-' + i;
      buttons[i].id = qId;
      buttons[i].setAttribute('aria-controls', aId);
      buttons[i].setAttribute('aria-expanded', 'false');
      answers[i].id = aId;
      answers[i].setAttribute('aria-labelledby', qId);
      item.dataset.slug = slug;
    });

    function render(open) {
      items.forEach(function (item, i) {
        buttons[i].setAttribute('aria-expanded', String(open[i]));
        answers[i].hidden = !open[i];
        item.classList.toggle('is-open', open[i]);
      });
    }

    var open = items.map(function () { return false; });

    buttons.forEach(function (btn, i) {
      btn.addEventListener('click', function () {
        open = nextOpenState(open, i, allowMultiple);
        render(open);
      });
    });

    // Expand all / collapse all.
    var expandAll = root.querySelector('[data-nz-faq-expand-all]');
    var collapseAll = root.querySelector('[data-nz-faq-collapse-all]');
    if (expandAll) {
      expandAll.addEventListener('click', function () {
        open = items.map(function () { return true; });
        render(open);
      });
    }
    if (collapseAll) {
      collapseAll.addEventListener('click', function () {
        open = items.map(function () { return false; });
        render(open);
      });
    }

    // Live search: hide non-matching items, show a "no results" note.
    var search = root.querySelector('.nz-faq-search');
    var emptyNote = root.querySelector('.nz-faq-empty');
    if (search) {
      search.addEventListener('input', function () {
        var data = items.map(function (item, i) {
          return {
            question: buttons[i].textContent,
            answer: answers[i].textContent
          };
        });
        var kept = filterItems(data, search.value);
        var keptSet = {};
        kept.forEach(function (item) { keptSet[item.question] = true; });
        var visible = 0;
        items.forEach(function (item, i) {
          var show = keptSet[buttons[i].textContent] === true;
          item.style.display = show ? '' : 'none';
          if (show) visible++;
        });
        if (emptyNote) emptyNote.hidden = visible !== 0;
      });
    }

    // Deep-link: #faq-<slug> opens that item on page load.
    if (window.location.hash.indexOf('#faq-') === 0) {
      var wanted = window.location.hash.slice(5);
      items.forEach(function (item, i) {
        if (item.dataset.slug === wanted) {
          open = nextOpenState(open, i, allowMultiple);
        }
      });
    }

    render(open);
  }

  // Export pure helpers for the Node test suite; wire up in the browser.
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = { slugify: slugify, filterItems: filterItems, nextOpenState: nextOpenState };
  } else if (typeof document !== 'undefined') {
    document.addEventListener('DOMContentLoaded', function () {
      Array.prototype.forEach.call(
        document.querySelectorAll('.nz-faq'),
        initAccordion
      );
    });
  }
})();
