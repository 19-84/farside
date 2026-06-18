// Command probe health-checks every instance (and fallback) in a Farside
// services JSON file and prints a per-type report.
//
// For each instance it performs the same check the server's cron uses
// (GET <instance><test_url>, expect HTTP 200, reject Cloudflare block /
// challenge pages) and additionally validates that the response body
// contains a content marker identifying that frontend type -- so a 200
// from a parked domain or an unrelated server is flagged as suspect.
//
//	go run ./tools/probe -file services.json
//	go run ./tools/probe -file services-full.json -c 30 -timeout 8s
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"net/http"
	"os"
	"sort"
	"strings"
	"sync"
	"time"
)

type service struct {
	Type      string   `json:"type"`
	TestURL   string   `json:"test_url"`
	Fallback  string   `json:"fallback"`
	Instances []string `json:"instances"`
}

// contentMarkers maps a service type to case-insensitive substrings, any of
// which identifies a valid response for that frontend. These are stable
// software identifiers (name in title/footer/meta/CSS), not version strings.
// An empty list means "no content check" (status + block-page only).
var contentMarkers = map[string][]string{
	"libreddit":         {"redlib", "libreddit"},
	"redlib":            {"redlib", "libreddit"},
	"teddit":            {"teddit"},
	"proxigram":         {"proxigram"},
	"invidious":         {"invidious"},
	"piped":             {"piped"},
	"nitter":            {"nitter"},
	"scribe":            {"scribe"},
	"simplytranslate":   {"simplytranslate", "simply translate"},
	"lingva":            {"lingva"},
	"rimgo":             {"rimgo"},
	"whoogle":           {"whoogle"},
	"searx":             {"searx"},
	"searxng":           {"searxng", "searx"},
	"wikiless":          {"wikiless"},
	"librarian":         {"librarian"},
	"proxitok":          {"proxitok"},
	"quetre":            {"quetre"},
	"libremdb":          {"libremdb"},
	"dumb":              {"dumb", "genius"},
	"breezewiki":        {"breezewiki"},
	"gothub":            {"gothub"},
	"anonymousoverflow": {"anonymousoverflow", "anonymous overflow"},
	"4get":              {"4get"},
	"librey":            {"librey", "librex"},
	"tent":              {"tent"},
}

// blockMarkers identify an anti-bot challenge/block page served with 200.
// Kept in sync with db.blockPageMarkers in the server. HTML-entity-safe.
var blockMarkers = []string{
	"error code: 1003",              // Cloudflare direct-IP / proxy block
	"just a moment...",              // Cloudflare JS challenge
	"attention required!",           // Cloudflare WAF block
	"cf-browser-verification",       // Cloudflare challenge asset
	"enable javascript and cookies", // Cloudflare interstitial
	"checking your browser",         // DDoS-Guard / generic interstitial
	"ddos-guard",                    // DDoS-Guard
	"making sure you",               // Anubis proof-of-work wall
	"tollbat",                       // Tollbat challenge
	"<title>gandalf</title>",        // Gandalf auth portal
}

const userAgent = "Mozilla/5.0 (compatible; Farside/1.0.0; +https://farside.link)"

type result struct {
	svcType    string
	instance   string
	isFallback bool
	status     int
	elapsed    time.Duration
	reachable  bool
	blocked    bool
	markerKnown bool
	markerOK   bool
	reason     string
}

// pass reports whether the instance is healthy by the server's criteria
// (reachable, 200, not a block page). Marker mismatch is reported but does
// not by itself fail the instance, so we can gauge marker reliability.
func (r result) pass() bool { return r.reachable && r.status == 200 && !r.blocked }

