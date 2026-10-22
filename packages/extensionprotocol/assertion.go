// Package extensionprotocol defines request-bound identity assertions between a
// trusted Portal host and an independently deployed application backend.
package extensionprotocol

import (
	"bytes"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"net/url"
	"strings"
	"sync"
	"time"
)

const Header = "X-Portal-Assertion"
const Lifetime = 30 * time.Second
const maxToken = 32768

var ErrInvalid = errors.New("invalid extension assertion")
var ErrCapacity = errors.New("extension assertion replay capacity unavailable")

type Viewer struct {
	Subject         string   `json:"sub"`
	SessionRevision int64    `json:"session_revision"`
	Role            string   `json:"role"`
	OUs             []string `json:"ous"`
}

type Claims struct {
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

type Signer struct {
	Issuer, Audience, AppID, InstanceID, BootID, KeyID string
	Key                                                []byte
}

type VerifyConfig struct {
	Issuer, Audience, AppID, InstanceID, BootID string
	Keys                                        map[string][]byte
	ReplayCapacity                              int
}

type Verifier struct {
	config VerifyConfig
	mu     sync.Mutex
	seen   map[string]int64
}

// NewVerifier copies configuration and key material. A nonpositive capacity
// defaults to a fixed bound; live records are never evicted to admit new work.
func NewVerifier(config VerifyConfig) *Verifier {
	keys := make(map[string][]byte, len(config.Keys))
	for id, key := range config.Keys {
		keys[id] = bytes.Clone(key)
	}
	config.Keys = keys
	if config.ReplayCapacity <= 0 {
		config.ReplayCapacity = 4096
	}
	return &Verifier{config: config, seen: map[string]int64{}}
}

func validRequest(method, path string) bool {
	if method != "GET" && method != "POST" && method != "PUT" && method != "DELETE" {
		return false
	}
	u, err := url.ParseRequestURI(path)
	if err != nil || u.IsAbs() || u.Host != "" || u.Fragment != "" || !strings.HasPrefix(path, "/v1/") || len(path) > 2048 {
		return false
	}
	decoded := u.Path
	for range 2 {
		decoded, err = url.PathUnescape(decoded)
		if err != nil {
			return false
		}
	}
	return !strings.Contains(decoded, "..") && !strings.Contains(decoded, "//") && !strings.ContainsAny(decoded, "\\\r\n")
}

func validViewer(v Viewer) bool {
	if v.Subject == "" || len(v.Subject) > 256 || v.SessionRevision < 0 || v.Role == "" || len(v.Role) > 64 || len(v.OUs) > 64 {
		return false
	}
	for _, ou := range v.OUs {
		if ou == "" || len(ou) > 256 {
			return false
		}
	}
	return true
}

func digest(body []byte) string { sum := sha256.Sum256(body); return hex.EncodeToString(sum[:]) }
func signature(key []byte, encoded string) []byte {
	mac := hmac.New(sha256.New, key)
	mac.Write([]byte("rp-extension-v1\n"))
	mac.Write([]byte(encoded))
	return mac.Sum(nil)
}

// Sign uses identity facts already verified by the host for this request. It
// does not turn client-supplied identities into trusted facts.
func (s Signer) Sign(method, path string, body []byte, viewer Viewer, now time.Time) (string, error) {
	if len(s.Key) < 32 || s.KeyID == "" || s.Issuer == "" || s.Audience == "" || s.AppID == "" || s.InstanceID == "" || s.BootID == "" || !validRequest(method, path) || !validViewer(viewer) {
		return "", ErrInvalid
	}
	nonce := make([]byte, 24)
	if _, err := rand.Read(nonce); err != nil {
		return "", err
	}
	claims := Claims{Version: 1, KeyID: s.KeyID, Issuer: s.Issuer, Audience: s.Audience, AppID: s.AppID, InstanceID: s.InstanceID, BootID: s.BootID, RequestID: base64.RawURLEncoding.EncodeToString(nonce), IssuedAt: now.Unix(), ExpiresAt: now.Add(Lifetime).Unix(), Method: method, Path: path, BodyDigest: digest(body), Viewer: viewer}
	raw, err := json.Marshal(claims)
	if err != nil {
		return "", err
	}
	encoded := base64.RawURLEncoding.EncodeToString(raw)
	token := encoded + "." + base64.RawURLEncoding.EncodeToString(signature(s.Key, encoded))
	if len(token) > maxToken {
		return "", ErrInvalid
	}
	return token, nil
}

// Verify authenticates before reading authority and consumes the request nonce
// atomically after every boundary check. Replays and full replay storage fail closed.
func (v *Verifier) Verify(token, method, path string, body []byte, now time.Time) (Claims, error) {
	var empty Claims
	if len(token) > maxToken || !validRequest(method, path) {
		return empty, ErrInvalid
	}
	encoded, sig, ok := strings.Cut(token, ".")
	if !ok || strings.Contains(sig, ".") {
		return empty, ErrInvalid
	}
	raw, err := base64.RawURLEncoding.Strict().DecodeString(encoded)
	if err != nil {
		return empty, ErrInvalid
	}
	var c Claims
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	if decoder.Decode(&c) != nil {
		return empty, ErrInvalid
	}
	var trailing any
	if decoder.Decode(&trailing) != io.EOF {
		return empty, ErrInvalid
	}
	key := v.config.Keys[c.KeyID]
	got, err := base64.RawURLEncoding.Strict().DecodeString(sig)
	if err != nil || len(key) < 32 || !hmac.Equal(signature(key, encoded), got) {
		return empty, ErrInvalid
	}
	if c.Version != 1 || c.Issuer != v.config.Issuer || c.Audience != v.config.Audience || c.AppID != v.config.AppID || c.InstanceID != v.config.InstanceID || c.BootID != v.config.BootID || c.BootID == "" || c.RequestID == "" || len(c.RequestID) > 128 || c.Method != method || c.Path != path || c.BodyDigest != digest(body) || !validViewer(c.Viewer) {
		return empty, ErrInvalid
	}
	if c.IssuedAt > now.Add(5*time.Second).Unix() || c.ExpiresAt <= now.Unix() || c.ExpiresAt <= c.IssuedAt || c.ExpiresAt-c.IssuedAt > int64(Lifetime/time.Second) {
		return empty, ErrInvalid
	}
	v.mu.Lock()
	defer v.mu.Unlock()
	for id, expiry := range v.seen {
		if expiry <= now.Unix() {
			delete(v.seen, id)
		}
	}
	if _, exists := v.seen[c.RequestID]; exists {
		return empty, ErrInvalid
	}
	if len(v.seen) >= v.config.ReplayCapacity {
		return empty, ErrCapacity
	}
	v.seen[c.RequestID] = c.ExpiresAt
	return c, nil
}
