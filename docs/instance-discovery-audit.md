# Instance Discovery Audit

_Date: 2026-06-17_

Audit of every service Farside redirects to, across three axes:

1. **Repo** — is the upstream frontend project still maintained? (forge API:
   last push / archived flag)
2. **Registry** — does a machine-readable instance registry exist, and is it
   reachable/parseable? (`tools/check-registries.py`)
3. **Parsing** — does the CI's extraction in `update-instances.yml` match the
   registry's current format?
4. **Live** — instances actually healthy right now (`tools/probe`, status +
   anti-bot wall + per-type content marker against `services.json`).

Registries can be flaky — a single failed fetch is not definitive (piped's
registry returned `null` on one pull and valid JSON on the next). Re-run before
acting.

## Summary table

The **Walls** column is from a 2026-07-01 re-probe of `services-full.json`
(`tools/probe -json`) and counts instances serving an anti-bot challenge
page with HTTP 200 (Anubis proof-of-work, Cloudflare challenge, Tollbat,
Gandalf, DDoS-Guard). Walled ≠ dead: a real browser may pass the wall, but
the probe (and Farside's cron) cannot, so these count as unhealthy.

| Service | Repo (last push) | Registry | Parsing | Live | Walls | Verdict |
|---|---|---|---|---|---|---|
| redlib | active 2026-04 | redlib-instances JSON | OK | 1/5 | 2 anubis | **healthy** |
| libreddit | stale 2025-02 | shares redlib registry | OK | 1/5 | 2 anubis | superseded by redlib |
| nitter | active 2026-06 | status.d420.de (now a list) | OK¹ | 2/6 | 3 anubis, 1 cloudflare | **healthy** |
| rimgo | active 2026-06 | rimgo.codeberg.page JSON | OK | 6/21 | 5 anubis, 1 cloudflare, 1 gandalf | **healthy** |
| breezewiki | active 2026-06 | docs.breezewiki.com JSON | OK | 5/16 | 5 anubis | **healthy** |
| gothub | active 2026-06 | codeberg JSON | OK | 5/6 | — | **healthy** |
| librey | active 2026-06 | LibreY JSON | OK | 3/14 | 1 anubis | **healthy** |
| tent | active 2026-04 | forgejo.sny.sh JSON | OK | 5/11 | 1 anubis, 1 cloudflare | **healthy** |
| whoogle | active 2026-05 | instances.txt | OK | 0/5 | — | registry ok, instances down |
| simplytranslate | **archived** 2024-12 | codeberg config.json | OK | 5/16 | — | works despite archive |
| searxng | active 2026-06 | searx.space JSON (83) | OK | 0/33 | 2 anubis (rest dead/suspect) | instances behind Anubis walls |
| searx | active 2026-05 (legacy) | searx-instances yml (9) | OK | 0/9 | — | legacy; superseded by searxng |
| invidious | active 2026-06 | api.invidious.io JSON (8) | OK | 0/6 | 3 anubis, 1 gandalf | instances walled/dead |
| piped | active 2026-06 | kavin.rocks (1 entry, **api_url only**) | unusable² | 0/14 | — | no frontend registry |
| scribe | sr.ht (no API) | git.sr.ht | **BROKEN³** | 2/5 | — | registry unfetchable |
| quetre | active 2025-11 | README only | none | 1/16 | 1 tollbat | live, no auto-discovery |
| libremdb | active 2026-04 | README only | none | 0/13 | 1 anubis | live ones exist, no auto-discovery |
| dumb | active 2026-04 | README only | none | 1/7 | — | live, no auto-discovery |
| anonymousoverflow | active 2025-12 | README only | none | 3/12 | 1 anubis | live, no auto-discovery |
| 4get | active 2026-06 | HTML page only (no JSON) | none | 5/18 | 1 anubis | live, no auto-discovery |
| lingva | **dormant 2023** | README only | none | 1/8 | — | abandoned; a few live |
| proxitok | stale 2025-05 | wiki only | none | 0/12 | — | dying |
| teddit | stale 2025-04 | registry commented out | n/a | 2/21 | — | unmaintained |
| proxigram | stale 2024-12 | none found | none | 0/6 | — | **defunct — removed** |
| librarian | **archived** 2024-12 | none | none | 0/6 | — | **defunct — removed** |
| wikiless | **repo gone (404)** | commented out | n/a | 0/10 | — | **defunct — removed** |

¹ status.d420.de changed `hosts` dict→list; CI `jq | to_entries` tolerates it.
² registry lists `api_url` (Piped API), not the frontend URL Farside redirects to.
³ git.sr.ht returns HTTP 418 to automated fetches (any UA); no mirror found.

This table is a snapshot. A continuously-updated version (per-instance
status with wall classification) is published to GitHub Pages by
`.github/workflows/status-page.yml`.

## Findings

- **Discovery works for ~10 services** (redlib, nitter, rimgo, breezewiki,
  gothub, librey, tent, whoogle, simplytranslate, + searxng/searx/invidious
  whose registries parse but whose instances are now walled/dead).
- **3 services are fully defunct** — repo archived/deleted, no registry, zero
  live instances: `proxigram`, `librarian`, `wikiless`. Drop candidates.
- **searx** is the legacy project superseded by searxng (0 live). **libreddit**
  is superseded by redlib (shares its registry). Consolidation candidates.
- **piped / scribe** have active-ish upstreams but no usable registry (piped's
  collapsed to one API-only entry; scribe's host blocks automated fetches).
- **6 services are alive but un-discoverable** (quetre, libremdb, dumb,
  anonymousoverflow, 4get, lingva) — they only publish instances in
  README/wiki markdown, which scrapes too noisily to automate (CI badges and
  dependency links return 200 and masquerade as instances). Refresh by hand.
- **Ecosystem-wide**: many registries parse fine but their instances have
  adopted Anubis / Cloudflare / Tollbat walls (searxng, invidious especially),
  so "registry healthy" no longer implies "instances reachable."

## Recommended actions

1. Drop the 3 defunct services (`proxigram`, `librarian`, `wikiless`) from
   `services.json`, `services-full.json`, `services/mappings.go`, and the
   commented CI blocks.
2. Consider dropping `searx` (use `searxng`) and folding `libreddit` into
   `redlib`.
3. For the 6 un-discoverable-but-alive services, periodically refresh
   instance lists by hand (no reliable registry exists).
4. Run `tools/check-registries.py` (registries) and `tools/probe` (instances)
   in CI so this audit stays current.
