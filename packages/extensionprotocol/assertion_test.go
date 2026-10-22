package extensionprotocol

import (
	"bytes"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func fixture() (Signer, *Verifier, time.Time) {
	key := bytes.Repeat([]byte{23}, 32)
	now := time.Date(2026, 10, 22, 0, 0, 0, 0, time.UTC)
	return Signer{Issuer: "portal-test", Audience: "status-test", AppID: "status", InstanceID: "registration-1", KeyID: "current", Key: key}, NewVerifier(VerifyConfig{Issuer: "portal-test", Audience: "status-test", AppID: "status", InstanceID: "registration-1", Keys: map[string][]byte{"current": key}, ReplayCapacity: 4}), now
}

func TestRequestBoundIdentityAndOUClaims(t *testing.T) {
	s, v, now := fixture()
	viewer := Viewer{Subject: "account-1", SessionRevision: 3, Role: "user", OUs: []string{"ou:root-generation", "ou:team-generation"}}
	token, err := s.Sign("GET", "/v1/components?limit=10", nil, viewer, now)
	if err != nil {
		t.Fatal(err)
	}
	claims, err := v.Verify(token, "GET", "/v1/components?limit=10", nil, now)
	if err != nil || claims.Viewer.Subject != viewer.Subject || len(claims.Viewer.OUs) != 2 {
		t.Fatalf("claims=%+v err=%v", claims, err)
	}
	if _, err = v.Verify(token, "GET", "/v1/components?limit=10", nil, now); err == nil {
		t.Fatal("replay accepted")
	}
}

func TestAssertionRejectsWrongBoundary(t *testing.T) {
	for _, mode := range []string{"method", "path", "body", "expired", "future", "audience", "app", "instance", "signature", "subject", "bad-key"} {
		t.Run(mode, func(t *testing.T) {
			s, v, now := fixture()
			viewer := Viewer{Subject: "account-1", Role: "admin"}
			if mode == "subject" {
				viewer.Subject = ""
			}
			if mode == "bad-key" {
				s.Key = []byte("short")
			}
			if mode == "audience" {
				s.Audience = "other"
			}
			if mode == "app" {
				s.AppID = "other"
			}
			if mode == "instance" {
				s.InstanceID = "other"
			}
			token, err := s.Sign("GET", "/v1/components", nil, viewer, now)
			if mode == "subject" || mode == "bad-key" {
				if err == nil {
					t.Fatal("invalid signing input accepted")
				}
				return
			}
			if err != nil {
				t.Fatal(err)
			}
			method, path, body := "GET", "/v1/components", []byte(nil)
			when := now
			switch mode {
			case "method":
				method = "POST"
			case "path":
				path = "/v1/components?limit=100"
			case "body":
				body = []byte("changed")
			case "expired":
				when = now.Add(31 * time.Second)
			case "future":
				when = now.Add(-6 * time.Second)
			case "signature":
				token = token[:len(token)-1] + "!"
			}
			if _, err := v.Verify(token, method, path, body, when); err == nil {
				t.Fatal("invalid boundary accepted")
			}
		})
	}
}

func TestReplayConcurrentAndCapacityFailsClosed(t *testing.T) {
	s, v, now := fixture()
	token, err := s.Sign("GET", "/v1/components", nil, Viewer{Subject: "user", Role: "user"}, now)
	if err != nil {
		t.Fatal(err)
	}
	var accepted atomic.Int32
	var wg sync.WaitGroup
	for range 20 {
		wg.Go(func() {
			if _, err := v.Verify(token, "GET", "/v1/components", nil, now); err == nil {
				accepted.Add(1)
			}
		})
	}
	wg.Wait()
	if accepted.Load() != 1 {
		t.Fatalf("accepted %d replays", accepted.Load())
	}
	for range 3 {
		tok, _ := s.Sign("GET", "/v1/components", nil, Viewer{Subject: "user", Role: "user"}, now)
		if _, err := v.Verify(tok, "GET", "/v1/components", nil, now); err != nil {
			t.Fatal(err)
		}
	}
	tok, _ := s.Sign("GET", "/v1/components", nil, Viewer{Subject: "user", Role: "user"}, now)
	if _, err := v.Verify(tok, "GET", "/v1/components", nil, now); err == nil {
		t.Fatal("capacity silently evicted live replay record")
	}
	tok, _ = s.Sign("GET", "/v1/components", nil, Viewer{Subject: "user", Role: "user"}, now.Add(time.Minute))
	if _, err := v.Verify(tok, "GET", "/v1/components", nil, now.Add(time.Minute)); err != nil {
		t.Fatal("expired records did not release capacity")
	}
}

func TestMalformedAssertionsBounded(t *testing.T) {
	_, v, now := fixture()
	for _, token := range []string{"", "a.b.c", "invalid.invalid", strings.Repeat("x", 32769)} {
		if _, err := v.Verify(token, "GET", "/v1/components", nil, now); err == nil {
			t.Fatal("malformed token accepted")
		}
	}
}
