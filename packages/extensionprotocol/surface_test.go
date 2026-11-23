package extensionprotocol

import (
	"bytes"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"strings"
	"testing"
)

func decodeClaims(t *testing.T, token string) map[string]any {
	t.Helper()
	encoded, _, _ := strings.Cut(token, ".")
	raw, err := base64.RawURLEncoding.DecodeString(encoded)
	if err != nil {
		t.Fatal(err)
	}
	var out map[string]any
	if err := json.Unmarshal(raw, &out); err != nil {
		t.Fatal(err)
	}
	return out
}

func TestReaderAssertionCarriesNoSurface(t *testing.T) {
	s, v, now := fixture()
	token, err := s.Sign("GET", "/v1/components", nil, Viewer{Subject: "a", Role: "user"}, now)
	if err != nil {
		t.Fatal(err)
	}
	if _, present := decodeClaims(t, token)["surface"]; present {
		t.Fatal("reader assertion must keep its v1 byte shape without a surface field")
	}
	claims, err := v.Verify(token, "GET", "/v1/components", nil, now)
	if err != nil || claims.Admin() || claims.Surface != "" {
		t.Fatalf("claims=%+v err=%v", claims, err)
	}
}

func TestAdminAssertionVerifiesAsAdmin(t *testing.T) {
	s, v, now := fixture()
	body := []byte(`{"request_id":"r1"}`)
	token, err := s.SignAdmin("POST", "/v1/admin/jobs/a/run", body, Viewer{Subject: "a", Role: "user"}, now)
	if err != nil {
		t.Fatal(err)
	}
	if decodeClaims(t, token)["surface"] != SurfaceAdmin {
		t.Fatal("admin assertion must carry surface=admin")
	}
	claims, err := v.Verify(token, "POST", "/v1/admin/jobs/a/run", body, now)
	if err != nil || !claims.Admin() {
		t.Fatalf("claims=%+v err=%v", claims, err)
	}
}

// A verifier built before the surface claim existed decodes Claims strictly.
// It must refuse an admin assertion rather than read it as a reader request.
func TestPreSurfaceVerifierRefusesAdminAssertion(t *testing.T) {
	s, _, now := fixture()
	token, err := s.SignAdmin("GET", "/v1/admin/jobs", nil, Viewer{Subject: "a", Role: "user"}, now)
	if err != nil {
		t.Fatal(err)
	}
	encoded, _, _ := strings.Cut(token, ".")
	raw, _ := base64.RawURLEncoding.DecodeString(encoded)
	type legacyClaims struct {
		Version    int    `json:"v"`
		KeyID      string `json:"kid"`
		Issuer     string `json:"iss"`
		Audience   string `json:"aud"`
		AppID      string `json:"app"`
		InstanceID string `json:"instance"`
		BootID     string `json:"boot"`
		RequestID  string `json:"jti"`
		IssuedAt   int64  `json:"iat"`
		ExpiresAt  int64  `json:"exp"`
		Method     string `json:"method"`
		Path       string `json:"path"`
		BodyDigest string `json:"body_sha256"`
		Viewer     Viewer `json:"viewer"`
	}
	var c legacyClaims
	d := json.NewDecoder(bytes.NewReader(raw))
	d.DisallowUnknownFields()
	if d.Decode(&c) == nil {
		t.Fatal("a pre-surface strict decoder accepted an admin assertion")
	}
}

func TestUnknownSurfaceRefused(t *testing.T) {
	s, v, now := fixture()
	token, err := s.Sign("GET", "/v1/components", nil, Viewer{Subject: "a", Role: "user"}, now)
	if err != nil {
		t.Fatal(err)
	}
	claims := decodeClaims(t, token)
	claims["surface"] = "owner"
	raw, _ := json.Marshal(claims)
	encoded := base64.RawURLEncoding.EncodeToString(raw)
	mac := hmac.New(sha256.New, s.Key)
	mac.Write([]byte("rp-extension-v1\n"))
	mac.Write([]byte(encoded))
	forged := encoded + "." + base64.RawURLEncoding.EncodeToString(mac.Sum(nil))
	if _, err := v.Verify(forged, "GET", "/v1/components", nil, now); err == nil {
		t.Fatal("an unknown surface value was accepted")
	}
}

func TestSurfaceCannotBeStrippedWithoutKey(t *testing.T) {
	s, v, now := fixture()
	token, err := s.Sign("GET", "/v1/components", nil, Viewer{Subject: "a", Role: "user"}, now)
	if err != nil {
		t.Fatal(err)
	}
	encoded, sig, _ := strings.Cut(token, ".")
	claims := decodeClaims(t, token)
	claims["surface"] = SurfaceAdmin
	raw, _ := json.Marshal(claims)
	_ = encoded
	if _, err := v.Verify(base64.RawURLEncoding.EncodeToString(raw)+"."+sig, "GET", "/v1/components", nil, now); err == nil {
		t.Fatal("a reader assertion was promoted to admin without the key")
	}
}
