package db

import (
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"slices"
	"strings"
	"time"

	"github.com/benbusby/farside/services"
	"github.com/robfig/cron/v3"
)

const defaultPrimary = "https://farside.link/state"
const defaultCFPrimary = "https://cf.farside.link/state"

var LastUpdate time.Time

// skipInstanceChecks lists service types that bypass the availability check
// and are added to the pool unconditionally. It is intentionally empty:
// every instance is health-checked so dead ones are pruned. (searx/searxng
// were previously skipped, which caused dead instances to be served.)
var skipInstanceChecks = []string{}

func InitCronTasks() {
	log.Println("Initializing cron tasks...")
	updateServiceList()

	cronDisabled := os.Getenv("FARSIDE_CRON")
	if len(cronDisabled) == 0 || cronDisabled == "1" {
		// SkipIfStillRunning prevents a slow instance sweep (which can
		// exceed the 10m interval) from overlapping itself.
		c := cron.New(cron.WithChain(
			cron.SkipIfStillRunning(cron.DefaultLogger)))
		c.AddFunc("@every 10m", queryServiceInstances)
		c.AddFunc("@daily", updateServiceList)
		c.Start()
	}

	queryServiceInstances()
}

func updateServiceList() {
	// Only pull fresh service definitions from the repo when explicitly
	// enabled. Otherwise the local (possibly customized) services file is
	// preserved instead of being overwritten on every startup.
	if os.Getenv("FARSIDE_AUTO_UPDATE") == "1" {
		fileName := services.GetServicesFileName()
		_, _ = services.FetchServicesFile(fileName)
	}
	services.InitializeServices()
}

func queryServiceInstances() {
	log.Println("Starting instance queries...")

	isPrimary := os.Getenv("FARSIDE_PRIMARY")
	if len(isPrimary) == 0 || isPrimary != "1" {
		remoteServices, err := fetchInstancesFromPrimary()
		if err != nil {
			// Keep the existing instance data (and the real LastUpdate
			// timestamp) rather than marking a failed refresh as fresh.
			log.Println("Unable to fetch instances from primary", err)
			return
		}

		for _, service := range remoteServices {
			SetInstances(service.Type, service.Instances)
		}

		LastUpdate = time.Now().UTC()
		return
	}

	for _, service := range services.Services() {
		canSkip := slices.Contains[[]string, string](skipInstanceChecks, service.Type)

		fmt.Printf("===== %s =====\n", service.Type)
		var instances []string
		for _, instance := range service.Instances {
			testURL := strings.ReplaceAll(
				service.TestURL,
				"<%=query%>",
				"current+weather")
			available := queryServiceInstance(
				instance,
				testURL,
				canSkip)

			if available {
				instances = append(instances, instance)
			}
		}

		SetInstances(service.Type, instances)
	}

	LastUpdate = time.Now().UTC()
}

func fetchInstancesFromPrimary() ([]services.Service, error) {
	primaryURL := defaultPrimary
	useCF := os.Getenv("FARSIDE_CF_ENABLED")
	if len(useCF) > 0 && useCF == "1" {
		primaryURL = defaultCFPrimary
	}

	resp, err := http.Get(primaryURL)
	if err != nil {
		return nil, err
	}

	defer resp.Body.Close()

	bodyBytes, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}

	var serviceList []services.Service
	err = json.Unmarshal(bodyBytes, &serviceList)
	return serviceList, err
}

func queryServiceInstance(instance, testURL string, canSkipCheck bool) bool {
	testMode := os.Getenv("FARSIDE_TEST")
	if len(testMode) > 0 && testMode == "1" {
		return true
	}

	if canSkipCheck {
		fmt.Printf("    [INFO] Adding %s\n", instance)
		return true
	}

	ua := "Mozilla/5.0 (compatible; Farside/1.0.0; +https://farside.link)"
	url := instance + testURL

	req, err := http.NewRequest(http.MethodGet, url, nil)
	if err != nil {
		fmt.Println("    [ERRO] Failed to create new http request!", err)
		return false
	}

	req.Header.Set("User-Agent", ua)
	client := &http.Client{
		Timeout: 10 * time.Second,
	}
	resp, err := client.Do(req)
	if err != nil {
		fmt.Println("    [ERRO] Error fetching instance:", err)
		return false
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		fmt.Printf("    [WARN] Received non-200 status for %s\n", url)
		return false
	}

	body, err := io.ReadAll(io.LimitReader(resp.Body, 64*1024))
	if err != nil {
		fmt.Println("    [ERRO] Error reading instance body:", err)
		return false
	}

	if isBlockPage(body) {
		fmt.Printf("    [WARN] %s served a block/challenge page\n", url)
		return false
	}

	fmt.Printf("    [INFO] Received 200 status for %s\n", url)
	return true
}

// isBlockPage reports whether a 200 response body is actually an anti-bot
// challenge or block page rather than a working frontend. Markers are matched
// against the lowercased body and chosen to be specific enough not to prune
// legitimate instances. Markers must be HTML-entity-safe (e.g. match the text
// before an apostrophe, since bodies contain &#39; not ').
func isBlockPage(body []byte) bool {
	lower := strings.ToLower(string(body))
	for _, m := range blockPageMarkers {
		if strings.Contains(lower, m) {
			return true
		}
	}
	return false
}

// blockPageMarkers identifies anti-bot challenge/block pages served with a 200
// status. Keep this list in sync with tools/probe.
var blockPageMarkers = []string{
	"error code: 1003",            // Cloudflare direct-IP / proxy block
	"just a moment...",            // Cloudflare JS challenge
	"attention required!",         // Cloudflare WAF block
	"cf-browser-verification",     // Cloudflare challenge asset
	"enable javascript and cookies", // Cloudflare interstitial
	"checking your browser",       // DDoS-Guard / generic interstitial
	"ddos-guard",                  // DDoS-Guard
	"making sure you",             // Anubis proof-of-work wall ("Making sure you're not a bot!")
	"tollbat",                     // Tollbat challenge
	"<title>gandalf</title>",      // Gandalf auth portal
}
