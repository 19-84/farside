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

"Dead" = the same liveness test the server uses: not HTTP 200, or a 200 that is
actually an anti-bot wall. Identity/content markers are NOT used here -- they
are unreliable for some frontends and would prune real instances.

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


def is_live(base, test_url, retries, timeout):
    url = base.rstrip("/") + test_url.replace("<%=query%>", "current+weather")
    for _ in range(retries):
        try:
            r = urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                       timeout=timeout, context=CTX)
            if r.status != 200:
                continue  # transient 5xx etc. -> retry
            body = r.read(262144).decode("utf-8", "replace").lower()
            # an anti-bot wall is a consistent state, not transient: dead, no retry
            return not any(m in body for m in BLOCK)
        except Exception:
            continue  # network blip -> retry
    return False


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

    # one test_url per instance (services sharing an instance share the path)
    inst_test = {}
    for s in services:
        for inst in s["instances"]:
            inst_test.setdefault(inst, s.get("test_url", ""))

    with cf.ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        live = dict(zip(inst_test, ex.map(
            lambda it: is_live(it[0], it[1], args.retries, args.timeout),
            inst_test.items())))

    # strike count per unique instance computed once (avoid double-counting
    # an instance that appears under multiple service types)
    nstrike = {i: (0 if live[i] else strikes.get(i, 0) + 1) for i in inst_test}

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

    still = {i for s in services for i in s["instances"]}
    new_state = {i: nstrike[i] for i in still if nstrike[i] > 0}

    json.dump(services, open(args.file, "w"), indent=2, ensure_ascii=False)
    open(args.file, "a").write("\n")
    json.dump(dict(sorted(new_state.items())), open(args.state, "w"), indent=2)
    open(args.state, "a").write("\n")

    live_n = sum(1 for v in live.values() if v)
    print(f"probed {len(inst_test)} instances: {live_n} live, {len(inst_test)-live_n} failing")
    npruned = sum(len(v) for v in pruned.values())
    print(f"pruned {npruned} instance(s) dead >= {args.threshold} consecutive runs:")
    for t, urls in sorted(pruned.items()):
        for u in urls:
            print(f"    - {t}: {u}")
    if brink:
        print(f"on brink ({args.threshold-1} strikes, pruned next run if still dead):")
        for t, u, n in sorted(brink):
            print(f"    ! {t}: {u}")


if __name__ == "__main__":
    main()
