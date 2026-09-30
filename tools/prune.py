#!/usr/bin/env python3
"""Non-flaky pruning of dead instances from a services JSON file.

Pruning naively on a single failed probe is destructive: one transient outage
(or a CI network blip) would drop a perfectly good instance. This tool avoids
that with two layers of hysteresis:

  in-run  : each instance is probed with a few retries; any success = live.
  cross-run: a per-instance strike counter is persisted (instance-strikes.json).
            A live probe resets it to 0; a dead probe increments it. An instance
            is only removed once it has been dead for >= THRESHOLD consecutive
            runs (default 3, i.e. ~3 days for a daily job).

Strikes outlive the prune. Most lists are rebuilt from upstream registries
every night, and those registries keep listing dead instances. When the state
was dropped on removal, a pruned instance came back the next night at 0
strikes, so the committed lists were clean only one day in three (and the
LibRedirect-sourced ones, refreshed after this step, were never clean). Now a
pruned instance keeps its count for as long as a registry still lists it. If
it is still dead when it reappears, it is pruned again straight away. A single
live probe resets it as usual.

"Dead" = a hard failure only: DNS/connection errors, timeouts, 404/410,
persistent 5xx, or a 200 whose body is empty or a parked/shut-down notice
(the frontend itself is gone even though the host answers). Bot-defense responses (429/403/418, anti-bot wall pages) do
NOT count -- they mean the instance blocks CI's datacenter IP, not real users
(searxng instances rate-limit every automated query, mirroring the server's
skipInstanceChecks). The runtime health check still gates what gets served.
Identity/content markers are NOT used here -- they are unreliable for some
frontends and would prune real instances.

Fallback URLs get the same probe + strike treatment but are never pruned:
once one has been dead >= THRESHOLD runs, a ::warning:: annotation is
emitted so it shows up on the Actions run (a fallback is what users get
when a service's whole instance list is empty, so rot there is invisible
until someone follows a redirect to a dead site).

    python3 tools/prune.py --file services-full.json --state instance-strikes.json

Writes the pruned services file and the updated state file in place.
"""
import argparse
import concurrent.futures as cf
import json
import os
import ssl
import urllib.request

# same UA as db/cron.go -- no "Mozilla", so Anubis walls let the probe through
UA = {"User-Agent": "Farside/1.0 (+https://github.com/19-84/farside)"}
CTX = ssl.create_default_context()

# kept in sync with db.blockPageMarkers / tools/probe
BLOCK = ["error code: 1003", "just a moment...", "attention required!",
         "cf-browser-verification", "enable javascript and cookies",
         "checking your browser", "<title>ddos-guard</title>",
         "/.well-known/ddos-guard/", "making sure you",
         'id="anubis_challenge"', "/.within.website/x/cmd/anubis/",
         "tollbat", "<title>gandalf</title>"]

# "the host answers but the frontend is gone" -- a 200 that is really dead
GONE = ["this domain is for sale", "domain is parked", "buy this domain",
        "service has been shutdown", "service has been shut down"]

# "the instance is refusing bots, not down" -- no strike for these
BOT_STATUS = {401, 403, 406, 418, 429}

# farside redirects clearnet browsers; overlay-network addresses can never be
# reached by its users (or probed from CI), so they only accumulate strikes
OVERLAY_TLDS = (".onion", ".i2p", ".ygg", ".loki")


def clearnet(url):
    if not isinstance(url, str) or not url.startswith(("https://", "http://")):
        return False
    host = url.split("/")[2].split(":")[0].lower()
    return not host.endswith(OVERLAY_TLDS)


