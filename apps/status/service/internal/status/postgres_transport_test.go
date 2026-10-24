package status

import (
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"crypto/tls"
	"crypto/x509"
	"encoding/binary"
	"fmt"
	"github.com/jackc/pgx/v5/pgproto3"
	"io"
	"math/big"
	"net"
	"net/netip"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func TestPostgresResolutionStaysBoundToConfiguredHost(t *testing.T) {
	m := Monitor{Config: ProbeConfig{Host: "database.example", Port: 5432}}
	guard, err := newProbeTransport(ProbeConfig{URL: "https://database.example:5432"})
	if err != nil {
		t.Fatal(err)
	}
	cfg, err := postgresProbeConfig(m, guard)
	if err != nil {
		t.Fatal(err)
	}
	if addresses, err := cfg.LookupFunc(context.Background(), "198.51.100.11"); err == nil {
		t.Fatalf("driver bypassed the configured hostname with %v", addresses)
	}
}

type observedCloseConn struct {
	net.Conn
	closed chan struct{}
	once   sync.Once
}

func (c *observedCloseConn) Close() error {
	c.once.Do(func() { close(c.closed) })
	return c.Conn.Close()
}

// The driver speaks its real SSL negotiation and extended query protocol over
// an in-memory connection; no system DNS, database or provider account is used.
func postgresFixture(t *testing.T, mode string) (*probeTransport, *x509.CertPool, <-chan error, *atomic.Int32, *atomic.Int32) {
	t.Helper()
	public, private, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	dnsName := "database.example"
	if mode == "wrong_name" {
		dnsName = "other.example"
	}
	template := &x509.Certificate{SerialNumber: big.NewInt(1), DNSNames: []string{dnsName}, NotBefore: time.Now().Add(-time.Hour), NotAfter: time.Now().Add(time.Hour), IsCA: true, BasicConstraintsValid: true, KeyUsage: x509.KeyUsageCertSign | x509.KeyUsageDigitalSignature, ExtKeyUsage: []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth}}
	der, err := x509.CreateCertificate(rand.Reader, template, template, public, private)
	if err != nil {
		t.Fatal(err)
	}
	certificate := tls.Certificate{Certificate: [][]byte{der}, PrivateKey: private}
	parsed, err := x509.ParseCertificate(der)
	if err != nil {
		t.Fatal(err)
	}
	roots := x509.NewCertPool()
	roots.AddCert(parsed)
	guard, err := newProbeTransport(ProbeConfig{URL: "https://database.example:5432", Networks: []netip.Prefix{netip.MustParsePrefix("10.42.0.0/16")}})
	if err != nil {
		t.Fatal(err)
	}
	guard.lookup = func(ctx context.Context, host string) ([]netip.Addr, error) {
		if host != "database.example" {
			return nil, fmt.Errorf("unexpected lookup host")
		}
		return []netip.Addr{netip.MustParseAddr("10.42.0.8")}, nil
	}
	completed := make(chan error, 4)
	calls, startups := &atomic.Int32{}, &atomic.Int32{}
	guard.dial = func(ctx context.Context, network, address string) (net.Conn, error) {
		calls.Add(1)
		if network != "tcp" || address != "10.42.0.8:5432" {
			return nil, fmt.Errorf("dial escaped pinned address")
		}
		client, server := net.Pipe()
		closed := make(chan struct{})
		client = &observedCloseConn{Conn: client, closed: closed}
		t.Cleanup(func() { client.Close(); server.Close() })
		go func() {
			defer server.Close()
			server.SetDeadline(time.Now().Add(3 * time.Second))
			completed <- func() error {
				header := make([]byte, 8)
				if _, err := io.ReadFull(server, header); err != nil {
					return err
				}
				if binary.BigEndian.Uint32(header[:4]) != 8 || binary.BigEndian.Uint32(header[4:]) != 80877103 {
					return fmt.Errorf("client did not request PostgreSQL TLS")
				}
				if mode == "stall_tls" {
					_, _ = io.Copy(io.Discard, server)
					return nil
				}
				if mode == "no_tls" {
					if _, err := server.Write([]byte("N")); err != nil {
						return err
					}
					n, _ := server.Read(make([]byte, 512))
					if n != 0 {
						return fmt.Errorf("client sent plaintext startup after TLS refusal")
					}
					return nil
				}
				if _, err := server.Write([]byte("S")); err != nil {
					return err
				}
				secure := tls.Server(server, &tls.Config{Certificates: []tls.Certificate{certificate}, MinVersion: tls.VersionTLS12})
				if err := secure.Handshake(); err != nil {
					if mode == "wrong_name" || mode == "untrusted" {
						return nil
					}
					return err
				}
				backend := pgproto3.NewBackend(secure, secure)
				startup, err := backend.ReceiveStartupMessage()
				if err != nil {
					return err
				}
				if _, ok := startup.(*pgproto3.StartupMessage); !ok {
					return fmt.Errorf("unexpected startup message")
				}
				startups.Add(1)
				if mode == "stall_auth" {
					<-closed
					return nil
				}
				backend.Send(&pgproto3.AuthenticationOk{})
				backend.Send(&pgproto3.ParameterStatus{Name: "server_version", Value: "16.0"})
				backend.Send(&pgproto3.ReadyForQuery{TxStatus: 'I'})
				if err := backend.Flush(); err != nil {
					return err
				}
				var format int16
				var executed bool
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
							_, _ = io.Copy(io.Discard, secure)
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
						executed = true
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
						return fmt.Errorf("unexpected driver operation %T", message)
					}
					if err := backend.Flush(); err != nil {
						return err
					}
					if _, synced := message.(*pgproto3.Sync); synced && executed && mode == "stall_close" {
						<-closed
						return nil
					}
				}
			}()
		}()
		return client, nil
	}
	return guard, roots, completed, calls, startups
}

