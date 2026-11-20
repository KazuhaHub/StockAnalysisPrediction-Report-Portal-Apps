// Command APP_ID is the managed backend of the APP_ID app.
//
// It speaks the platform protocol (portal.backend/1) on a Unix socket: a
// readiness route, the boot handshake with Portal, viewer routes verified with
// the viewer assertion Portal signs into each relayed request, and an optional
// background task entry point that only enqueues work.
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
)

const (
	defaultSocketPath   = "/run/portal-app/http/app.sock"
	defaultRegistration = "/run/portal-app/broker/registration.json"
	defaultDataDir      = "/data"
)

func env(name, fallback string) string {
	if v := os.Getenv(name); v != "" {
		return v
	}
	return fallback
}

func main() {
	socket := env("PORTAL_APP_HTTP_SOCKET", defaultSocketPath)
	queue, err := NewQueue(env("APP_DATA_DIR", defaultDataDir), jobs)
	if err != nil {
		os.Exit(6)
	}

	// A fresh boot ID per start: Portal learns it in the handshake and a
	// viewer assertion issued for an earlier boot is refused.
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
	// Opt-in outbound HTTPS (network.proxy). Bound before any work can start.
	stopProxy, err := startEgressProxy()
	if err != nil {
		os.Exit(8)
	}
	// Start work only once the service can be reached, so a failing boot
	// does not spend a requeued task's attempts.
	stopQueue := queue.Start()
	srv := &http.Server{
		ReadHeaderTimeout: time.Second,
		ReadTimeout:       2 * time.Second,
		WriteTimeout:      5 * time.Second,
		IdleTimeout:       time.Second,
		MaxHeaderBytes:    65536,
		Handler:           newServer(queue, auth),
	}
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
	stopQueue()
	stopProxy()
	os.Exit(code)
}
