package services

import (
	"encoding/json"
	"io"
	"net/http"
	"os"
	"sync"
)

var (
	listMu      sync.RWMutex
	serviceList []Service
	fallbackMap map[string]string
)

// Services returns a snapshot of the current service list. The returned
// slice shares its backing array with the package and must not be mutated.
func Services() []Service {
	listMu.RLock()
	defer listMu.RUnlock()
	return serviceList
}

// Fallback returns the fallback URL for a service type, if one is defined.
func Fallback(service string) (string, bool) {
	listMu.RLock()
	defer listMu.RUnlock()
	link, ok := fallbackMap[service]
	return link, ok
}

const (
	baseRepoLink = "https://raw.githubusercontent.com/benbusby/farside/refs/heads/main/"

	noCFServicesJSON = "services.json"
	fullServicesJSON = "services-full.json"
)

type Service struct {
	Type      string   `json:"type"`
	TestURL   string   `json:"test_url,omitempty"`
	Fallback  string   `json:"fallback,omimtempty"`
	Instances []string `json:"instances"`
}

func GetServicesFileName() string {
	cloudflareEnabled := false

	cfEnabledVar := os.Getenv("FARSIDE_CF_ENABLED")
	if len(cfEnabledVar) > 0 && cfEnabledVar == "1" {
		cloudflareEnabled = true
	}

	serviceJSON := noCFServicesJSON
	if cloudflareEnabled {
		serviceJSON = fullServicesJSON
	}

	return serviceJSON
}

func FetchServicesFile(serviceJSON string) ([]byte, error) {
	resp, err := http.Get(baseRepoLink + serviceJSON)
	if err != nil {
		return nil, err
	}

	defer resp.Body.Close()

	bodyBytes, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}

	err = os.WriteFile(serviceJSON, bodyBytes, 0666)
	if err != nil {
		return nil, err
	}

	return bodyBytes, nil
}

func InitializeServices() error {
	serviceJSON := GetServicesFileName()
	fileBytes, err := os.ReadFile(serviceJSON)
	if err != nil {
		fileBytes, err = FetchServicesFile(serviceJSON)
		if err != nil {
			return err
		}
	}

	var parsed []Service
	err = json.Unmarshal(fileBytes, &parsed)
	if err != nil {
		return err
	}

	fallbacks := make(map[string]string)
	for _, serviceElement := range parsed {
		fallbacks[serviceElement.Type] = serviceElement.Fallback
	}

	listMu.Lock()
	serviceList = parsed
	fallbackMap = fallbacks
	listMu.Unlock()

	return nil
}
