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
	"unicode"
	"unicode/utf8"
)

// The authenticated machine read API (doc 183). A machine assertion is sent in its own header, has
// its own prefix and MAC domain, and carries no viewer: it names the reviewed route, the
// installation generation and the machine client that was admitted.

const MachineHeader = "X-Portal-Machine-Assertion"
const MachineLifetime = 30 * time.Second
const machinePrefix = "mch."
const machineDomain = "rp-extension-machine-v1\n"
const maxMachineToken = 4096
const maxMachinePath = 2048
const maxMachineLabel = 64

// MachineClaims are the claims of a machine assertion; the request ID is `rid`.
type MachineClaims struct {
	Version      int    `json:"v"`
	KeyID        string `json:"kid"`
	Issuer       string `json:"iss"`
	Audience     string `json:"aud"`
	AppID        string `json:"app"`
	InstanceID   string `json:"instance"`
	BootID       string `json:"boot"`
	RequestID    string `json:"rid"`
	IssuedAt     int64  `json:"iat"`
	ExpiresAt    int64  `json:"exp"`
	Method       string `json:"method"`
	Installation string `json:"installation"`
	Generation   int64  `json:"generation"`
	Route        string `json:"route"`
	Path         string `json:"path"`
	QueryDigest  string `json:"query_sha256"`
	ClientID     string `json:"client_id"`
	ClientLabel  string `json:"client_label"`
}

func machineSignature(key []byte, encoded string) []byte {
	mac := hmac.New(sha256.New, key)
	mac.Write([]byte(machineDomain))
	mac.Write([]byte(encoded))
	return mac.Sum(nil)
}

// MachineQueryDigest is the digest of the canonical query a machine assertion binds.
func MachineQueryDigest(query string) string {
	sum := sha256.Sum256([]byte(query))
	return hex.EncodeToString(sum[:])
}

func validMachineRoute(id string) bool {
	if id == "" || len(id) > 32 || id[0] < 'a' || id[0] > 'z' {
		return false
	}
	for _, c := range id {
		if !((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '-') {
			return false
		}
	}
	return true
}

func validMachinePath(path string) bool {
	rest, ok := strings.CutPrefix(path, "/v1/machine/")
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

func validMachineClient(id, label string) bool {
	if len(id) != 12 {
		return false
	}
	for _, c := range id {
		if !((c >= 'a' && c <= 'z') || (c >= '2' && c <= '7')) {
			return false
		}
	}
	return label != "" && len(label) <= maxMachineLabel && utf8.ValidString(label) && strings.TrimSpace(label) == label &&
		strings.IndexFunc(label, unicode.IsControl) < 0
}

// parseMachineClaims decodes strictly: canonical base64, no unknown fields, no trailing data, and a
// re-encoding that equals the received bytes.
func parseMachineClaims(token string) (MachineClaims, string, string, bool) {
	var zero MachineClaims
	body, ok := strings.CutPrefix(token, machinePrefix)
	if !ok || len(token) > maxMachineToken {
		return zero, "", "", false
	}
	encoded, sig, ok := strings.Cut(body, ".")
	if !ok || strings.Contains(sig, ".") {
		return zero, "", "", false
	}
	raw, err := base64.RawURLEncoding.Strict().DecodeString(encoded)
	if err != nil {
		return zero, "", "", false
	}
	var c MachineClaims
	d := json.NewDecoder(bytes.NewReader(raw))
	d.DisallowUnknownFields()
	if d.Decode(&c) != nil {
		return zero, "", "", false
	}
	var trailing any
	if d.Decode(&trailing) != io.EOF {
		return zero, "", "", false
	}
	again, _ := json.Marshal(c)
	if !bytes.Equal(again, raw) || c.Version != 1 || c.Method != "GET" || c.Generation < 1 || !validMachineRoute(c.Route) || !validMachinePath(c.Path) ||
		c.RequestID == "" || len(c.RequestID) > 128 || !validMachineClient(c.ClientID, c.ClientLabel) {
		return zero, "", "", false
	}
	return c, encoded, sig, true
}

// VerifyMachineAssertion authenticates a machine assertion for the request target (path and
// canonical query as received) and consumes its request ID in the same replay store as Verify.
// Viewer, public and ingress tokens never verify here: the prefix and the MAC domain differ.
func (v *Verifier) VerifyMachineAssertion(token, target string, now time.Time) (MachineClaims, error) {
	var empty MachineClaims
	if len(token) > maxMachineToken || len(target) > maxMachinePath+maxMachineQueryRaw {
		return empty, ErrInvalid
	}
	c, encoded, sig, ok := parseMachineClaims(token)
	if !ok {
		return empty, ErrInvalid
	}
	key := v.config.Keys[c.KeyID]
	got, err := base64.RawURLEncoding.Strict().DecodeString(sig)
	if err != nil || len(key) < 32 || !hmac.Equal(machineSignature(key, encoded), got) {
		return empty, ErrInvalid
	}
	path, query, _ := strings.Cut(target, "?")
	if _, err := url.ParseQuery(query); err != nil {
		return empty, ErrInvalid
	}
	installation, hasPrefix := strings.CutPrefix(v.config.Audience, "portal.app/")
	if c.Issuer != v.config.Issuer || c.Audience != v.config.Audience || c.AppID != v.config.AppID || c.InstanceID != v.config.InstanceID || c.BootID != v.config.BootID || c.BootID == "" ||
		!hasPrefix || installation == "" || c.Installation != installation || c.Path != path || c.QueryDigest != MachineQueryDigest(query) {
		return empty, ErrInvalid
	}
	if c.IssuedAt > now.Add(5*time.Second).Unix() || c.ExpiresAt <= now.Unix() || c.ExpiresAt-c.IssuedAt != int64(MachineLifetime/time.Second) {
		return empty, ErrInvalid
	}
	v.mu.Lock()
	defer v.mu.Unlock()
	for id, expiry := range v.seen {
		if expiry <= now.Unix() {
			delete(v.seen, id)
		}
	}
	// The request ID of a machine assertion lives in its own namespace of the replay store.
	id := machinePrefix + c.RequestID
	if _, exists := v.seen[id]; exists {
		return empty, ErrInvalid
	}
	if len(v.seen) >= v.config.ReplayCapacity {
		return empty, ErrCapacity
	}
	v.seen[id] = c.ExpiresAt
	return c, nil
}

const maxMachineQueryRaw = 4096
