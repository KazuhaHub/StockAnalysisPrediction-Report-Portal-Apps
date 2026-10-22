package main

import (
	"context"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/apps/status/service/internal/status"
	protocol "github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/extensionprotocol"
)

var version = "0.1.0-dev"

type pairing struct {
	Issuer     string `json:"issuer"`
	Audience   string `json:"audience"`
	AppID      string `json:"app_id"`
	InstanceID string `json:"instance_id"`
	KeyID      string `json:"key_id"`
	SigningKey []byte `json:"signing_key"`
}

func readSecret(path string) ([]byte, error) {
	info, err := os.Stat(path)
	if err != nil || !info.Mode().IsRegular() || info.Size() > 16384 {
		return nil, errors.New("secret file is missing, oversized or not regular")
	}
	if info.Mode().Perm()&0077 != 0 {
		return nil, errors.New("secret file must be readable only by its owner")
	}
	return os.ReadFile(path)
}
func run() error {
	command := "serve"
	args := os.Args[1:]
	if len(args) > 0 && !strings.HasPrefix(args[0], "-") {
		command, args = args[0], args[1:]
	}
	flags := flag.NewFlagSet("status", flag.ContinueOnError)
	database := flags.String("database", "data/status.db", "Independent Status SQLite file")
	storageKey := flags.String("storage-key-file", "", "File containing a base64-encoded 32-byte storage key (owner-only permissions)")
	pairFile := flags.String("pairing-file", "", "Owner-only JSON file with Portal registration pins and signing key")
	listen := flags.String("listen", ":8791", "HTTP listen address behind the trusted gateway")
	file := flags.String("file", "", "Backup input/output or key generation destination")
	if err := flags.Parse(args); err != nil {
		return err
	}
	if len(flags.Args()) != 0 {
		return errors.New("unexpected command arguments")
	}
	if command == "version" {
		fmt.Println(version)
		return nil
	}
	if command == "keygen" {
		if *file == "" {
			return errors.New("keygen requires -file")
		}
		key := make([]byte, 32)
		if _, err := rand.Read(key); err != nil {
			return err
		}
		out, err := os.OpenFile(*file, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
		if err != nil {
			return err
		}
		_, err = out.WriteString(base64.StdEncoding.EncodeToString(key) + "\n")
		closeErr := out.Close()
		if err != nil {
			return err
		}
		return closeErr
	}
	if command != "serve" && command != "backup" && command != "restore" {
		return errors.New("command must be serve, backup, restore, keygen or version")
	}
	raw, err := readSecret(*storageKey)
	if err != nil {
		return err
	}
	key, err := base64.StdEncoding.Strict().DecodeString(strings.TrimSpace(string(raw)))
	if err != nil || len(key) != 32 {
		return errors.New("storage key must encode exactly 32 bytes")
	}
	store, err := status.Open(*database, key)
	if err != nil {
		return err
	}
	defer store.Close()
	if command == "backup" {
		if *file == "" {
			return errors.New("backup requires -file")
		}
		return store.Backup(*file)
	}
	if command == "restore" {
		if *file == "" {
			return errors.New("restore requires -file")
		}
		return store.Restore(*file)
	}
	raw, err = readSecret(*pairFile)
	if err != nil {
		return err
	}
	var pair pairing
	decoder := json.NewDecoder(strings.NewReader(string(raw)))
	decoder.DisallowUnknownFields()
	if decoder.Decode(&pair) != nil {
		return errors.New("invalid pairing file")
	}
	signer := protocol.Signer{Issuer: pair.Issuer, Audience: pair.Audience, AppID: pair.AppID, InstanceID: pair.InstanceID, KeyID: pair.KeyID, Key: pair.SigningKey}
	if pair.AppID != "status" {
		return errors.New("pairing must name the status application")
	}
	handler, err := status.NewServer(store, signer)
	if err != nil {
		return err
	}
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()
	server := &http.Server{Addr: *listen, Handler: handler, ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 20 * time.Second, WriteTimeout: 25 * time.Second, IdleTimeout: 30 * time.Second, MaxHeaderBytes: 32768}
	var workers sync.WaitGroup
	workers.Add(3)
	go func() {
		defer workers.Done()
		if err := store.Run(ctx, &status.Prober{}); err != nil {
			log.Print("status scheduler stopped")
			cancel()
		}
	}()
	go func() { defer workers.Done(); store.PublishLoop(ctx, &status.Publisher{}) }()
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
	log.Printf("status %s listening on %s", version, *listen)
	err = server.ListenAndServe()
	cancel()
	<-stopped
	workers.Wait()
	if errors.Is(err, http.ErrServerClosed) {
		return nil
	}
	return err
}
func main() {
	if err := run(); err != nil {
		log.Fatal(err)
	}
}
