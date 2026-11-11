# NZ Simple Redirects

A lightweight 301/302 redirect manager for WordPress — part of the
[NZ Daily Builds](https://github.com/nasirnaseer3737/nz-daily-builds) series
(daily build, 2026-11-11).

## What it does

Lets you redirect old URLs to new ones from **Settings → NZ Redirects** in
wp-admin — no `.htaccess` editing, no heavy redirect plugin.

- **Exact redirects** — `/old-page` → `/new-page` (301 permanent or 302 temporary).
- **Wildcard redirects** — `/blog/*` → `/news/*` sends `/blog/hello` to
  `/news/hello`. A `*` in the target is replaced with the matched remainder;
  without a `*`, the whole section points at one target.
- **Forgiving matching** — trailing slashes and upper/lower case don't matter
  (`/Old-Page/` matches a rule for `/old-page`).
- **Safe targets only** — site-relative paths (`/new-page`) or absolute
  `http(s)` URLs. `javascript:` and other schemes are rejected.
- **Duplicate-safe** — adding a rule for a "from" path that already exists
  updates it instead of creating a duplicate.
- **Zero bloat** — one option row in the database, one `template_redirect`
  hook, no admin notices, no tracking.

## Install

1. Copy the `nz-simple-redirects` folder into `wp-content/plugins/`.
2. Activate **NZ Simple Redirects** in WordPress → Plugins.
3. Go to **Settings → NZ Redirects** and add your redirects.

## Files

| File | What it is |
|------|-----------|
| `nz-simple-redirects.php` | The whole plugin (admin screen + redirect engine) |
| `test-nz-simple-redirects.php` | Offline tests — WordPress stubs, no WP install needed |

## Tests

```bash
php -l nz-simple-redirects.php
php test-nz-simple-redirects.php   # 34 checks, WordPress not required
```

## How it works

Redirects are stored as an array in the `nzsr_redirects` option. On every
front-end request the `template_redirect` hook normalises the request path and
checks the rules: exact matches first, then wildcard rules (longest prefix
wins). On a match it calls `wp_redirect()` with the rule's status code and
exits. The matching/sanitising functions are pure PHP with no WordPress calls,
so they are unit-tested directly.
