package services

import "testing"

// Retired frontends must not resolve to themselves: a bare service name
// otherwise passes through MatchRequest unchanged, which would send
// pre-existing /whoogle/... and /searx/... links to a service that no longer
// exists. They should land on the living replacement instead.
func TestRetiredServicesAlias(t *testing.T) {
	cases := map[string]string{
		"whoogle": "searxng",
		"searx":   "searxng",
		"piped":   "invidious",
		"Whoogle": "searxng", // case-insensitive
	}

	for in, want := range cases {
		got, err := MatchRequest(in)
		if err != nil {
			t.Errorf("MatchRequest(%q) returned error: %v", in, err)
			continue
		}
		if got != want {
			t.Errorf("MatchRequest(%q) = %q, want %q", in, got, want)
		}
	}
}

// Live services must still pass through untouched, and URL-form requests must
// still go through regexMap rather than the alias table.
func TestLiveServicesUnaffected(t *testing.T) {
	for _, in := range []string{"searxng", "invidious", "nitter", "tent"} {
		got, err := MatchRequest(in)
		if err != nil || got != in {
			t.Errorf("MatchRequest(%q) = %q, %v; want %q, nil", in, got, err, in)
		}
	}

	// google.com has no "whoogle" target any more, so it must pick searxng.
	got, err := MatchRequest("google.com")
	if err != nil {
		t.Fatalf("MatchRequest(\"google.com\") returned error: %v", err)
	}
	if got != "searxng" {
		t.Errorf("MatchRequest(\"google.com\") = %q, want \"searxng\"", got)
	}
}
