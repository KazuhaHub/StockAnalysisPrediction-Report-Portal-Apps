package status

import (
	"context"
	"net"
	"net/http"
	"net/http/httptest"
	"net/netip"
	"net/url"
	"strconv"
	"sync/atomic"
	"testing"
	"time"
)

func TestProbeRechecksAllDNSAnswersBeforeEveryConnection(t *testing.T) {
	config := ProbeConfig{URL: "https://service.example", Networks: []netip.Prefix{netip.MustParsePrefix("10.42.0.0/16")}}
	guard, err := newProbeTransport(config)
	if err != nil {
		t.Fatal(err)
	}
	lookups, dials := 0, 0
	guard.lookup = func(context.Context, string) ([]netip.Addr, error) {
		lookups++
		if lookups == 1 {
			return []netip.Addr{netip.MustParseAddr("10.42.0.8")}, nil
		}
		return []netip.Addr{netip.MustParseAddr("10.42.0.8"), netip.MustParseAddr("169.254.169.254")}, nil
	}
	guard.dial = func(context.Context, string, string) (net.Conn, error) {
		dials++
		a, b := net.Pipe()
		b.Close()
		return a, nil
	}
	conn, err := guard.dialContext(context.Background(), "tcp", "service.example:443")
	if err != nil {
		t.Fatal(err)
	}
	conn.Close()
	if conn, err := guard.dialContext(context.Background(), "tcp", "service.example:443"); err == nil {
		conn.Close()
		t.Fatal("rebound mixed answer reached the dialer")
	}
	if lookups != 2 || dials != 1 {
		t.Fatalf("lookup/dial counts=%d/%d", lookups, dials)
	}
	for _, address := range []string{"other.example:443", "service.example:8443"} {
		if conn, err := guard.dialContext(context.Background(), "tcp", address); err == nil {
			conn.Close()
			t.Fatal("configured destination changed")
		}
	}
	if dials != 1 {
		t.Fatal("invalid destination opened a connection")
	}
}

// Only the fixture socket is substituted. The client retains production
// redirect, timeout, response bounds and guarded-address policy.
func fixtureProbeClient(t *testing.T, server *httptest.Server) (*Prober, ProbeConfig) {
	t.Helper()
	endpoint, err := url.Parse(server.URL)
	if err != nil {
		t.Fatal(err)
	}
	config := ProbeConfig{URL: "http://10.42.0.8:" + endpoint.Port(), PlainHTTP: true, Networks: []netip.Prefix{netip.MustParsePrefix("10.42.0.0/16")}}
	client, err := (&Prober{}).client(config)
	if err != nil {
		t.Fatal(err)
	}
	guard, err := newProbeTransport(config)
	if err != nil {
		t.Fatal(err)
	}
	guard.lookup = func(context.Context, string) ([]netip.Addr, error) {
		return []netip.Addr{netip.MustParseAddr("10.42.0.8")}, nil
	}
	guard.dial = func(ctx context.Context, network, address string) (net.Conn, error) {
		if address != net.JoinHostPort("10.42.0.8", endpoint.Port()) {
			t.Error("fixture dial escaped its fixed destination")
		}
		return (&net.Dialer{}).DialContext(ctx, network, endpoint.Host)
	}
	client.Transport.(*http.Transport).DialContext = guard.dialContext
	t.Cleanup(client.CloseIdleConnections)
	return &Prober{clientForTest: func(ProbeConfig) (*http.Client, error) { return client, nil }}, config
}

func TestHTTPProbeRefusesSameTargetRedirectWithoutForwardingCredentials(t *testing.T) {
	var requests atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requests.Add(1)
		if r.URL.Path != "/" || r.Header.Get("Authorization") != "Bearer fixture-only" {
			t.Error("probe followed a redirect or lost its initial credential")
		}
		w.Header().Set("Location", "/credential-target")
		w.WriteHeader(http.StatusFound)
	}))
	defer server.Close()
	prober, config := fixtureProbeClient(t, server)
	result := prober.Check(context.Background(), Monitor{Kind: "http", Config: config, Secret: CredentialSecret{APIKey: "fixture-only"}})
	if result.Outcome != "unknown" || result.ReasonCode != "redirect_refused" || requests.Load() != 1 {
		t.Fatalf("redirect result=%+v requests=%d", result, requests.Load())
	}
}

func TestHTTPProbeTimeoutBoundsHeadersAndBody(t *testing.T) {
	for _, bodyStarted := range []bool{false, true} {
		t.Run(strconv.FormatBool(bodyStarted), func(t *testing.T) {
			var entered atomic.Bool
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				entered.Store(true)
				if bodyStarted {
					w.WriteHeader(200)
					w.(http.Flusher).Flush()
				}
				<-r.Context().Done()
			}))
			defer server.Close()
			prober, config := fixtureProbeClient(t, server)
			ctx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
			defer cancel()
			started := time.Now()
			result := prober.Check(ctx, Monitor{Kind: "http", Config: config})
			if elapsed := time.Since(started); elapsed > time.Second {
				t.Fatalf("probe exceeded caller deadline: %s", elapsed)
			}
			if ctx.Err() == nil {
				t.Fatal("timeout drill returned before its deadline")
			}
			if !entered.Load() {
				t.Fatal("timeout fixture never received the request")
			}
			if result.Outcome == "success" || result.Outcome == "degraded" || len(result.Measurements.Balances) != 0 {
				t.Fatalf("timeout fabricated healthy or financial evidence: %+v", result)
			}
		})
	}
}
