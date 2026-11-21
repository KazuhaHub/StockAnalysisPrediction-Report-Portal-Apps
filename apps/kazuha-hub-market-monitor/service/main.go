// Command market-monitor is the managed backend of the market-monitor app.
//
// It speaks the platform protocol on a Unix socket, runs the daily Python
// jobs inside the container when a platform task triggers them, and serves
// the resulting snapshots to viewers a page at a time.
package main

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"net"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"
	_ "time/tzdata" // the schedule's zone must not depend on the image's tzdata
)

const (
	defaultSocketPath   = "/run/portal-app/http/app.sock"
	defaultRegistration = "/run/portal-app/broker/registration.json"
	defaultDataDir      = "/data"
	defaultPython       = "/app/venv/bin/python"
	defaultJobEntry     = "/app/pipeline/mm_job.py"
)

func env(name, fallback string) string {
	if v := os.Getenv(name); v != "" {
		return v
	}
	return fallback
}

// jobSpecs lists the daily jobs. The time limits follow the measured run
// times in the pipeline README with headroom; the market-data rebuild is the
// longest.
func jobSpecs() []JobSpec {
	python, entry := env("MM_PYTHON", defaultPython), env("MM_JOB_ENTRY", defaultJobEntry)
	spec := func(name string, timeout time.Duration) JobSpec {
		return JobSpec{Name: name, Command: []string{python, entry, name}, Timeout: timeout}
	}
	return []JobSpec{
		spec("marketdata", 4*time.Hour),
		spec("sentiment", 90*time.Minute),
		spec("panorama", 2*time.Hour),
		spec("etf", 90*time.Minute),
		spec("margin", 2*time.Hour),
	}
}

func main() {
	if len(os.Args) > 1 && os.Args[1] == validateHistoryArg {
		os.Exit(runValidateHistory(os.Args[2:], os.Stdin, os.Stdout, os.Stderr))
	}
	socket := env("PORTAL_APP_HTTP_SOCKET", defaultSocketPath)
	dataDir := env("MM_DATA_DIR", defaultDataDir)
	store := NewStore(dataDir)
	runner, err := NewRunner(dataDir, jobSpecs(), store)
	if err != nil {
		os.Exit(6)
	}
	runner.afterRun = func() { warnIfQuotaNearlyUsed(dataDir) }
	warnIfQuotaNearlyUsed(dataDir)

	var boot [16]byte
	if _, err := rand.Read(boot[:]); err != nil {
		os.Exit(5)
	}
	auth := newAuthority(env("PORTAL_APP_REGISTRATION", defaultRegistration), hex.EncodeToString(boot[:]))

	listener, err := net.Listen("unix", socket)
	if err != nil {
		os.Exit(2)
	}
	if err := os.Chmod(socket, 0600); err != nil {
		os.Exit(3)
	}
	// The workers reach the network only through the forwarder, so it listens
	// before any job can start.
	_, stopProxy, err := startEgressProxy()
	if err != nil {
		os.Exit(8)
	}
	// Start jobs only once the service can be reached, so a failing boot
	// does not spend a requeued run's attempts.
	stopRunner := runner.Start()
	// The slots are exchange times; they are not configurable.
	loc, err := time.LoadLocation("Asia/Shanghai")
	if err != nil {
		stopRunner()
		stopProxy()
		os.Exit(7)
	}
	stopScheduler := NewScheduler(runner, DefaultSlots(), loc).Start()
	srv := &http.Server{
		ReadHeaderTimeout: time.Second,
		ReadTimeout:       2 * time.Second,
		WriteTimeout:      5 * time.Second,
		IdleTimeout:       time.Second,
		MaxHeaderBytes:    65536,
		Handler:           newServer(store, runner, auth),
	}
	// On SIGTERM stop serving, then stop the worker, which kills a running
	// job's process group; the next start queues that run again.
	ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGTERM, syscall.SIGINT)
	defer cancel()
	served := make(chan error, 1)
	go func() { served <- srv.Serve(listener) }()
	code := 0
	select {
	case <-ctx.Done():
		shutdown, done := context.WithTimeout(context.Background(), 5*time.Second)
		_ = srv.Shutdown(shutdown)
		done()
	case err := <-served:
		if !errors.Is(err, http.ErrServerClosed) {
			code = 4
		}
	}
	stopScheduler()
	stopRunner()
	stopProxy()
	os.Exit(code)
}
