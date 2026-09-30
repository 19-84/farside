package db

import "testing"

func TestIsBlockPage(t *testing.T) {
	cases := []struct {
		name string
		body string
		want bool
	}{
		{"anubis default title", `<title>Making sure you&#39;re not a bot!</title>`, true},
		{"anubis custom title", `<title>Verifying your browser…</title>` +
			`<script id="anubis_challenge" type="application/json">{}</script>`, true},
		{"anubis script only", `<script type="module" src="/.within.website/x/cmd/anubis/static/js/main.mjs">`, true},
		{"ddos-guard challenge", `<title>DDoS-Guard</title>`, true},
		{"cloudflare challenge", `<title>Just a moment...</title>`, true},
		// Real content that merely names the vendors must not be rejected.
		{"readme mentioning walls", `<article>prunes instances serving Cloudflare/DDoS-Guard/Anubis ` +
			`challenge pages</article>`, false},
		{"frontend page", `<title>r/popular - Redlib</title>`, false},
	}
	for _, c := range cases {
		if got := isBlockPage([]byte(c.body)); got != c.want {
			t.Errorf("%s: isBlockPage = %v, want %v", c.name, got, c.want)
		}
	}
}
