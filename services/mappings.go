package services

import (
	"errors"
	"math/rand"
	"regexp"
	"strings"
)

type RegexMapping struct {
	Pattern *regexp.Regexp
	Targets []string
}

var regexMap = []RegexMapping{
	{
		// YouTube ("piped" kept in the pattern so old Piped links still
		// route somewhere useful; the service itself was removed)
		Pattern: regexp.MustCompile(`youtu(\.be|be\.com)|invidious|piped`),
		Targets: []string{"invidious"},
	},
	{
		// Twitter / X
		Pattern: regexp.MustCompile(`twitter\.com|x\.com|nitter`),
		Targets: []string{"nitter"},
	},
	{
		// Reddit
		Pattern: regexp.MustCompile(`reddit\.com|libreddit|redlib|teddit`),
		Targets: []string{"libreddit", "redlib", "teddit"},
	},
	{
		// Google Search
		// whoogle stays in the pattern so existing Whoogle links keep
		// routing, but it is no longer a target: the project was archived
		// in Aug 2026 and every known instance is dead.
		Pattern: regexp.MustCompile(`google\.com|whoogle|searx|searxng`),
		Targets: []string{"searxng"},
	},
	{
		// Medium
		Pattern: regexp.MustCompile(`medium\.com|scribe`),
		Targets: []string{"scribe"},
	},
	{
		// Imgur
		Pattern: regexp.MustCompile(`imgur\.com|rimgo`),
		Targets: []string{"rimgo"},
	},
	{
		// Google Translate
		Pattern: regexp.MustCompile(`translate\.google\.com|lingva|simplytranslate|mozhi`),
		Targets: []string{"lingva", "simplytranslate", "mozhi"},
	},
	{
		// Fandom
		Pattern: regexp.MustCompile(`.*fandom\.com|breezewiki`),
		Targets: []string{"breezewiki"},
	},
	{
		// IMDB
		Pattern: regexp.MustCompile(`imdb\.com|libremdb`),
		Targets: []string{"libremdb"},
	},
	{
		// Goodreads
		Pattern: regexp.MustCompile(`goodreads\.com|biblioreads`),
		Targets: []string{"biblioreads"},
	},
	{
		// Quora
		Pattern: regexp.MustCompile(`quora\.com|quetre`),
		Targets: []string{"quetre"},
	},
	{
		// GitHub
		Pattern: regexp.MustCompile(`github\.com|gothub`),
		Targets: []string{"gothub"},
	},
	{
		// StackOverflow
		Pattern: regexp.MustCompile(`stackoverflow\.com|anonymousoverflow`),
		Targets: []string{"anonymousoverflow"},
	},
	{
		// Genius
		Pattern: regexp.MustCompile(`genius\.com|dumb`),
		Targets: []string{"dumb"},
	},
	{
		// 4get
		// Note: Could be used for redirecting other search engine
		// requests, but would need special handling
		Pattern: regexp.MustCompile("4get"),
		Targets: []string{"4get"},
	},
	{
		// LibreY
		// Note: Could be used for redirecting other search engine
		// requests, but would need special handling
		Pattern: regexp.MustCompile("librex|librey"),
		Targets: []string{"librey"},
	},
	{
		// Tent
		// Note: This is a Bandcamp alternative, but the endpoints are
		// completely different than Bandcamp, so 1-to-1 mapping of URLs
		// is not possible without some additional work
		Pattern: regexp.MustCompile("tent"),
		Targets: []string{"tent"},
	},
}

// retiredAliases maps a retired frontend onto a living equivalent. A bare
// service name (no ".") otherwise passes through MatchRequest unchanged, so
// without this a link minted before the service was retired -- /whoogle/...,
// /searx/... -- resolves to a service that no longer exists and errors out.
// URL-form requests are unaffected: those still go through regexMap.
var retiredAliases = map[string]string{
	"whoogle": "searxng", // archived Aug 2026, every known instance dead
	"searx":   "searxng", // discontinued upstream; SearXNG is the successor
	"piped":   "invidious",
}

func MatchRequest(service string) (string, error) {
	if !strings.Contains(service, ".") {
		if alias, ok := retiredAliases[strings.ToLower(service)]; ok {
			return alias, nil
		}
	}

	for _, mapping := range regexMap {
		hasMatch := mapping.Pattern.MatchString(service)
		if !hasMatch {
			continue
		}

		if !strings.Contains(service, ".") {
			return service, nil
		}

		index := rand.Intn(len(mapping.Targets))
		value := mapping.Targets[index]
		return value, nil
	}

	return "", errors.New("no match found")
}
