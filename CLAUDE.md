# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Farside is a Go HTTP service that redirects `farside.link/<service>/<path>` requests to a working,
randomly-chosen instance of a privacy-oriented alternative frontend (Nitter, Libreddit/Redlib,
Invidious, SearXNG, etc.). It distributes traffic across instances and routes around dead ones.

## Commands

```bash
go build                      # compile (binary: ./farside, gitignored)
go test ./...                 # run all tests
go test -v ./db               # single package
go test -v -run TestBaseRouting ./server   # single test
FARSIDE_TEST=1 ./farside      # run with all instances added to the pool (skips health checks)
./cross_compile.sh            # build release tarballs for all platforms into ./out/
```

Tests open a real BadgerDB on disk (`./badger-db` unless `FARSIDE_DB_DIR` is set), so run them
in a writable directory. CI (`.github/workflows/tests.yml`) runs `go test ./...` on Go 1.21–1.23
across Linux/macOS/Windows.

## Architecture

Three internal packages, wired together in `main.go` (which starts the DB, services, cron, and server):

- **`db/`** — BadgerDB key/value store mapping `service.Type` → JSON array of live instance URLs.
  - `db.go`: `GetInstance` implements the **"reserving" rule** — it returns a random instance but
    excludes the one returned on the *previous* request for that service (tracked in the in-memory
    `selectionMap`), so consecutive requests hit different instances. Falls back to
    `services.FallbackMap` when no live instances exist. `GetServiceList` caches the full list for 5 min.
  - `cron.go`: periodic health-checking. See the primary/replica split below.
- **`services/`** — service definitions and URL matching.
  - `services.go`: loads `services.json` / `services-full.json` into `ServiceList` and builds
    `FallbackMap`. Files are read from disk, or fetched from the GitHub raw repo if absent.
  - `mappings.go`: `regexMap` maps a requested "parent" service or URL (e.g. `reddit.com`,
    `youtube.com`) to candidate frontend types. `MatchRequest` returns the frontend to use — a bare
    service name (no `.`) passes through unchanged; a real domain picks a random matching target.
- **`server/`** — `net/http` server (Go 1.22+ `ServeMux` pattern routing). Routes:
  - `/{$}` home page, `/state/{$}` JSON dump of all services+instances, `/{routing...}` the redirect
    endpoint (302), `/_/{routing...}` same redirect but renders `route.html` to keep a history entry
    for back-navigation between instances. `index.html` and `route.html` are `//go:embed`-ed.

## Primary/replica model (important)

Only the **primary** node actually probes instances. `cron.go` branches on `FARSIDE_PRIMARY`:

- `FARSIDE_PRIMARY=1`: queries every instance in `ServiceList` (5–10s timeout, expects HTTP 200) and
  writes the live set to the DB. `searx`/`searxng` are in `skipInstanceChecks` and added unconditionally.
- otherwise (default): fetches already-vetted state from `https://farside.link/state` (or
  `cf.farside.link/state` when `FARSIDE_CF_ENABLED=1`) instead of probing itself.

So a self-hosted instance is a replica of the official one unless you set `FARSIDE_PRIMARY=1`.

## Service lists & the CI updater

- `services.json` — instances **not** behind Cloudflare (default).
- `services-full.json` — all instances; used when `FARSIDE_CF_ENABLED=1` (→ picks `services-full.json`
  via `GetServicesFileName`).
- `.github/workflows/update-instances.yml` runs daily: it pulls fresh instance lists from each
  upstream project's own instance API/list with `jq`/`yq`, writes `services-full.json`, then runs
  `tools/un-cloudflare.sh` (which `dig`s each domain and drops Cloudflare-proxied ones) to produce
  `services.json`, and commits both as `[CI] Auto update instances` (the bulk of git history).

When **adding a new service**, you generally touch three things: an entry in both JSON files
(`type`, `test_url`, `fallback`, `instances`), a `RegexMapping` in `services/mappings.go`, and an
update block in `update-instances.yml` so the instance list stays fresh.

## Environment variables

`FARSIDE_PORT` (default 4001) · `FARSIDE_DB_DIR` (default `./badger-db`) · `FARSIDE_PRIMARY` ·
`FARSIDE_CF_ENABLED` · `FARSIDE_CRON` (set `0` to disable the periodic checks) · `FARSIDE_TEST`.
