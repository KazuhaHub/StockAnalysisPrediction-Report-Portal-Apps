package status

import (
	"bytes"
	"fmt"
	protocol "github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/extensionprotocol"
	"net"
	"net/http/httptest"
	"net/netip"
	"testing"
	"time"
)

func TestAnonymousBurstIsBoundedWithoutTrustingForwardedHeaders(t *testing.T) {
	server, err := NewServer(testStore(t), protocol.Signer{Issuer: "portal", Audience: "status", AppID: "status", InstanceID: "registration", KeyID: "key", Key: bytes.Repeat([]byte{8}, 32)})
	if err != nil {
		t.Fatal(err)
	}
	limited := 0
	for i := 0; i < 100; i++ {
		request := httptest.NewRequest("GET", "/public/v1/status", nil)
		request.RemoteAddr = "192.0.2.10:45000"
		request.Header.Set("X-Forwarded-For", newID())
		response := httptest.NewRecorder()
		server.ServeHTTP(response, request)
		if response.Code == 429 {
			limited++
			if response.Header().Get("Retry-After") == "" {
				t.Fatal("missing retry guidance")
			}
		}
	}
	if limited == 0 {
		t.Fatal("anonymous burst was unbounded")
	}
	private := httptest.NewRecorder()
	server.ServeHTTP(private, httptest.NewRequest("GET", "/v1/components", nil))
	if private.Code != 401 {
		t.Fatalf("anonymous budget interfered with private auth: %d", private.Code)
	}
	other := httptest.NewRequest("GET", "/public/v1/status", nil)
	other.RemoteAddr = "192.0.2.11:45000"
	response := httptest.NewRecorder()
	server.ServeHTTP(response, other)
	if response.Code != 200 {
		t.Fatalf("independent origin blocked: %d", response.Code)
	}
}

func TestPublicBudgetExpiresOriginsAndBoundsGlobalWork(t *testing.T) {
	var budget publicBudget
	now := time.Now()
	rejected := 0
	for i := 0; i < 100; i++ {
		if !budget.allow(fmt.Sprintf("192.0.2.%d:4000", i), now) {
			rejected++
		}
	}
	if rejected < 20 {
		t.Fatalf("global burst exceeded bound: rejected=%d", rejected)
	}
	var crowded publicBudget
	address := netip.MustParseAddr("2001:db8::1")
	for i := 0; i < 1024; i++ {
		crowded.allow(net.JoinHostPort(address.String(), "4000"), now)
		address = address.Next()
	}
	if crowded.allow(net.JoinHostPort(address.String(), "4000"), now) {
		t.Fatal("origin registry exceeded hard bound")
	}
	if !crowded.allow(net.JoinHostPort(address.String(), "4000"), now.Add(61*time.Second)) {
		t.Fatal("idle origins were never evicted")
	}
	if len(crowded.origins) > 1024 {
		t.Fatal("unbounded public origin registry")
	}
}
