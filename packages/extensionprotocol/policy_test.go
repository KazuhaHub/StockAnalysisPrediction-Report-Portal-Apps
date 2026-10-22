package extensionprotocol

import (
	"context"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"net/netip"
	"strings"
	"testing"
)

func TestRoutePolicyUsesSegmentBoundaryAndDenyTraversal(t *testing.T) {
	p := Policy{Routes: []Route{{Method: "GET", Prefix: "/v1/components"}}}
	for _, path := range []string{"/v1/components", "/v1/components/one", "/v1/components?limit=10"} {
		if !p.Allows("GET", path) {
			t.Fatalf("denied %s", path)
		}
	}
	for _, path := range []string{"/v1/components-secret", "/v1/%2e%2e/admin", "/v1/components/../secrets", "/v1/components/%252e%252e/admin", "//evil/v1/components", "https://evil/v1/components"} {
		if p.Allows("GET", path) {
			t.Fatalf("accepted %s", path)
		}
	}
	if p.Allows("DELETE", "/v1/components") {
		t.Fatal("write inherited read rule")
	}
}

func TestDestinationRequiresExplicitPrivatePolicy(t *testing.T) {
	p := Policy{Routes: []Route{{Method: "GET", Prefix: "/v1/components"}}, Ports: []uint16{443}, Networks: []netip.Prefix{netip.MustParsePrefix("10.2.0.0/16")}}
	for _, ip := range []string{"127.0.0.1", "169.254.169.254", "::1", "fe80::1", "0.0.0.0", "100.64.0.1", "10.3.0.1", "::ffff:127.0.0.1", "64:ff9b::a9fe:a9fe", "2002:7f00:1::", "2001::1"} {
		if p.AllowsIP(netip.MustParseAddr(ip)) {
			t.Fatalf("accepted %s", ip)
		}
	}
	for _, ip := range []string{"10.2.0.8", "8.8.8.8"} {
		if !p.AllowsIP(netip.MustParseAddr(ip)) {
			t.Fatalf("denied %s", ip)
		}
	}
	if _, err := NewBackendClient("http://backend.invalid", p); err == nil {
		t.Fatal("plaintext accepted without explicit policy")
	}
	if _, err := NewBackendClient("https://user:secret@backend.invalid", p); err == nil {
		t.Fatal("userinfo accepted")
	}
	if _, err := NewBackendClient("https://backend.invalid:444", p); err == nil {
		t.Fatal("unapproved port accepted")
	}
}

func TestDialValidatesEveryDNSAnswer(t *testing.T) {
	p := Policy{Ports: []uint16{443}, Routes: []Route{{Method: "GET", Prefix: "/v1/components"}}}
	c, err := NewBackendClient("https://backend.invalid", p)
	if err != nil {
		t.Fatal(err)
	}
	c.lookup = func(context.Context, string) ([]netip.Addr, error) {
		return []netip.Addr{netip.MustParseAddr("8.8.8.8"), netip.MustParseAddr("127.0.0.1")}, nil
	}
	called := false
	c.dial = func(context.Context, string, string) (net.Conn, error) { called = true; return nil, ErrInvalid }
	if _, err = c.dialContext(context.Background(), "tcp", "backend.invalid:443"); err == nil || called {
		t.Fatal("mixed DNS bypassed pinning")
	}
	c.lookup = func(context.Context, string) ([]netip.Addr, error) {
		return []netip.Addr{netip.MustParseAddr("8.8.8.8")}, nil
	}
	c.dial = func(_ context.Context, network, address string) (net.Conn, error) {
		if address != "8.8.8.8:443" {
			t.Fatalf("unbound dial %s", address)
		}
		called = true
		return nil, ErrInvalid
	}
	_, _ = c.dialContext(context.Background(), "tcp", "backend.invalid:443")
	if !called {
		t.Fatal("validated address not dialled")
	}
}

func TestBackendRefusesRedirectAndBoundsJSON(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/v1/components/redirect":
			w.Header().Set("Location", "http://169.254.169.254/latest")
			w.WriteHeader(302)
		case "/v1/components/malformed":
			w.Header().Set("Content-Type", "application/json")
			io.WriteString(w, "not-json")
		case "/v1/components/large":
			w.Header().Set("Content-Type", "application/json")
			io.WriteString(w, strings.Repeat("x", 1048577))
		default:
			w.Header().Set("Content-Type", "application/json")
			io.WriteString(w, `{"ok":true}`)
		}
	}))
	defer upstream.Close()
	p := Policy{Ports: []uint16{80}, PlainHTTP: true, Networks: []netip.Prefix{netip.MustParsePrefix("10.0.0.0/8")}, Routes: []Route{{Method: "GET", Prefix: "/v1/components"}}}
	c, err := NewBackendClient("http://backend.invalid", p)
	if err != nil {
		t.Fatal(err)
	}
	c.lookup = func(context.Context, string) ([]netip.Addr, error) {
		return []netip.Addr{netip.MustParseAddr("10.0.0.2")}, nil
	}
	c.dial = func(ctx context.Context, network, address string) (net.Conn, error) {
		return (&net.Dialer{}).DialContext(ctx, network, strings.TrimPrefix(upstream.URL, "http://"))
	}
	for _, path := range []string{"/v1/components/redirect", "/v1/components/large", "/v1/components/malformed"} {
		if _, err := c.Do(context.Background(), "GET", path, nil, "signed"); err == nil {
			t.Fatalf("unsafe response accepted %s", path)
		}
	}
	result, err := c.Do(context.Background(), "GET", "/v1/components", nil, "signed")
	if err != nil || string(result.Body) != `{"ok":true}` {
		t.Fatalf("result=%+v err=%v", result, err)
	}
}