func probe(client *http.Client, svc service, instance string, isFallback bool) result {
	r := result{svcType: svc.Type, instance: instance, isFallback: isFallback}
	testURL := strings.ReplaceAll(svc.TestURL, "<%=query%>", "current+weather")
	url := strings.TrimSuffix(instance, "/") + testURL

	req, err := http.NewRequest(http.MethodGet, url, nil)
	if err != nil {
		r.reason = "bad request: " + err.Error()
		return r
	}
	req.Header.Set("User-Agent", userAgent)

	start := time.Now()
	resp, err := client.Do(req)
	r.elapsed = time.Since(start)
	if err != nil {
		r.reason = "unreachable: " + condense(err.Error())
		return r
	}
	defer resp.Body.Close()
	r.reachable = true
	r.status = resp.StatusCode

	if resp.StatusCode != http.StatusOK {
		r.reason = fmt.Sprintf("HTTP %d", resp.StatusCode)
		return r
	}

	body, err := io.ReadAll(io.LimitReader(resp.Body, 256*1024))
	if err != nil {
		r.reason = "read error: " + condense(err.Error())
		return r
	}
	low := strings.ToLower(string(body))

	for _, m := range blockMarkers {
		if strings.Contains(low, m) {
			r.blocked = true
			r.reason = "block/challenge page"
			return r
		}
	}

	if ms := contentMarkers[svc.Type]; len(ms) > 0 {
		r.markerKnown = true
		for _, m := range ms {
			if strings.Contains(low, strings.ToLower(m)) {
				r.markerOK = true
				break
			}
		}
	}

	switch {
	case r.markerKnown && !r.markerOK:
		r.reason = "200 OK but no content marker (suspect)"
	default:
		r.reason = "ok"
	}
	return r
}

func condense(s string) string {
	s = strings.ReplaceAll(s, "\n", " ")
	if len(s) > 90 {
		return s[:90] + "…"
	}
	return s
}

func main() {
	file := flag.String("file", "services.json", "services JSON file to probe")
	conc := flag.Int("c", 25, "max concurrent probes")
	timeout := flag.Duration("timeout", 10*time.Second, "per-request timeout")
	flag.Parse()

	raw, err := os.ReadFile(*file)
	if err != nil {
		fmt.Fprintln(os.Stderr, "read services file:", err)
		os.Exit(2)
	}
	var services []service
	if err := json.Unmarshal(raw, &services); err != nil {
		fmt.Fprintln(os.Stderr, "parse services file:", err)
		os.Exit(2)
	}

	client := &http.Client{Timeout: *timeout}

	type job struct {
		svc        service
		instance   string
		isFallback bool
	}
	var jobs []job
	for _, svc := range services {
		for _, inst := range svc.Instances {
			jobs = append(jobs, job{svc, inst, false})
		}
		if svc.Fallback != "" {
			jobs = append(jobs, job{svc, svc.Fallback, true})
		}
	}

	results := make([]result, len(jobs))
	sem := make(chan struct{}, *conc)
	var wg sync.WaitGroup
	for i, j := range jobs {
		wg.Add(1)
		sem <- struct{}{}
		go func(i int, j job) {
			defer wg.Done()
			defer func() { <-sem }()
			results[i] = probe(client, j.svc, j.instance, j.isFallback)
		}(i, j)
	}
	wg.Wait()

	report(services, results)
}

func report(services []service, results []result) {
	byType := map[string][]result{}
	for _, r := range results {
		byType[r.svcType] = append(byType[r.svcType], r)
	}

	types := make([]string, 0, len(byType))
	for t := range byType {
		types = append(types, t)
	}
	sort.Strings(types)

	var totalInst, passInst, deadFallbacks, suspectMarkers int
	for _, t := range types {
		rs := byType[t]
		sort.Slice(rs, func(i, j int) bool {
			if rs[i].isFallback != rs[j].isFallback {
				return !rs[i].isFallback
			}
			return rs[i].instance < rs[j].instance
		})
		var p, n int
		for _, r := range rs {
			if r.isFallback {
				continue
			}
			n++
			if r.pass() {
				p++
			}
		}
		totalInst += n
		passInst += p
		fmt.Printf("\n== %-17s %d/%d instances healthy ==\n", t, p, n)
		for _, r := range rs {
			tag := "  "
			switch {
			case r.isFallback && !r.pass():
				tag = "💀F"
				deadFallbacks++
			case r.isFallback:
				tag = "★F"
			case !r.pass():
				tag = "✗ "
			case r.markerKnown && !r.markerOK:
				tag = "? "
				suspectMarkers++
			default:
				tag = "✓ "
			}
			mark := "-"
			if r.markerKnown {
				if r.markerOK {
					mark = "marker✓"
				} else {
					mark = "marker✗"
				}
			}
			fmt.Printf("  %s %-45s %4dms  %-8s %s\n",
				tag, r.instance, r.elapsed.Milliseconds(), mark, r.reason)
		}
	}

	fmt.Printf("\n========================================\n")
	fmt.Printf("instances healthy:    %d/%d\n", passInst, totalInst)
	fmt.Printf("dead fallbacks:       %d\n", deadFallbacks)
	fmt.Printf("200-but-no-marker:    %d (suspect: parked/wrong page or weak marker)\n", suspectMarkers)
	if deadFallbacks > 0 {
		os.Exit(1)
	}
}
