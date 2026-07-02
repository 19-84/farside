#!/usr/bin/env python3
"""Verify-first instance discovery for services without a clean registry.

Several frontends only publish their instances in a README/wiki/HTML page,
which cannot be scraped naively -- CI badges, dependency links and bare domains
return HTTP 200 and masquerade as instances. This tool treats those pages as a
source of *candidates* and then confirms each candidate independently:

  live     : GET <base><test_url> returns 200 and is not an anti-bot wall
  identity : the instance HOME page contains a content marker for that frontend
             (so vercel.com / heroicons.com / badge links are rejected)

Only candidates passing BOTH are emitted. Run it, eyeball the result, then merge
into services.json. It does not write any files itself.

    python3 tools/discover.py            # all configured services
    python3 tools/discover.py lingva     # one service
"""
import concurrent.futures as cf
import json
import re
import ssl
import sys
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (compatible; Farside-discover/1.0; +https://farside.link)"}
CTX = ssl.create_default_context()

# kept in sync with tools/probe and db.blockPageMarkers
BLOCK = ["error code: 1003", "just a moment...", "attention required!",
         "cf-browser-verification", "enable javascript and cookies",
         "checking your browser", "ddos-guard", "making sure you",
         "tollbat", "<title>gandalf</title>"]

# service -> {sources, test_url, markers}. markers are matched (lowercased,
# HTML-entity-safe) against the instance home page to confirm identity.
SERVICES = {
    "lingva": {
        "sources": ["https://raw.githubusercontent.com/thedaviddelta/lingva-translate/main/README.md"],
        "test_url": "/auto/en/hola", "markers": ["lingva"]},
    "quetre": {
        "sources": ["https://raw.githubusercontent.com/zyachel/quetre/main/README.md"],
        "test_url": "/How-does-the-Z-boson-decay", "markers": ["quetre"]},
    "libremdb": {
        "sources": ["https://raw.githubusercontent.com/zyachel/libremdb/main/README.md"],
        "test_url": "/title/tt0133093", "markers": ["libremdb"]},
    "dumb": {
        "sources": ["https://raw.githubusercontent.com/rramiachraf/dumb/main/README.md"],
        "test_url": "/Naughty-boy-la-la-la-lyrics", "markers": ["dumb", "genius"]},
    "anonymousoverflow": {
        "sources": ["https://raw.githubusercontent.com/httpjamesm/AnonymousOverflow/main/README.md"],
        "test_url": "/questions/6591213/how-do-i-rename-a-local-git-branch",
        "markers": ["anonymousoverflow", "anonymous overflow"]},
    "4get": {
        "sources": ["https://4get.ca/instances"],
        "test_url": "/ami4get", "markers": ["4get"]},
    "biblioreads": {
        "sources": ["https://raw.githubusercontent.com/nesaku/BiblioReads/main/README.md"],
        "test_url": "/search?q=dune", "markers": ["biblioreads"]},
}

BAD = ("github.com", "githubusercontent", "shields.io", "gitlab.com", "codeberg.org",
       "sr.ht", "matrix.to", "t.me", "reddit.com", "wikipedia", "vercel.com",
       "travis-ci", "cypress.io", "netcup", "heroicons", "materialdesignicons",
       "fonts.g", "cloudflare.com", "mozilla.org", "w3.org", "schema.org")


def fetch(url, limit=262144):
    r = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=12, context=CTX)
    return r.status, r.read(limit).decode("utf-8", "replace")


def candidates(source):
    _, body = fetch(source)
    urls = set(re.findall(r"https://[a-z0-9][a-z0-9.-]+\.[a-z]{2,}", body.lower()))
    return sorted(u.rstrip("/") for u in urls if not any(b in u for b in BAD))


def verify(base, test_url, markers):
    try:  # liveness via test_url
        code, body = fetch(base + test_url)
        if code != 200:
            return None
        low = body.lower()
        if any(m in low for m in BLOCK):
            return None
    except Exception:
        return None
    try:  # identity via home page
        _, home = fetch(base)
        hlow = home.lower()
        if any(m in hlow for m in markers) or any(m in body.lower() for m in markers):
            return base
    except Exception:
        pass
    return None


def discover(svc):
    cfg = SERVICES[svc]
    cands = set()
    for s in cfg["sources"]:
        try:
            cands.update(candidates(s))
        except Exception as e:
            print(f"  [{svc}] source failed: {s} ({type(e).__name__})", file=sys.stderr)
    cands = sorted(cands)
    good = []
    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        for r in ex.map(lambda b: verify(b, cfg["test_url"], cfg["markers"]), cands):
            if r:
                good.append(r)
    print(f"{svc}: {len(good)} verified / {len(cands)} candidates")
    for g in sorted(good):
        print(f"    {g}")
    return svc, sorted(good)


def main():
    which = sys.argv[1:] or list(SERVICES)
    result = {}
    for svc in which:
        if svc not in SERVICES:
            print(f"unknown service: {svc}", file=sys.stderr); continue
        s, good = discover(svc)
        result[s] = good
    print("\nJSON:")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
