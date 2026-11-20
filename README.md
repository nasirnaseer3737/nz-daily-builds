# NZ Daily Builds

One small, real, working build every day — a WordPress plugin, a Python
utility, a JS tool, an HTML/CSS component or a small CLI — pushed here as one
commit per day to keep the contribution graph green.

Owner: [nasirnaseer3737](https://github.com/nasirnaseer3737)

## Builds

| Date | Build | What it does |
|------|-------|--------------|
| 2026-11-09 | [nz-url-checker](2026-11-09-nz-url-checker/) | Python stdlib CLI that checks a list of URLs and reports status, redirects and response time, with CSV output |
| 2026-11-10 | [nz-meta-tags](2026-11-10-nz-meta-tags/) | Node.js stdlib CLI that generates SEO meta tags (Open Graph, Twitter Card, JSON-LD) and checks existing pages |
| 2026-11-11 | [nz-simple-redirects](2026-11-11-nz-simple-redirects/) | WordPress plugin: lightweight 301/302 redirect manager with exact and /* wildcard rules, admin screen under Settings |
| 2026-11-12 | [nz-faq-accordion](2026-11-12-nz-faq-accordion/) | Dependency-free accessible FAQ accordion with live search, single/multi-open modes and hash deep-linking (HTML/CSS/JS + demo) |
| 2026-11-13 | [nz-sitemap-generator](2026-11-13-nz-sitemap-generator/) | Python stdlib CLI that builds XML sitemaps from a URL list or a folder of HTML files, with lastmod, priority/changefreq heuristics and automatic splitting + sitemap index |
| 2026-11-14 | [nz-ai-lead-scorer](2026-11-14-nz-ai-lead-scorer/) | AI-powered lead scorer: Python stdlib CLI that scores CSV leads 0–100 (email, phone, website, size, industry, source, budget, TCPA consent) with a Gemini AI outreach angle per lead and a labelled mock fallback |
| 2026-11-15 | [nz-ai-outreach-drafter](2026-11-15-nz-ai-outreach-drafter/) | AI outreach email drafter: Python stdlib CLI that turns a prospects CSV into personalised emails (3 subject lines + body via Gemini API, labelled mock fallback) with a TCPA consent gate, sent-history dedupe and a 10-minute paced send queue |
| 2026-11-16 | [nz-ai-social-scheduler](2026-11-16-nz-ai-social-scheduler/) | AI social post scheduler: Python stdlib CLI that drafts LinkedIn/X/Facebook posts from a topics CSV via Gemini API (labelled mock fallback), enforces platform limits and hashtag caps, and schedules them into timed slots with dedupe history |
| 2026-11-17 | [nz-ai-keyword-clusterer](2026-11-17-nz-ai-keyword-clusterer/) | AI keyword clusterer: Python stdlib CLI that groups SEO keywords into pillar-page topic clusters via Gemini API (labelled offline mock fallback), with pillar keyword, slug, content brief and JSON/CSV/Markdown outputs |
| 2026-11-18 | [nz-ai-alt-writer](2026-11-18-nz-ai-alt-writer/) | AI image alt-text writer: Python stdlib CLI that writes descriptive, SEO-friendly alt text for website images via Gemini API (labelled mock fallback from filenames), with 125-char limit, decorative-image handling, dedupe history and an existing-alts audit mode |
| 2026-11-19 | [nz-ai-auto-reply-bot](2026-11-19-nz-ai-auto-reply-bot/) | AI auto-reply bot for a lead inbox: Python stdlib CLI that classifies WhatsApp/email messages and drafts replies via Gemini API (labelled mock fallback), with complaint escalation, WhatsApp 24h-window flagging, quiet-hours scheduling and a 10-minute paced send queue |
| 2026-11-20 | [nz-ai-seo-auditor](2026-11-20-nz-ai-seo-auditor/) | AI on-page SEO auditor: Python stdlib CLI that audits HTML pages/URLs (title, meta, headings, alt text, canonical, OG/Twitter, schema, content, links, readability, keyword) into a 0–100 score + grade, with Gemini fix suggestions and a labelled offline mock fallback |

Each build folder has its own README, source code and tests.
