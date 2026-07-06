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

"Dead" = a hard failure only: DNS/connection errors, timeouts, 404/410, or
persistent 5xx. Bot-defense responses (429/403/418, anti-bot wall pages) do
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

UA = {"User-Agent": "Mozilla/5.0 (compatible; Farside/1.0.0; +https://farside.link)"}
CTX = ssl.create_default_context()

# kept in sync with db.blockPageMarkers / tools/probe
BLOCK = ["error code: 1003", "just a moment...", "attention required!",
         "cf-browser-verification", "enable javascript and cookies",
         "checking your browser", "ddos-guard", "making sure you",
         "tollbat", "<title>gandalf</title>"]

# "the instance is refusing bots, not down" -- no strike for these
BOT_STATUS = {401, 403, 406, 418, 429}


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
    # have no "link", which jq turns into null) -- drop them up front
    for s in services:
        s["instances"] = [i for i in s["instances"] if isinstance(i, str) and i]

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

    still = {i for s in services for i in s["instances"]} | set(fb_test)
    new_state = {i: nstrike[i] for i in still if nstrike[i] > 0}

    json.dump(services, open(args.file, "w"), indent=2, ensure_ascii=False)
    open(args.file, "a").write("\n")
    json.dump(dict(sorted(new_state.items())), open(args.state, "w"), indent=2)
    open(args.state, "a").write("\n")

    counts = {v: sum(1 for x in verdict.values() if x == v)
              for v in ("live", "blocked", "dead")}
    print(f"probed {len(inst_test)} instances + {len(fb_only)} fallbacks: "
          f"{counts['live']} live, {counts['blocked']} bot-blocked (no strike), "
          f"{counts['dead']} dead")
    npruned = sum(len(v) for v in pruned.values())
    print(f"pruned {npruned} instance(s) dead >= {args.threshold} consecutive runs:")
    for t, urls in sorted(pruned.items()):
        for u in urls:
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
