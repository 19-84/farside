#!/usr/bin/env python3
"""Validate the upstream instance registries that feed update-instances.yml.

For each discovery source it fetches the URL and runs the same extraction the
CI uses, reporting how many instances the registry currently yields. A registry
that is unreachable, blocks automated fetches, or whose schema changed shows up
as DEAD/BROKEN so discovery rot is visible instead of silently shipping stale
instance lists.

Exit status is non-zero if any registry is dead, broken, or empty.

    python3 tools/check-registries.py

Note: a registry being "OK" only means it returns parseable data; the instances
it lists may still be dead or behind anti-bot walls. Use tools/probe to check
that the instances themselves are alive.
"""
import json
import ssl
import sys
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (compatible; Farside-registry-check/1.0)"}
CTX = ssl.create_default_context()


def _hosts(body):
    # status.d420.de changed "hosts" from a dict to a list; handle both.
    h = json.loads(body).get("hosts", {})
    return h.values() if isinstance(h, dict) else h


# (service, registry url, extractor -> instance count). Mirrors update-instances.yml.
REGISTRIES = [
    ("searxng", "https://searx.space/data/instances.json",
     lambda b: len(json.loads(b).get("instances", {}))),
    ("nitter", "https://status.d420.de/api/v1/instances",
     lambda b: sum(1 for v in _hosts(b) if v.get("healthy"))),
    ("simplytranslate", "https://codeberg.org/SimpleWeb/Website/raw/branch/master/config.json",
     lambda b: len(next(p for p in json.loads(b)["projects"] if p["id"] == "simplytranslate")["instances"])),
    ("whoogle", "https://raw.githubusercontent.com/benbusby/whoogle-search/main/misc/instances.txt",
     lambda b: sum(1 for l in b.splitlines() if l.strip().startswith("http"))),
    ("invidious", "https://api.invidious.io/instances.json",
     lambda b: sum(1 for e in json.loads(b) if e[1].get("type") == "https")),
    ("scribe", "https://git.sr.ht/~edwardloveall/scribe/blob/main/docs/instances.json",
     lambda b: len(json.loads(b))),
    ("libreddit/redlib", "https://raw.githubusercontent.com/redlib-org/redlib-instances/main/instances.json",
     lambda b: len([i for i in json.loads(b)["instances"] if i.get("url")])),
    ("breezewiki", "https://docs.breezewiki.com/files/instances.json",
     lambda b: len(json.loads(b))),
    ("gothub", "https://codeberg.org/gothub/gothub-instances/raw/branch/master/instances.json",
     lambda b: len(json.loads(b))),
    ("librey", "https://raw.githubusercontent.com/Ahwxorg/LibreY/main/instances.json",
     lambda b: len(json.loads(b)["instances"])),
    ("rimgo", "https://rimgo.codeberg.page/api.json",
     lambda b: len(json.loads(b).get("clearnet", []))),
    ("tent", "https://forgejo.sny.sh/sun/Tent/raw/branch/main/instances.json",
     lambda b: sum(1 for e in json.loads(b) if e.get("type") == "http")),
]


def main():
    print(f"{'service':18} {'status':10} {'#inst':>6}  note")
    print("-" * 78)
    bad = 0
    for svc, url, extract in REGISTRIES:
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=20, context=CTX) as r:
                body = r.read().decode("utf-8", "replace")
            try:
                n = extract(body)
            except Exception as e:
                print(f"{svc:18} {'BROKEN':10} {'-':>6}  parse failed ({type(e).__name__}); schema changed?")
                bad += 1
                continue
            status = "OK" if n > 0 else "EMPTY"
            if n <= 0:
                bad += 1
            print(f"{svc:18} {str(r.status)+' '+status:10} {n:>6}")
        except Exception as e:
            print(f"{svc:18} {'DEAD':10} {'-':>6}  {type(e).__name__}: {str(e)[:40]}")
            bad += 1
    print("-" * 78)
    print(f"{len(REGISTRIES) - bad}/{len(REGISTRIES)} registries healthy")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
