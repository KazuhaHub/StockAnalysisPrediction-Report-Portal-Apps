package extensionprotocol

import (
	"bytes"
	"crypto/hmac"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"io"
	"strings"
	"time"
)

type handshake struct {
	Kind            string `json:"kind"`
	Issuer          string `json:"iss"`
	Audience        string `json:"aud"`
	AppID           string `json:"app"`
	InstanceID      string `json:"instance"`
	KeyID           string `json:"kid"`
	Nonce           string `json:"nonce"`
	IssuedAt        int64  `json:"iat"`
	ExpiresAt       int64  `json:"exp"`
	BootID          string `json:"boot,omitempty"`
	ChallengeDigest string `json:"challenge_sha256,omitempty"`
}

func (s Signer) validPair() bool {
	return len(s.Key) >= 32 && s.KeyID != "" && s.Issuer != "" && s.Audience != "" && s.AppID != "" && s.InstanceID != ""
}

func (s Signer) encodeHandshake(h handshake) (string, error) {
	if !s.validPair() {
		return "", ErrInvalid
	}
	raw, err := json.Marshal(h)
	if err != nil {
		return "", err
	}
	enc := base64.RawURLEncoding.EncodeToString(raw)
	return enc + "." + base64.RawURLEncoding.EncodeToString(signature(s.Key, "handshake:"+enc)), nil
}

func (s Signer) decodeHandshake(token, kind string, now time.Time) (handshake, error) {
	var h handshake
	if !s.validPair() || len(token) > 4096 {
		return h, ErrInvalid
	}
	encoded, sig, ok := strings.Cut(token, ".")
	if !ok {
		return h, ErrInvalid
	}
	got, err := base64.RawURLEncoding.Strict().DecodeString(sig)
	if err != nil || !hmac.Equal(got, signature(s.Key, "handshake:"+encoded)) {
		return h, ErrInvalid
	}
	raw, err := base64.RawURLEncoding.Strict().DecodeString(encoded)
	if err != nil {
		return h, ErrInvalid
	}
	d := json.NewDecoder(bytes.NewReader(raw))
	d.DisallowUnknownFields()
	if d.Decode(&h) != nil {
		return h, ErrInvalid
	}
	var extra any
	if d.Decode(&extra) != io.EOF || h.Kind != kind || h.KeyID != s.KeyID || h.Issuer != s.Issuer || h.Audience != s.Audience || h.AppID != s.AppID || h.InstanceID != s.InstanceID || h.Nonce == "" || len(h.Nonce) > 128 || h.IssuedAt > now.Add(5*time.Second).Unix() || h.ExpiresAt <= now.Unix() || h.ExpiresAt <= h.IssuedAt || h.ExpiresAt-h.IssuedAt > 30 {
		return h, ErrInvalid
	}
	return h, nil
}

// NewChallenge authenticates the host to the pinned backend. The response must
// prove both key possession and this exact fresh challenge before using its boot ID.
func (s Signer) NewChallenge(now time.Time) (string, error) {
	nonce := make([]byte, 24)
	if _, err := rand.Read(nonce); err != nil {
		return "", err
	}
	return s.encodeHandshake(handshake{Kind: "challenge", Issuer: s.Issuer, Audience: s.Audience, AppID: s.AppID, InstanceID: s.InstanceID, KeyID: s.KeyID, Nonce: base64.RawURLEncoding.EncodeToString(nonce), IssuedAt: now.Unix(), ExpiresAt: now.Add(Lifetime).Unix()})
}

func (s Signer) AnswerChallenge(challenge, bootID string, now time.Time) (string, error) {
	h, err := s.decodeHandshake(challenge, "challenge", now)
	if err != nil || bootID == "" || len(bootID) > 128 {
		return "", ErrInvalid
	}
	h.Kind = "answer"
	h.BootID = bootID
	h.ChallengeDigest = digest([]byte(challenge))
	return s.encodeHandshake(h)
}

func (s Signer) VerifyAnswer(challenge, response string, now time.Time) (string, error) {
	c, err := s.decodeHandshake(challenge, "challenge", now)
	if err != nil {
		return "", ErrInvalid
	}
	a, err := s.decodeHandshake(response, "answer", now)
	if err != nil || a.Nonce != c.Nonce || a.ChallengeDigest != digest([]byte(challenge)) || a.BootID == "" || len(a.BootID) > 128 {
		return "", ErrInvalid
	}
	return a.BootID, nil
}
