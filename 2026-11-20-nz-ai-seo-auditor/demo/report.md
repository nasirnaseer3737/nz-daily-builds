# NZ AI SEO Audit Report

Pages audited: **2**  |  AI suggestions: **MOCK (offline fallback)**

## sample_pages/bad-page.html — 32/100 (Grade F)

- Words: 11  |  Readability (Flesch): 85.9
- Images: 2 (2 missing alt)  |  Links: 2 internal, 0 external

| Check | Status | Detail |
|---|---|---|
| Title tag | WARN | Title is 4 chars (too short, aim 30-60). |
| Meta description | FAIL | No meta description. |
| H1 heading | WARN | 2 H1 tags found (aim for exactly one). |
| Heading order | WARN | Heading levels are skipped (e.g. H1 straight to H3). |
| Image alt text | FAIL | 2 of 2 images have no alt text. |
| Canonical URL | WARN | No canonical link tag. |
| Social tags (OG/Twitter) | WARN | Missing social tags: og:title, og:description, og:image, twitter:card, twitter:title. |
| Schema.org markup | WARN | No JSON-LD structured data found. |
| Content length | WARN | Only 11 words of body text (aim 300+). |
| Links | WARN | 2 placeholder/broken-looking links (2 internal, 0 external). |
| Readability | PASS | Flesch reading ease 85.9. |
| Target keyword | FAIL | "WordPress developer" appears 0x in body (density 0.0%), in title: no, in H1: no. |

### Fix suggestions (MOCK (offline fallback — no AI API key set))

- Add a 120-160 char meta description with a call to action.
- Write descriptive alt text (under 125 chars) for every image.
- Use "WordPress developer" in the title, H1 and naturally in the body.
- Expand the title to 30-60 chars, lead with the keyword.
- Keep one H1; demote the others to H2.
- Use headings in order: H1, then H2, then H3.
- Add <link rel="canonical" href="..."> with the preferred URL.
- Add Open Graph + Twitter Card tags so shares look right.
- Add JSON-LD schema (e.g. LocalBusiness, Article or WebPage).
- Add useful content — aim for at least 300 words on the topic.
- Fix or remove placeholder links (#, javascript:).

## sample_pages/good-page.html — 92/100 (Grade A)

- Words: 234  |  Readability (Flesch): 60.9
- Images: 2 (0 missing alt)  |  Links: 2 internal, 1 external

| Check | Status | Detail |
|---|---|---|
| Title tag | PASS | Title is 59 chars. |
| Meta description | PASS | Meta description is 154 chars. |
| H1 heading | PASS | One H1: "WordPress Developer in Rawalpindi" |
| Heading order | PASS | 5 headings in order. |
| Image alt text | PASS | All 2 images have alt text. |
| Canonical URL | PASS | Canonical set: https://nzgenix.digital/wordpress-developer/ |
| Social tags (OG/Twitter) | PASS | Open Graph and Twitter Card tags present. |
| Schema.org markup | PASS | JSON-LD structured data found. |
| Content length | WARN | Only 234 words of body text (aim 300+). |
| Links | PASS | 2 internal, 1 external links. |
| Readability | PASS | Flesch reading ease 60.9. |
| Target keyword | PASS | "WordPress developer" appears 5x in body (density 2.14%), in title: yes, in H1: yes. |

### Fix suggestions (MOCK (offline fallback — no AI API key set))

- Add useful content — aim for at least 300 words on the topic.
- Page is in good shape — re-check after the next content update.