def probe(base, test_url, retries, timeout):
    """Returns 'live', 'blocked' (bot defense; alive for real users) or 'dead'."""
    url = base.rstrip("/") + test_url.replace("<%=query%>", "current+weather")
    for _ in range(retries):
        try:
            r = urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                       timeout=timeout, context=CTX)
            if r.status != 200:
                continue  # transient 5xx etc. -> retry
            body = r.read(262144).decode("utf-8", "replace").lower()
            # an anti-bot wall is a consistent state, no point retrying
            if any(m in body for m in BLOCK):
                return "blocked"
            # so is a parked domain or a shutdown notice
            if not body.strip() or any(m in body for m in GONE):
                return "dead"
            return "live"
        except urllib.error.HTTPError as e:
            if e.code in BOT_STATUS:
                return "blocked"
            continue  # 404/410/5xx -> retry, dead if persistent
        except Exception:
            continue  # network blip -> retry
    return "dead"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default="services-full.json")
    ap.add_argument("--state", default="instance-strikes.json")
    ap.add_argument("--threshold", type=int, default=3)
    ap.add_argument("--retries", type=int, default=2)
    ap.add_argument("--timeout", type=int, default=8)
    ap.add_argument("--concurrency", type=int, default=20)
    args = ap.parse_args()

    services = json.load(open(args.file))
    strikes = json.load(open(args.state)) if os.path.exists(args.state) else {}

    # registries can leak non-URL entries (e.g. mozhi's Tor-only instances
    # have no "link", which jq turns into null) and overlay-network addresses
    # (breezewiki's .onion mirrors) -- drop them up front
    for s in services:
        s["instances"] = [i for i in s["instances"] if clearnet(i)]

    # one test_url per instance (services sharing an instance share the path)
    inst_test = {}
    for s in services:
        for inst in s["instances"]:
            inst_test.setdefault(inst, s.get("test_url", ""))

    with cf.ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        verdict = dict(zip(inst_test, ex.map(
            lambda it: probe(it[0], it[1], args.retries, args.timeout),
            inst_test.items())))

    # fallbacks are the last line of defense (served whenever a service's
    # instance list is empty) and rot silently -- probe them too, with the
    # same strike hysteresis. They are never pruned, only warned about.
    fb_test = {s["fallback"]: s.get("test_url", "")
               for s in services if s.get("fallback")}
    fb_only = {u: t for u, t in fb_test.items() if u not in inst_test}
    with cf.ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        verdict.update(dict(zip(fb_only, ex.map(
            lambda it: probe(it[0], it[1], args.retries, args.timeout),
            fb_only.items()))))

    # strike count per unique instance computed once (avoid double-counting
    # an instance that appears under multiple service types); only a hard-dead
    # probe strikes -- 'blocked' resets, same as 'live'
    nstrike = {i: (strikes.get(i, 0) + 1 if verdict[i] == "dead" else 0)
               for i in list(inst_test) + list(fb_only)}

    pruned, brink = {}, []
    for s in services:
        kept = []
        for inst in s["instances"]:
            if nstrike[inst] >= args.threshold:
                pruned.setdefault(s["type"], []).append(inst)
            else:
                kept.append(inst)
                if nstrike[inst] == args.threshold - 1:
                    brink.append((s["type"], inst, nstrike[inst]))
        s["instances"] = sorted(kept)

    # keep the count for everything probed this run, pruned or not: a registry
    # that re-lists a pruned instance tomorrow must not hand it a clean slate.
    # An instance no registry lists any more is not probed, so it ages out.
    new_state = {i: n for i, n in nstrike.items() if n > 0}

    json.dump(services, open(args.file, "w"), indent=2, ensure_ascii=False)
    open(args.file, "a").write("\n")
    json.dump(dict(sorted(new_state.items())), open(args.state, "w"), indent=2)
    open(args.state, "a").write("\n")

    counts = {v: sum(1 for x in verdict.values() if x == v)
              for v in ("live", "blocked", "dead")}
    print(f"probed {len(inst_test)} instances + {len(fb_only)} fallbacks: "
          f"{counts['live']} live, {counts['blocked']} bot-blocked (no strike), "
          f"{counts['dead']} dead")
    # instances already past the threshold last run are registry re-listings
    # of known-dead entries -- count them, but only list the newly dead ones
    relisted = sum(1 for urls in pruned.values() for u in urls
                   if strikes.get(u, 0) >= args.threshold)
    npruned = sum(len(v) for v in pruned.values())
    print(f"pruned {npruned} instance(s) dead >= {args.threshold} consecutive runs "
          f"({relisted} re-listed by a registry but still dead); newly pruned:")
    for t, urls in sorted(pruned.items()):
        for u in urls:
            if strikes.get(u, 0) < args.threshold:
                print(f"    - {t}: {u}")
    if brink:
        print(f"on brink ({args.threshold-1} strikes, pruned next run if still dead):")
        for t, u, n in sorted(brink):
            print(f"    ! {t}: {u}")

    # ::warning:: makes these show up as annotations on the Actions run
    for s in services:
        fb = s.get("fallback")
        if fb and nstrike.get(fb, 0) >= args.threshold:
            print(f"::warning::fallback for '{s['type']}' has been dead for "
                  f"{nstrike[fb]} consecutive runs, replace it: {fb}")


if __name__ == "__main__":
    main()
