package main

import (
	"context"
	"crypto/rand"
	"encoding/base64"
	"encoding/hex"
	"errors"
	"flag"
	"fmt"
	"log"
	"net"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/apps/status/service/internal/status"
)

var version = "0.2.0-beta.1"

const (
	defaultSocketPath = "/run/portal-app/http/app.sock"
	defaultDatabase   = "/data/status.db"
	storageKeyName    = "status.key"
)

type config struct {
	database     string
	registration string
	socket       string
}

func readSecret(path string) ([]byte, error) {
	info, err := os.Lstat(path)
	if err != nil || !info.Mode().IsRegular() || info.Size() > 16384 {
		return nil, errors.New("secret file is missing, oversized or not regular")
	}
	if info.Mode().Perm()&0077 != 0 {
		return nil, errors.New("secret file must be readable only by its owner")
	}
	return os.ReadFile(path)
}

// loadStorageKey returns the key that seals credentials in the database. It
// lives beside the database in the application's data volume, so a platform
// restore of /data always brings back a matching pair. The platform's secret
// custody replaces stored credentials, and with them this key, in a later
// storage change.
func loadStorageKey(path string) ([]byte, error) {
	if _, err := os.Lstat(path); errors.Is(err, os.ErrNotExist) {
		key := make([]byte, 32)
		if _, err := rand.Read(key); err != nil {
			return nil, err
		}
		out, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
		if err != nil {
			return nil, err
		}
		_, err = out.WriteString(base64.StdEncoding.EncodeToString(key) + "\n")
		if closeErr := out.Close(); err == nil {
			err = closeErr
		}
		if err != nil {
			return nil, err
		}
	}
	raw, err := readSecret(path)
	if err != nil {
		return nil, err
	}
	key, err := base64.StdEncoding.Strict().DecodeString(strings.TrimSpace(string(raw)))
	if err != nil || len(key) != 32 {
		return nil, errors.New("storage key must encode exactly 32 bytes")
	}
	return key, nil
}

func listenUnix(path string) (net.Listener, error) {
	if info, err := os.Lstat(path); err == nil {
		if info.Mode()&os.ModeSocket == 0 {
			return nil, errors.New("application socket path is occupied")
		}
		if err := os.Remove(path); err != nil {
			return nil, err
		}
	}
	listener, err := net.Listen("unix", path)
	if err != nil {
		return nil, err
	}
	if err := os.Chmod(path, 0600); err != nil {
		listener.Close()
		return nil, err
	}
	return listener, nil
}

// serve runs the application until the context ends. It listens only on the
// platform's Unix socket and answers only requests the platform relays.
func serve(ctx context.Context, cfg config) error {
	registration, err := status.LoadRegistration(cfg.registration)
	if err != nil {
		return err
	}
	clear(registration.Key)
	if err := os.MkdirAll(filepath.Dir(cfg.database), 0700); err != nil {
		return err
	}
	key, err := loadStorageKey(filepath.Join(filepath.Dir(cfg.database), storageKeyName))
	if err != nil {
		return err
	}
	store, err := status.Open(cfg.database, key)
	clear(key)
	if err != nil {
		return err
	}
	defer store.Close()
	restored, err := store.ReconcilePlatform(registration.PlatformIdentity(), time.Now())
	if err != nil {
		return err
	}
	if restored {
		log.Print("status data found under a different platform identity; probes and notifications are paused until an administrator resumes them")
	}
	boot := make([]byte, 16)
	if _, err := rand.Read(boot); err != nil {
		return err
	}
	listener, err := listenUnix(cfg.socket)
	if err != nil {
		return err
	}
	defer os.Remove(cfg.socket)
	handler := status.NewServer(store, cfg.registration, hex.EncodeToString(boot))
	server := &http.Server{Handler: handler, ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 20 * time.Second, WriteTimeout: 25 * time.Second, IdleTimeout: 30 * time.Second, MaxHeaderBytes: 32768}
	ctx, cancel := context.WithCancel(ctx)
	defer cancel()
	var workers sync.WaitGroup
	workers.Add(3)
	go func() {
		defer workers.Done()
		if err := store.Run(ctx, &status.Prober{Egress: status.NoEgress{}}); err != nil {
			log.Print("status scheduler stopped")
			cancel()
		}
	}()
	go func() { defer workers.Done(); store.PublishLoop(ctx, &status.Publisher{Egress: status.NoEgress{}}) }()
	go func() {
		defer workers.Done()
		ticker := time.NewTicker(time.Hour)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case now := <-ticker.C:
				if err := store.Cleanup(now); err != nil {
					log.Print("status retention pass failed")
				}
			}
		}
	}()
	stopped := make(chan struct{})
	go func() {
		<-ctx.Done()
		shutdown, done := context.WithTimeout(context.Background(), 30*time.Second)
		defer done()
		_ = server.Shutdown(shutdown)
		close(stopped)
	}()
	log.Printf("status %s serving on the platform socket", version)
	err = server.Serve(listener)
	cancel()
	<-stopped
	workers.Wait()
	if errors.Is(err, http.ErrServerClosed) {
		return nil
	}
	return err
}

func run() error {
	command := "serve"
	args := os.Args[1:]
	if len(args) > 0 && !strings.HasPrefix(args[0], "-") {
		command, args = args[0], args[1:]
	}
	flags := flag.NewFlagSet("status", flag.ContinueOnError)
	database := flags.String("database", defaultDatabase, "Status SQLite file in the application data volume")
	registration := flags.String("registration", status.DefaultRegistrationPath, "Platform backend registration file")
	if err := flags.Parse(args); err != nil {
		return err
	}
	if len(flags.Args()) != 0 {
		return errors.New("unexpected command arguments")
	}
	switch command {
	case "version":
		fmt.Println(version)
		return nil
	case "serve":
	default:
		return errors.New("command must be serve or version")
	}
	socket := os.Getenv("PORTAL_APP_HTTP_SOCKET")
	if socket == "" {
		socket = defaultSocketPath
	}
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()
	return serve(ctx, config{database: *database, registration: *registration, socket: socket})
}
func main() {
	if err := run(); err != nil {
		log.Fatal(err)
	}
}
