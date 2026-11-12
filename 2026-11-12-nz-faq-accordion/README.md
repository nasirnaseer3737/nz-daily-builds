# NZ FAQ Accordion

A dependency-free, accessible FAQ accordion with live search — drop it into any
static page or WordPress site. No build step, no framework, no jQuery.

## Features

- Click (or Enter / Space) toggles an answer; `aria-expanded` and `hidden` stay in sync
- Live search filters questions as you type (matches question + answer text)
- Single-open or multi-open mode via `data-allow-multiple="true|false"`
- Deep-linking: `#faq-how-much-does-a-website-cost` opens that item on load
- Expand all / Collapse all buttons, plus a "no results" empty state
- Theme-neutral CSS with variables you can override (`--nz-faq-accent`, etc.)

## Files

| File | What it is |
|------|-----------|
| `faq-accordion.js` | Accordion logic (pure helpers exported for tests) |
| `faq-accordion.css` | Theme-neutral styles |
| `index.html` | Demo page with 5 sample questions |
| `test.js` | Node test suite for the pure helpers |

## Usage

```html
<link rel="stylesheet" href="faq-accordion.css">

<div class="nz-faq" data-allow-multiple="false">
  <input class="nz-faq-search" type="search" placeholder="Search questions…">

  <div class="nz-faq-tools">
    <button type="button" data-nz-faq-expand-all>Expand all</button>
    <button type="button" data-nz-faq-collapse-all>Collapse all</button>
  </div>

  <div class="nz-faq-item">
    <h3><button class="nz-faq-question" type="button">Your question?</button></h3>
    <div class="nz-faq-answer" hidden><p>Your answer.</p></div>
  </div>

  <p class="nz-faq-empty" hidden>No questions match your search.</p>
</div>

<script src="faq-accordion.js"></script>
```

Open `index.html` in a browser to see the demo.

## Tests

```sh
node --check faq-accordion.js
node test.js   # 15 assertions, all passing
```