func TestPostgresGuardedDriverTLSAndTimeouts(t *testing.T) {
	for _, mode := range []string{"healthy", "no_tls", "untrusted", "wrong_name", "stall_tls", "stall_auth", "stall_query", "stall_close"} {
		t.Run(mode, func(t *testing.T) {
			guard, roots, completed, calls, startups := postgresFixture(t, mode)
			m := Monitor{Config: ProbeConfig{Host: "database.example", Port: 5432, Database: "fixture"}, Secret: CredentialSecret{Username: "read_fixture", Password: "fixture-secret"}}
			cfg, err := postgresProbeConfig(m, guard)
			if err != nil {
				t.Fatal(err)
			}
			if mode != "untrusted" {
				cfg.TLSConfig.RootCAs = roots
			} else {
				cfg.TLSConfig.RootCAs = x509.NewCertPool()
			}
			if cfg.TLSConfig.InsecureSkipVerify || cfg.TLSConfig.ServerName != "database.example" || len(cfg.Fallbacks) != 0 {
				t.Fatal("TLS identity or plaintext fallback policy changed")
			}
			timeout := 2 * time.Second
			if strings.HasPrefix(mode, "stall_") {
				timeout = 100 * time.Millisecond
			}
			ctx, cancel := context.WithTimeout(context.Background(), timeout)
			defer cancel()
			started := time.Now()
			result := postgresReadCheck(ctx, cfg)
			if elapsed := time.Since(started); elapsed > time.Second && strings.HasPrefix(mode, "stall_") {
				t.Fatalf("probe exceeded its timeout: %s", elapsed)
			}
			if strings.HasPrefix(mode, "stall_") && ctx.Err() == nil {
				t.Fatal("stall returned before the caller deadline")
			}
			if mode == "healthy" || mode == "stall_close" {
				if result.Outcome != "success" || result.Measurements.Capability != "read_query_only" {
					t.Fatalf("guarded hostname query=%+v", result)
				}
			} else if result.Outcome != "failure" {
				t.Fatalf("failed TLS/timeout became healthy: %+v", result)
			}
			if calls.Load() != 1 {
				t.Fatalf("unexpected fallback/reconnect count %d", calls.Load())
			}
			if (mode == "no_tls" || mode == "untrusted" || mode == "wrong_name") && startups.Load() != 0 {
				t.Fatal("database startup reached an unverified peer")
			}
			select {
			case err := <-completed:
				if err != nil {
					t.Fatal(err)
				}
			case <-time.After(time.Second):
				t.Fatal("fixture connection did not close")
			}
		})
	}
}
