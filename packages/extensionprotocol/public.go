package extensionprotocol

import (
	"bytes"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"io"
	"net/url"
	"strings"
	"time"
)

// The anonymous public projection (doc 179). A public assertion is sent in its own header, has its
// own prefix and MAC domain, and carries no viewer: it names the reviewed route and the installation
// generation, and nothing about the reader.

const PublicHeader = "X-Portal-Public-Assertion"
const PublicLifetime = 30 * time.Second
const publicPrefix = "pub."
const publicDomain = "rp-extension-public-v1\n"
const maxPublicToken = 4096
const maxPublicQueryRaw = 1024

// PublicClaims are the claims of a public assertion; the request ID is `jti`.
type PublicClaims struct {
	Version      int    `json:"v"`
	KeyID        string `json:"kid"`
	Issuer       string `json:"iss"`
	Audience     string `json:"aud"`
	AppID        string `json:"app"`
	InstanceID   string `json:"instance"`
	BootID       string `json:"boot"`
	RequestID    string `json:"jti"`
	IssuedAt     int64  `json:"iat"`
	ExpiresAt    int64  `json:"exp"`
	Method       string `json:"method"`
	Installation string `json:"installation"`
	Generation   int64  `json:"generation"`
	Route        string `json:"route"`
	Path         string `json:"path"`
	QueryDigest  string `json:"query_sha256"`
}

// PublicQueryDigest is the digest of the canonical query a public assertion binds. An empty query
// has the digest of the empty string.
func PublicQueryDigest(query string) string {
	sum := sha256.Sum256([]byte(query))
	return hex.EncodeToString(sum[:])
}

func domainSignature(domain string, key []byte, encoded string) []byte {
	mac := hmac.New(sha256.New, key)
	mac.Write([]byte(domain))
	mac.Write([]byte(encoded))
	return mac.Sum(nil)
}

// splitSpecialToken cuts "<prefix><claims>.<mac>" into its two base64url parts.
func splitSpecialToken(token, prefix string, limit int) (encoded, sig string, ok bool) {
	body, ok := strings.CutPrefix(token, prefix)
	if !ok || len(token) > limit {
		return "", "", false
	}
	encoded, sig, ok = strings.Cut(body, ".")
	if !ok || strings.Contains(sig, ".") {
		return "", "", false
	}
	return encoded, sig, true
}

// decodeSpecialClaims decodes strictly: canonical base64, no unknown fields, no trailing data. The
// caller compares a re-encoding with the received bytes.
func decodeSpecialClaims(encoded string, into any) ([]byte, bool) {
	raw, err := base64.RawURLEncoding.Strict().DecodeString(encoded)
	if err != nil {
		return nil, false
	}
	d := json.NewDecoder(bytes.NewReader(raw))
	d.DisallowUnknownFields()
	if d.Decode(into) != nil {
		return nil, false
	}
	var trailing any
	if d.Decode(&trailing) != io.EOF {
		return nil, false
	}
	return raw, true
}

// validSpacePath checks a reserved route-space path: the prefix, a conservative character set, no
// empty or dot segments, and a bounded length. It has no query.
func validSpacePath(prefix, path string) bool {
	rest, ok := strings.CutPrefix(path, prefix)
	if !ok || rest == "" || len(path) > maxMachinePath {
		return false
	}
	for _, c := range rest {
		if !((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '.' || c == '_' || c == '/' || c == '-') {
			return false
		}
	}
	return !strings.Contains(path, "//") && !strings.Contains(path, "..")
}

func validEndpointID(id string) bool {
	if id == "" || len(id) > 64 || id[0] < 'a' || id[0] > 'z' {
		return false
	}
	for _, c := range id {
		if !((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '-') {
			return false
		}
	}
	return true
}

func validHexDigest(s string) bool {
	if len(s) != 64 {
		return false
	}
	for _, c := range s {
		if !((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f')) {
			return false
		}
	}
	return true
}

// consumeSpecial records a request ID in its own namespace of the shared replay store, after every
// other check has passed. Replays and a full store fail closed.
func (v *Verifier) consumeSpecial(namespace, requestID string, expiresAt int64, now time.Time) error {
	v.mu.Lock()
	defer v.mu.Unlock()
	for id, expiry := range v.seen {
		if expiry <= now.Unix() {
			delete(v.seen, id)
		}
	}
	id := namespace + requestID
	if _, exists := v.seen[id]; exists {
		return ErrInvalid
	}
	if len(v.seen) >= v.config.ReplayCapacity {
		return ErrCapacity
	}
	v.seen[id] = expiresAt
	return nil
}

// boundTo reports whether the common claims belong to this verifier's installation.
func (v *Verifier) boundTo(issuer, audience, appID, instanceID, bootID, installation string) bool {
	prefixInstallation, hasPrefix := strings.CutPrefix(v.config.Audience, "portal.app/")
	return issuer == v.config.Issuer && audience == v.config.Audience && appID == v.config.AppID && instanceID == v.config.InstanceID &&
		bootID == v.config.BootID && bootID != "" && hasPrefix && prefixInstallation != "" && installation == prefixInstallation
}

func specialTimeOK(issuedAt, expiresAt int64, lifetime time.Duration, now time.Time) bool {
	return issuedAt <= now.Add(5*time.Second).Unix() && expiresAt > now.Unix() && expiresAt-issuedAt == int64(lifetime/time.Second)
}

// VerifyPublicAssertion authenticates a public assertion for the request target (path and canonical
// query as received) and consumes its request ID in the same replay store as Verify. Viewer,
// machine and ingress tokens never verify here: the prefix and the MAC domain differ.
func (v *Verifier) VerifyPublicAssertion(token, target string, now time.Time) (PublicClaims, error) {
	var empty PublicClaims
	if len(token) > maxPublicToken || len(target) > maxMachinePath+maxPublicQueryRaw+1 {
		return empty, ErrInvalid
	}
	encoded, sig, ok := splitSpecialToken(token, publicPrefix, maxPublicToken)
	if !ok {
		return empty, ErrInvalid
	}
	var c PublicClaims
	raw, ok := decodeSpecialClaims(encoded, &c)
	if !ok {
		return empty, ErrInvalid
	}
	key := v.config.Keys[c.KeyID]
	got, err := base64.RawURLEncoding.Strict().DecodeString(sig)
	if err != nil || len(key) < 32 || !hmac.Equal(domainSignature(publicDomain, key, encoded), got) {
		return empty, ErrInvalid
	}
	again, _ := json.Marshal(c)
	if !bytes.Equal(again, raw) || c.Version != 1 || c.Method != "GET" || c.Generation < 1 || !validMachineRoute(c.Route) ||
		!validSpacePath("/v1/public/", c.Path) || c.RequestID == "" || len(c.RequestID) > 128 {
		return empty, ErrInvalid
	}
	path, query, _ := strings.Cut(target, "?")
	if len(query) > maxPublicQueryRaw {
		return empty, ErrInvalid
	}
	if _, err := url.ParseQuery(query); err != nil {
		return empty, ErrInvalid
	}
	if !v.boundTo(c.Issuer, c.Audience, c.AppID, c.InstanceID, c.BootID, c.Installation) || c.Path != path || c.QueryDigest != PublicQueryDigest(query) ||
		!specialTimeOK(c.IssuedAt, c.ExpiresAt, PublicLifetime, now) {
		return empty, ErrInvalid
	}
	if err := v.consumeSpecial(publicPrefix, c.RequestID, c.ExpiresAt, now); err != nil {
		return empty, err
	}
	return c, nil
}
