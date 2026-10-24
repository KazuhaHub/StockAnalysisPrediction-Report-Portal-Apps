package status

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"github.com/jackc/pgx/v5/pgproto3"
	"io"
	"net"
	"os"
	"path/filepath"
	"runtime"
	"sync/atomic"
	"testing"
	"time"
)

func TestPostgresLocalSocketConfiguration(t *testing.T) {
	for _, tc := range []struct {
		name, kind, config string
		valid              bool
	}{
		{"explicit socket", "postgres", `{"postgres_transport":"unix","port":5432,"database":"fixture"}`, true},
		{"explicit TLS", "postgres", `{"postgres_transport":"tls","host":"database.example","port":5432,"database":"fixture"}`, true},
		{"legacy TLS", "postgres", `{"host":"database.example","port":5432,"database":"fixture"}`, true},
		{"unknown transport", "postgres", `{"postgres_transport":"plaintext","host":"database.example","port":5432,"database":"fixture"}`, false},
		{"socket with hostname", "postgres", `{"postgres_transport":"unix","host":"database.example","port":5432,"database":"fixture"}`, false},
		{"socket with network allowance", "postgres", `{"postgres_transport":"unix","networks":["10.0.0.0/8"],"port":5432,"database":"fixture"}`, false},
		{"socket path injection", "postgres", `{"postgres_transport":"unix","socket_path":"/var/run/docker.sock","port":5432,"database":"fixture"}`, false},
		{"socket without port", "postgres", `{"postgres_transport":"unix","database":"fixture"}`, false},
		{"socket without database", "postgres", `{"postgres_transport":"unix","port":5432}`, false},
		{"socket with URL", "postgres", `{"postgres_transport":"unix","url":"https://database.example","port":5432,"database":"fixture"}`, false},
		{"unrelated monitor", "http", `{"postgres_transport":"unix","url":"https://example.com"}`, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			input := MonitorInput{Kind: tc.kind, Label: "Fixture", CredentialID: "fixture", IntervalSeconds: 60, TimeoutSeconds: 5, Config: json.RawMessage(tc.config)}
			if err := validateMonitor(&input); (err == nil) != tc.valid {
				t.Fatalf("validation error=%v, valid=%v", err, tc.valid)
			}
		})
	}
}

func socketTestDirectory(t *testing.T) string {
	t.Helper()
	directory, err := os.MkdirTemp("", "pg-unix-")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { os.RemoveAll(directory) })
	return directory
}

func TestPostgresLocalSocketQueryAndDeadlines(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("PostgreSQL local sockets require a Unix host")
	}
	for _, mode := range []string{"healthy", "stall_auth", "stall_query"} {
		t.Run(mode, func(t *testing.T) {
			directory := socketTestDirectory(t)
			listener, err := net.Listen("unix", filepath.Join(directory, ".s.PGSQL.5432"))
			if err != nil {
				t.Fatal(err)
			}
			t.Cleanup(func() { listener.Close() })
			done := make(chan error, 1)
			go func() {
				done <- func() error {
					wire, err := listener.Accept()
					if err != nil {
						return err
					}
					defer wire.Close()
					wire.SetDeadline(time.Now().Add(3 * time.Second))
					backend := pgproto3.NewBackend(wire, wire)
					startup, err := backend.ReceiveStartupMessage()
					if err != nil {
						return err
					}
					message, ok := startup.(*pgproto3.StartupMessage)
					if !ok || message.Parameters["user"] != "read_fixture" || message.Parameters["database"] != "fixture" || message.Parameters["default_transaction_read_only"] != "on" {
						return fmt.Errorf("unexpected local startup")
					}
					if mode == "stall_auth" {
						_, _ = io.Copy(io.Discard, wire)
						return nil
					}
					backend.Send(&pgproto3.AuthenticationOk{})
					backend.Send(&pgproto3.ParameterStatus{Name: "server_version", Value: "16.0"})
					backend.Send(&pgproto3.ReadyForQuery{TxStatus: 'I'})
					if err := backend.Flush(); err != nil {
						return err
					}
					var format int16
					for {
						message, err := backend.Receive()
						if err != nil {
							return err
						}
						switch message := message.(type) {
						case *pgproto3.Parse:
							if message.Query != "SELECT 1" {
								return fmt.Errorf("unexpected SQL operation")
							}
							if mode == "stall_query" {
								_, _ = io.Copy(io.Discard, wire)
								return nil
							}
							backend.Send(&pgproto3.ParseComplete{})
						case *pgproto3.Describe:
							backend.Send(&pgproto3.ParameterDescription{})
							backend.Send(&pgproto3.RowDescription{Fields: []pgproto3.FieldDescription{{Name: []byte("one"), DataTypeOID: 23, DataTypeSize: 4, TypeModifier: -1}}})
						case *pgproto3.Bind:
							if len(message.ResultFormatCodes) > 0 {
								format = message.ResultFormatCodes[0]
							}
							backend.Send(&pgproto3.BindComplete{})
						case *pgproto3.Execute:
							value := []byte("1")
							if format == 1 {
								value = []byte{0, 0, 0, 1}
							}
							backend.Send(&pgproto3.DataRow{Values: [][]byte{value}})
							backend.Send(&pgproto3.CommandComplete{CommandTag: []byte("SELECT 1")})
						case *pgproto3.Sync:
							backend.Send(&pgproto3.ReadyForQuery{TxStatus: 'I'})
						case *pgproto3.Terminate:
							return nil
						default:
							return fmt.Errorf("unexpected protocol operation %T", message)
						}
						if err := backend.Flush(); err != nil {
							return err
						}
					}
				}()
			}()
			m := Monitor{Config: ProbeConfig{PostgresTransport: "unix", Port: 5432, Database: "fixture"}, Secret: CredentialSecret{Username: "read_fixture", Password: "fixture-only"}}
			cfg, err := postgresSocketConfig(m, directory)
			if err != nil {
				t.Fatal(err)
			}
			if cfg.TLSConfig != nil || len(cfg.Fallbacks) != 0 || cfg.Host != directory {
				t.Fatal("local connection unexpectedly gained a network fallback")
			}
			dial := cfg.DialFunc
			var calls atomic.Int32
			cfg.DialFunc = func(ctx context.Context, network, address string) (net.Conn, error) {
				calls.Add(1)
				return dial(ctx, network, address)
			}
			timeout := time.Second
			if mode != "healthy" {
				timeout = 100 * time.Millisecond
			}
			ctx, cancel := context.WithTimeout(context.Background(), timeout)
			defer cancel()
			started := time.Now()
			result := postgresReadCheck(ctx, cfg)
			if mode == "healthy" {
				if result.Outcome != "success" || result.Measurements.Capability != "read_query_only" {
					t.Fatalf("local check=%+v", result)
				}
			} else if result.Outcome != "failure" || ctx.Err() == nil || time.Since(started) > time.Second {
				t.Fatalf("unbounded or successful stalled check=%+v", result)
			}
			if calls.Load() != 1 {
				t.Fatalf("unexpected dial count=%d", calls.Load())
			}
			select {
			case err := <-done:
				if err != nil {
					t.Fatal(err)
				}
			case <-time.After(time.Second):
				t.Fatal("local fixture socket did not close")
			}
		})
	}
}

