> [!NOTE]
> This is a maintained fork of [benbusby/farside](https://github.com/benbusby/farside),
> which was archived in August 2026 and whose official instance (farside.link) has been
> shut down.
>
> Upstream cited anti-bot challenge systems making instance health checks unreliable.
> This fork addresses that directly: health checks detect and prune instances serving
> Cloudflare/DDoS-Guard/Anubis challenge pages behind a 200 status, and a daily CI job
> refreshes the instance lists and publishes a
> [status page](https://19-84.github.io/farside/).
>
> Because farside.link/state no longer exists, **every node now health-checks instances
> itself by default**. See [`FARSIDE_REPLICA_URL`](#environment-variables) if you want to
> mirror another node instead.

___

<div align="center" style="margin-bottom: 10px;">
<img src="https://raw.githubusercontent.com/19-84/farside/refs/heads/main/img/farside.svg" alt="Farside">
</div>
<br>

<div align="center">

[![MIT License](https://img.shields.io/github/license/19-84/farside.svg)](http://opensource.org/licenses/MIT)
[![Tests](https://github.com/19-84/farside/actions/workflows/tests.yml/badge.svg)](https://github.com/19-84/farside/actions/workflows/tests.yml)
[![Instances](https://github.com/19-84/farside/actions/workflows/update-instances.yml/badge.svg)](https://github.com/19-84/farside/actions/workflows/update-instances.yml)

<table>
  <tr>
    <td><a href="https://github.com/19-84/farside">GitHub</a></td>
    <td><a href="https://19-84.github.io/farside/">Instance status</a></td>
  </tr>
</table>

</div>

___

Contents
1. [About](#about)
2. [Demo](#demo)
3. [How It Works](#how-it-works)
4. [Cloudflare](#regarding-cloudflare)
5. [Development](#development)
    1. [Environment Variables](#environment-variables)
6. [Search Integration](#search-integration)
    1. [Kagi](#kagi)

## About

A redirecting service for FOSS alternative frontends.

Farside provides links that automatically redirect to
working instances of privacy-oriented alternative frontends, such as Nitter,
Libreddit, etc. This allows for users to have more reliable access to the
available public instances for a particular service, while also helping to
distribute traffic more evenly across all instances and avoid performance
bottlenecks and rate-limiting.

The original public instance, `farside.link`, has been shut down. Run your own
(see [Development](#development)) and substitute your own host wherever the
examples below use `farside.link`.

Farside also integrates smoothly with basic redirector extensions in most
browsers. For a simple example setup,
[refer to the wiki](https://github.com/benbusby/farside/wiki/Browser-Extension).

## Demo

Farside's links work with the following structure: `<your-host>/<service>/<path>`.
The examples below use the original `farside.link` host for illustration; those
URLs no longer resolve.

For example:

<table>
    <tr>
        <td>Service</td>
        <td>Page</td>
        <td>Farside Link</td>
    </tr>
    <tr>
        <td><a href="https://sr.ht/~edwardloveall/Scribe/">Scribe</a></td>
        <td>View Medium post</td>
        <td><a href="https://farside.link/scribe/@ftrain/big-data-small-effort-b62607a43a8c">https://farside.link/scribe/@ftrain/big-data-small-effort-b62607a43a8c</a></td>
    </tr>
    <tr>
        <td><a href="https://github.com/spikecodes/libreddit">Libreddit</a></td>
        <td>/r/popular</td>
        <td><a href="https://farside.link/libreddit/r/popular">https://farside.link/libreddit/r/popular</a></td>
    </tr>
    <tr>
        <td><a href="https://gitdab.com/cadence/breezewiki">BreezeWiki</a></td>
        <td>Balatro Wiki</td>
        <td><a href="https://farside.link/breezewiki/balatrogame">https://farside.link/https://balatrogame.fandom.com</a></td>
    </tr>
    <tr>
        <td><a href="https://github.com/searxng/searxng">SearXNG</a></td>
        <td>Search "EFF"</td>
        <td><a href="https://farside.link/searxng/search?q=EFF">https://farside.link/searxng/search?q=EFF</a></td>
    </tr>
    <tr>
        <td><a href="https://codeberg.org/ManeraKai/simplytranslate">SimplyTranslate</a></td>
        <td>Translate "hola"</td>
        <td><a href="https://farside.link/simplytranslate/?engine=google&text=hola">https://farside.link/simplytranslate/?engine=google&text=hola</a></td>
    </tr>
    <tr>
        <td><a href="https://github.com/TheDavidDelta/lingva-translate">Lingva</a></td>
        <td>Translate "bonjour"</td>
        <td><a href="https://farside.link/lingva/auto/en/bonjour">https://farside.link/lingva/auto/en/bonjour</a></td>
    </tr>
    <tr>
        <td><a href="https://codeberg.org/video-prize-ranch/rimgo">Rimgo</a></td>
        <td>View photo album</td>
        <td><a href="https://farside.link/rimgo/a/H8M4rcp">https://farside.link/rimgo/a/H8M4rcp</a></td>
    </tr>
</table>

<sup>Note: This table doesn't include all available services. For a complete list of supported frontends, see the <a href="https://19-84.github.io/farside/">instance status page</a>, <a href="services.json">services.json</a>, or the <code>/state</code> endpoint of your own deployment.</sup>

Farside also accepts URLs to "parent" services, and will redirect to an appropriate front end service, for example:

- https://farside.link/https://balatrogame.fandom.com/wiki/Abandoned_Deck will redirect to a [BreezeWiki](https://gitdab.com/cadence/breezewiki) instance
- https://farside.link/reddit.com/r/popular will redirect to a [Libreddit](https://github.com/spikecodes/libreddit) or [Teddit](https://codeberg.org/teddit/teddit) instance
- etc.

## How It Works

The app runs with an internally scheduled cron task that queries all instances
for services defined in [services.json](services.json) every 5 minutes. For
each instance, as long as the instance takes <5 seconds to respond and returns
a successful response code, the instance is added to a list of available
instances for that particular service. If not, it is discarded until the next
update period.

Farside's routing is very minimal, with only the following routes:

- `/`
  - The app home page, displaying all live instances for every service
- `/:service/*glob`
  - The main endpoint for redirecting a user to a working instance of a
    particular service with the specified path
  - Ex: `/libreddit/r/popular` would navigate to `<libreddit instance
    URL>/r/popular`
    - If the service provided is actually a URL to a "parent" service
      (i.e. "youtube.com" instead of "invidious"), Farside
      will determine the correct frontend to use for the specified URL.
  - Note that a path is not required. `/libreddit` for example will still
    redirect the user to a working libreddit instance
- `/_/:service/*glob`
  - Achieves the same redirect as the main `/:service/*glob` endpoint, but
    preserves a short landing page in the browser's history to allow quickly
    jumping between instances by navigating back.
  - Ex: `/_/nitter` -> nitter instance A -> (navigate back one page) -> nitter
    instance B -> ...
  - *Note: Uses Javascript to preserve the page in history*

When a service is requested with the `/:service/...` endpoint, Farside requests
the list of working instances from the db and returns a random one from the list
and adds that instance as a new entry in the db to remove from subsequent
requests for that service. For example:

A user navigates to `/nitter` and is redirected to `nitter.net`. The next user
to request `/nitter` will be guaranteed to not be directed to `nitter.net`, and
will instead be redirected to a separate (random) working instance. That
instance will now take the place of `nitter.net` as the "reserved" instance, and
`nitter.net` will be returned to the list of available Nitter instances.

This "reserving" of previously chosen instances is performed in an attempt to
ensure better distribution of traffic to available instances for each service.

Farside does not perform any application-level ratelimiting itself; run it
behind a reverse proxy (e.g. nginx, Caddy) if you need per-IP request limits.

## Regarding Cloudflare
Instances deployed behind Cloudflare are kept in a separate list. By default
Farside uses `services.json`, which excludes them. To also serve instances that
use Cloudflare, set `FARSIDE_CF_ENABLED=1`, which switches to the full instance
list in `services-full.json`.

(The original deployment offered this as a separate `cf.farside.link` host; that
host has been shut down along with the rest of the original service.)

If you do use the full instance list, please be aware that Cloudflare takes
steps to block site visitors using Tor (and some VPNs), and that their mission
to centralize the entire web behind their service ultimately goes against what
Farside is trying to solve. Use at your own discretion.

## Development

- Install [Go](https://go.dev/doc/install)
- Compile with `go build`

### Environment Variables

<table>
    <tr>
        <td>Name</td>
        <td>Purpose</td>
    </tr>
    <tr>
        <td>FARSIDE_TEST</td>
        <td>If enabled, bypasses the instance availability check and adds all instances to the pool</td>
    </tr>
    <tr>
        <td>FARSIDE_PORT</td>
        <td>The port to run Farside on (default: `4001`)</td>
    </tr>
    <tr>
        <td>FARSIDE_DB_DIR</td>
        <td>The path to the directory to use for storing instance data (default: `./`)</td>
    </tr>
    <tr>
        <td>FARSIDE_CF_ENABLED</td>
        <td>Set to 1 to enable redirecting to instances behind cloudflare</td>
    </tr>
    <tr>
        <td>FARSIDE_CRON</td>
        <td>Set to 0 to deactivate the periodic instance availability check</td>
    </tr>
    <tr>
        <td>FARSIDE_REPLICA_URL</td>
        <td>Mirror instance state from another Farside node's <code>/state</code> endpoint instead of health-checking instances directly. Unset (the default) means this node probes instances itself</td>
    </tr>
    <tr>
        <td>FARSIDE_PRIMARY</td>
        <td>Obsolete, kept only so existing configs don't break. Direct health-checking is now the default, so this has no effect; a startup log message points at <code>FARSIDE_REPLICA_URL</code> if it is set</td>
    </tr>
    <tr>
        <td>FARSIDE_AUTO_UPDATE</td>
        <td>Set to 1 to re-fetch the services definition file from the upstream repo on startup and daily (off by default, so local edits are preserved)</td>
    </tr>
</table>

## Search Integration

### Kagi

https://kagi.com

On the settings page, go to `Search > Advanced > Open Redirects` and setup your redirects.

With the exception of BreezeWiki, most redirect rules can just extract the path of the
link you're visiting and append them to whichever Farside redirect you want to use.

For example:

##### Medium -> Scribe

`^https://medium.com/(.*)|https://farside.link/scribe/$1`

##### Fandom -> BreezeWiki

`^https://([^/]+).fandom.com/(.*)|https://farside.link/breezewiki/$1/$2`

