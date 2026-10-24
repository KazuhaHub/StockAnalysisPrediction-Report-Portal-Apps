package extensionprotocol

import (
	"context"
	"encoding/json"
	"net"
	"net/http"
	"net/http/httptest"
	"net/netip"
	"strings"
	"testing"
	"time"
)

func TestHandshakeUsesPinnedTransportAndBindsFreshBoot(t *testing.T) {
	now := time.Now()
	s := Signer{Issuer: "portal", Audience: "status", AppID: "status", InstanceID: "one", KeyID: "key", Key: []byte(strings.Repeat("k", 32))}
	boot := "first-boot"
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/handshake" || r.Method != "POST" || r.Header.Get(Header) != "" || r.Header.Get("Cookie") != "" {
			t.Error("unexpected handshake authority")
		}
		var in struct {
			Challenge string `json:"challenge"`
		}
		json.NewDecoder(r.Body).Decode(&in)
		answer, err := s.AnswerChallenge(in.Challenge, boot, now)
		if err != nil {
			w.WriteHeader(401)
			w.Header().Set("Content-Type", "application/json")
			return
		}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]string{"answer": answer})
	}))
	defer srv.Close()
	c, err := NewBackendClient("http://backend.invalid", Policy{Ports: []uint16{80}, PlainHTTP: true, Networks: []netip.Prefix{netip.MustParsePrefix("10.0.0.0/8")}, Routes: []Route{{Method: "GET", Prefix: "/v1/components"}}})
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	c.lookup = func(context.Context, string) ([]netip.Addr, error) {
		return []netip.Addr{netip.MustParseAddr("10.0.0.2")}, nil
	}
	c.dial = func(ctx context.Context, n, a string) (net.Conn, error) {
		return (&net.Dialer{}).DialContext(ctx, n, strings.TrimPrefix(srv.URL, "http://"))
	}
	got, err := c.Handshake(context.Background(), s, now)
	if err != nil || got != boot {
		t.Fatalf("boot=%q err=%v", got, err)
	}
	boot = "second-boot"
	got, err = c.Handshake(context.Background(), s, now)
	if err != nil || got != boot {
		t.Fatalf("stale boot=%q err=%v", got, err)
	}
	wrong := s
	wrong.InstanceID = "different"
	if _, err := c.Handshake(context.Background(), wrong, now); err == nil {
		t.Fatal("foreign registration paired")
	}
}