func TestPostgresLocalSocketStaleInodeFailsWithoutFallback(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("PostgreSQL local sockets require a Unix host")
	}
	directory := socketTestDirectory(t)
	listener, err := net.ListenUnix("unix", &net.UnixAddr{Name: filepath.Join(directory, ".s.PGSQL.5432"), Net: "unix"})
	if err != nil {
		t.Fatal(err)
	}
	listener.SetUnlinkOnClose(false)
	listener.Close()
	m := Monitor{Config: ProbeConfig{PostgresTransport: "unix", Port: 5432, Database: "fixture"}}
	cfg, err := postgresSocketConfig(m, directory)
	if err != nil {
		t.Fatal(err)
	}
	dial := cfg.DialFunc
	var calls atomic.Int32
	cfg.DialFunc = func(ctx context.Context, network, address string) (net.Conn, error) {
		calls.Add(1)
		return dial(ctx, network, address)
	}
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	if result := postgresReadCheck(ctx, cfg); result.Outcome != "failure" || calls.Load() != 1 {
		t.Fatalf("stale inode became healthy or used a fallback: %+v, dials=%d", result, calls.Load())
	}
}

func TestPostgresLocalSocketRejectsAlternateDestinations(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("PostgreSQL local sockets require a Unix host")
	}
	directory := socketTestDirectory(t)
	path := filepath.Join(directory, ".s.PGSQL.5432")
	listener, err := net.Listen("unix", path)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { listener.Close() })
	m := Monitor{Config: ProbeConfig{PostgresTransport: "unix", Port: 5432, Database: "fixture"}}
	cfg, err := postgresSocketConfig(m, directory)
	if err != nil {
		t.Fatal(err)
	}
	for _, destination := range []struct{ network, address string }{{"tcp", "127.0.0.1:5432"}, {"unix", "/var/run/docker.sock"}, {"unix", filepath.Join(directory, ".s.PGSQL.5433")}} {
		if connection, err := cfg.DialFunc(context.Background(), destination.network, destination.address); !errors.Is(err, ErrInvalid) || connection != nil {
			t.Fatalf("alternate destination accepted: %v", err)
		}
	}
	if _, err := cfg.LookupFunc(context.Background(), "database.example"); !errors.Is(err, ErrInvalid) {
		t.Fatal("local transport attempted DNS")
	}
	listener.Close()
	if _, err := postgresSocketConfig(m, directory); err == nil {
		t.Fatal("missing socket accepted")
	}
	if err := os.WriteFile(path, []byte("not a socket"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := postgresSocketConfig(m, directory); err == nil {
		t.Fatal("regular file accepted")
	}
	if _, err := cfg.DialFunc(context.Background(), "unix", path); !errors.Is(err, ErrInvalid) {
		t.Fatal("replacement file accepted at dial")
	}
	os.Remove(path)
	if err := os.Symlink("/var/run/docker.sock", path); err != nil {
		t.Fatal(err)
	}
	if _, err := postgresSocketConfig(m, directory); err == nil {
		t.Fatal("symlinked socket accepted")
	}
	link := filepath.Join(socketTestDirectory(t), "socket-root")
	if err := os.Symlink(directory, link); err != nil {
		t.Fatal(err)
	}
	if _, err := postgresSocketConfig(m, link); err == nil {
		t.Fatal("symlinked directory accepted")
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := cfg.DialFunc(ctx, "unix", path); !errors.Is(err, context.Canceled) {
		t.Fatal("cancelled dial ignored its context")
	}
}
