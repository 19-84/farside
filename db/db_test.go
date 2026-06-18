package db

import (
	"log"
	"os"
	"slices"
	"sync"
	"testing"
)

func TestMain(m *testing.M) {
	err := InitializeDB()
	if err != nil {
		log.Fatalln("Failed to initialize database")
	}

	exitCode := m.Run()

	_ = CloseDB()
	os.Exit(exitCode)
}

func TestDatabase(t *testing.T) {
	var (
		service = "test"
		siteA   = "a.com"
		siteB   = "b.com"
		siteC   = "c.com"
	)
	instances := []string{siteA, siteB, siteC}
	err := SetInstances(service, instances)
	if err != nil {
		t.Fatalf("Failed to set instances: %v\n", err)
	}

	dbInstances, err := GetAllInstances(service)
	if err != nil {
		t.Fatalf("Failed to retrieve instances: %v\n", err)
	}

	for _, instance := range instances {
		idx := slices.Index(dbInstances, instance)
		if idx < 0 {
			t.Fatalf("Failed to find instance in list")
		}
	}

	firstInstance, err := GetInstance(service, "")
	if err != nil {
		t.Fatalf("Failed to fetch single instance: %v\n", err)
	}

	secondInstance, err := GetInstance(service, "")
	if err != nil {
		t.Fatalf("Failed to fetch single instance (second): %v\n", err)
	} else if firstInstance == secondInstance {
		t.Fatalf("Same instance was selected twice")
	}
	// Note: do not CloseDB here; TestMain owns the DB lifecycle and other
	// tests run against the same handle.
}

// TestConcurrentGetInstance exercises GetInstance and GetServiceList from many
// goroutines at once. Without the mutexes guarding selectionMap and the service
// cache this panics with "concurrent map writes" (or trips -race); it is the
// regression test for that fix.
func TestConcurrentGetInstance(t *testing.T) {
	service := "concurrent"
	instances := []string{
		"https://a.example",
		"https://b.example",
		"https://c.example",
		"https://d.example",
	}
	if err := SetInstances(service, instances); err != nil {
		t.Fatalf("Failed to set instances: %v", err)
	}

	const (
		workers    = 50
		iterations = 100
	)
	var wg sync.WaitGroup
	wg.Add(workers)
	for i := 0; i < workers; i++ {
		go func() {
			defer wg.Done()
			for j := 0; j < iterations; j++ {
				if _, err := GetInstance(service, ""); err != nil {
					t.Errorf("GetInstance failed: %v", err)
					return
				}
				_ = GetServiceList()
			}
		}()
	}
	wg.Wait()
}
