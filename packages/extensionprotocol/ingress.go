package extensionprotocol

import (
	"bytes"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"time"
)

// Authenticated inbound ingress (doc 180). The Portal has already verified the sender's HMAC, its
// timestamp window and its nonce; the ingress assertion tells the backend which endpoint of which
// installation generation was heard, and carries the digests of the body and of the sender's nonce.
// It carries no secret, no source address and nothing else about the sender.

const IngressHeader = "X-Portal-Ingress-Assertion"
const IngressLifetime = 30 * time.Second
const ingressPrefix = "ing."
const ingressDomain = "rp-extension-ingress-v1\n"
const maxIngressToken = 4096

// IngressClaims are the claims of an ingress assertion; the request ID is `jti`. NonceDigest is the
// SHA-256 of the sender's nonce string and the key for durable deduplication, which is the
// app's: the verifier only rejects an assertion it has seen.
type IngressClaims struct {
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
	Endpoint     string `json:"endpoint"`
	Path         string `json:"path"`
	ReceivedMS   int64  `json:"received_ms"`
	NonceDigest  string `json:"nonce_sha256"`
	BodyDigest   string `json:"body_sha256"`
}

// IngressDigest is the lower-case hex SHA-256 an ingress assertion binds for a nonce or a body.
func IngressDigest(data []byte) string {
	sum := sha256.Sum256(data)
	return hex.EncodeToString(sum[:])
}

// VerifyIngressAssertion authenticates an ingress assertion for the request path (without a query)
// and the exact body received, and consumes its request ID in the same replay store as Verify.
// Viewer, machine and public tokens never verify here: the prefix and the MAC domain differ.
func (v *Verifier) VerifyIngressAssertion(token, path string, body []byte, now time.Time) (IngressClaims, error) {
	var empty IngressClaims
	if len(token) > maxIngressToken || len(path) > maxMachinePath {
		return empty, ErrInvalid
	}
	encoded, sig, ok := splitSpecialToken(token, ingressPrefix, maxIngressToken)
	if !ok {
		return empty, ErrInvalid
	}
	var c IngressClaims
	raw, ok := decodeSpecialClaims(encoded, &c)
	if !ok {
		return empty, ErrInvalid
	}
	key := v.config.Keys[c.KeyID]
	got, err := base64.RawURLEncoding.Strict().DecodeString(sig)
	if err != nil || len(key) < 32 || !hmac.Equal(domainSignature(ingressDomain, key, encoded), got) {
		return empty, ErrInvalid
	}
	again, _ := json.Marshal(c)
	if !bytes.Equal(again, raw) || c.Version != 1 || c.Method != "POST" || c.Generation < 1 || !validMachineRoute(c.Route) || !validEndpointID(c.Endpoint) ||
		!validSpacePath("/v1/ingress/", c.Path) || c.RequestID == "" || len(c.RequestID) > 128 || !validHexDigest(c.NonceDigest) || !validHexDigest(c.BodyDigest) {
		return empty, ErrInvalid
	}
	if !v.boundTo(c.Issuer, c.Audience, c.AppID, c.InstanceID, c.BootID, c.Installation) || c.Path != path || c.BodyDigest != IngressDigest(body) ||
		!specialTimeOK(c.IssuedAt, c.ExpiresAt, IngressLifetime, now) {
		return empty, ErrInvalid
	}
	if err := v.consumeSpecial(ingressPrefix, c.RequestID, c.ExpiresAt, now); err != nil {
		return empty, err
	}
	return c, nil
}
