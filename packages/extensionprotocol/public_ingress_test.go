package extensionprotocol

import (
	"bytes"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"strings"
	"testing"
	"time"
)

// Produced by the Portal's SignPublicAssertion and SignIngressAssertion with the fixture key of
// machineVerifier (32 bytes of 23) at machineVectorNow.
const publicQueryVector = "pub.eyJ2IjoxLCJraWQiOiJjdXJyZW50IiwiaXNzIjoicG9ydGFsLXRlc3QiLCJhdWQiOiJwb3J0YWwuYXBwL2luc3QtMSIsImFwcCI6InN0YXR1cyIsImluc3RhbmNlIjoicmVnaXN0cmF0aW9uLTEiLCJib290IjoiYm9vdC0xIiwianRpIjoiTXhhUVhzT3hJNzNkeWNxWkRHb0pxaUkzS3IwbFIwdkYiLCJpYXQiOjE3OTI2MjcyMDAsImV4cCI6MTc5MjYyNzIzMCwibWV0aG9kIjoiR0VUIiwiaW5zdGFsbGF0aW9uIjoiaW5zdC0xIiwiZ2VuZXJhdGlvbiI6Mywicm91dGUiOiJpdGVtcyIsInBhdGgiOiIvdjEvcHVibGljL2l0ZW1zIiwicXVlcnlfc2hhMjU2IjoiYTc0Y2JlMWRjOWU4NTliMjEzOWFlNjAwY2Y5MjUxYmI3MGQ4NTgwN2M3NDRiNDJkOGE5MTBiNGUwMzMwYmUwMSJ9.aB0cszJUqCjgdykpZJOZJhfayg4k2QN0PD-8uKuGRAE"
const publicEmptyQueryVector = "pub.eyJ2IjoxLCJraWQiOiJjdXJyZW50IiwiaXNzIjoicG9ydGFsLXRlc3QiLCJhdWQiOiJwb3J0YWwuYXBwL2luc3QtMSIsImFwcCI6InN0YXR1cyIsImluc3RhbmNlIjoicmVnaXN0cmF0aW9uLTEiLCJib290IjoiYm9vdC0xIiwianRpIjoiZDdTYk45WVhOcW8xY1Q5Z2lIYkZHMDBNOWsxMGU3bDQiLCJpYXQiOjE3OTI2MjcyMDAsImV4cCI6MTc5MjYyNzIzMCwibWV0aG9kIjoiR0VUIiwiaW5zdGFsbGF0aW9uIjoiaW5zdC0xIiwiZ2VuZXJhdGlvbiI6Mywicm91dGUiOiJpdGVtcyIsInBhdGgiOiIvdjEvcHVibGljL2l0ZW1zIiwicXVlcnlfc2hhMjU2IjoiZTNiMGM0NDI5OGZjMWMxNDlhZmJmNGM4OTk2ZmI5MjQyN2FlNDFlNDY0OWI5MzRjYTQ5NTk5MWI3ODUyYjg1NSJ9.66fkh-TqcWMlDjTMUbm0n7PUP02T7lLv_KfmtE0mYhI"
const ingressVector = "ing.eyJ2IjoxLCJraWQiOiJjdXJyZW50IiwiaXNzIjoicG9ydGFsLXRlc3QiLCJhdWQiOiJwb3J0YWwuYXBwL2luc3QtMSIsImFwcCI6InN0YXR1cyIsImluc3RhbmNlIjoicmVnaXN0cmF0aW9uLTEiLCJib290IjoiYm9vdC0xIiwianRpIjoiX3pnZ05IMEp4cVlDZ0tid3RYcUlFcWZSS3J0aVVMNzIiLCJpYXQiOjE3OTI2MjcyMDAsImV4cCI6MTc5MjYyNzIzMCwibWV0aG9kIjoiUE9TVCIsImluc3RhbGxhdGlvbiI6Imluc3QtMSIsImdlbmVyYXRpb24iOjMsInJvdXRlIjoiaG9va3MiLCJlbmRwb2ludCI6ImRlcGxveSIsInBhdGgiOiIvdjEvaW5ncmVzcy9ob29rcy9kZXBsb3kiLCJyZWNlaXZlZF9tcyI6MTc5MjYyNzE5OTUwMCwibm9uY2Vfc2hhMjU2IjoiZTY3MjIxOGU1N2NhNmUyZjM0M2YwZDlkYzhjMDFjYmE0Mjc4OGFjYmYwMGY3YjRiNjFlMTNiMDlmODg1MzY5YSIsImJvZHlfc2hhMjU2IjoiNWVjZTQwYTVlZDc0ZDE1ZGM1ZTM4YjA3MGU5ZTYzMDVlYTk4NTVjMGQzZWVkZDViNTNjZDc4NzUyYjYwNDlhMyJ9.8NBjJqDfA-QwpcztYobKxWjfaL6xZwVhbTPZe3zxEyI"

const publicTarget = "/v1/public/items?limit=10&page=2"
const ingressPath = "/v1/ingress/hooks/deploy"

var ingressBody = []byte(`{"event":"deploy","ok":true}`)

const ingressNonceDigest = "e672218e57ca6e2f343f0d9dc8c01cba42788acbf00f7b4b61e13b09f885369a"
const ingressBodyDigest = "5ece40a5ed74d15dc5e38b070e9e6305ea9855c0d3eedd5b53cd78752b6049a3"

func flipAt(s string, i int) string {
	b := []byte(s)
	if b[i] == 'A' {
		b[i] = 'B'
	} else {
		b[i] = 'A'
	}
	return string(b)
}

// signSpecial signs arbitrary claims the way the Portal does, to reach checks a Portal-produced
// vector cannot: wrong lifetime, unknown fields, a different installation inside the claims.
func signSpecial(prefix, domain string, claims any) string {
	raw, _ := json.Marshal(claims)
	encoded := base64.RawURLEncoding.EncodeToString(raw)
	mac := hmac.New(sha256.New, bytes.Repeat([]byte{23}, 32))
	mac.Write([]byte(domain))
	mac.Write([]byte(encoded))
	return prefix + encoded + "." + base64.RawURLEncoding.EncodeToString(mac.Sum(nil))
}

func viewerToken(t *testing.T) string {
	t.Helper()
	s := Signer{Issuer: "portal-test", Audience: "portal.app/inst-1", AppID: "status", InstanceID: "registration-1", BootID: "boot-1", KeyID: "current", Key: bytes.Repeat([]byte{23}, 32)}
	token, err := s.Sign("GET", "/v1/public/items", nil, Viewer{Subject: "u", Role: "member"}, machineVectorNow)
	if err != nil {
		t.Fatal(err)
	}
	return token
}

func TestPublicAssertionFromPortalSigner(t *testing.T) {
	v := machineVerifier()
	at := machineVectorNow.Add(time.Second)
	c, err := v.VerifyPublicAssertion(publicQueryVector, publicTarget, at)
	if err != nil {
		t.Fatal(err)
	}
	if c.Route != "items" || c.Generation != 3 || c.Installation != "inst-1" || c.Path != "/v1/public/items" || c.Method != "GET" || c.QueryDigest != PublicQueryDigest("limit=10&page=2") {
		t.Fatalf("claims=%+v", c)
	}
	if _, err = v.VerifyPublicAssertion(publicQueryVector, publicTarget, at); err == nil {
		t.Fatal("replay accepted")
	}
	if _, err = v.VerifyPublicAssertion(publicEmptyQueryVector, "/v1/public/items", at); err != nil {
		t.Fatalf("empty query: %v", err)
	}
}

func TestPublicAssertionRejections(t *testing.T) {
	at := machineVectorNow.Add(time.Second)
	body, sig, _ := strings.Cut(strings.TrimPrefix(publicQueryVector, "pub."), ".")
	cases := map[string]struct {
		token, target string
		now           time.Time
	}{
		"viewer token":          {viewerToken(t), publicTarget, at},
		"viewer token prefixed": {"pub." + viewerToken(t), publicTarget, at},
		"machine token":         {machineVector, publicTarget, at},
		"machine as public":     {strings.Replace(machineVector, "mch.", "pub.", 1), "/v1/machine/components?limit=10", at},
		"ingress token":         {ingressVector, publicTarget, at},
		"ingress as public":     {strings.Replace(ingressVector, "ing.", "pub.", 1), ingressPath, at},
		"wrong domain":          {"pub." + body + "." + base64.RawURLEncoding.EncodeToString(signature(bytes.Repeat([]byte{23}, 32), body)), publicTarget, at},
		"machine domain":        {"pub." + body + "." + base64.RawURLEncoding.EncodeToString(machineSignature(bytes.Repeat([]byte{23}, 32), body)), publicTarget, at},
		"expired":               {publicQueryVector, publicTarget, machineVectorNow.Add(30 * time.Second)},
		"not yet valid":         {publicQueryVector, publicTarget, machineVectorNow.Add(-10 * time.Second)},
		"tampered claims":       {"pub." + flipAt(body, 40) + "." + sig, publicTarget, at},
		"tampered signature":    {"pub." + body + "." + flipAt(sig, 5), publicTarget, at},
		"wrong path":            {publicQueryVector, "/v1/public/other?limit=10&page=2", at},
		"wrong query":           {publicQueryVector, "/v1/public/items?limit=11&page=2", at},
		"reordered query":       {publicQueryVector, "/v1/public/items?page=2&limit=10", at},
		"missing query":         {publicQueryVector, "/v1/public/items", at},
		"query on empty":        {publicEmptyQueryVector, "/v1/public/items?x=1", at},
		"trailing dot":          {publicQueryVector + ".x", publicTarget, at},
		"empty":                 {"", publicTarget, at},
		"noncanonical base64":   {"pub." + body + "A." + sig, publicTarget, at},
	}
	for name, tc := range cases {
		t.Run(name, func(t *testing.T) {
			if _, err := machineVerifier().VerifyPublicAssertion(tc.token, tc.target, tc.now); err == nil {
				t.Fatal("accepted")
			}
		})
	}
}

func TestPublicAssertionWrongInstallation(t *testing.T) {
	at := machineVectorNow.Add(time.Second)
	mutate := map[string]func(*VerifyConfig){
		"audience":  func(c *VerifyConfig) { c.Audience = "portal.app/inst-2" },
		"issuer":    func(c *VerifyConfig) { c.Issuer = "other" },
		"app":       func(c *VerifyConfig) { c.AppID = "other" },
		"instance":  func(c *VerifyConfig) { c.InstanceID = "registration-2" },
		"boot":      func(c *VerifyConfig) { c.BootID = "boot-2" },
		"key":       func(c *VerifyConfig) { c.Keys = map[string][]byte{"current": bytes.Repeat([]byte{24}, 32)} },
		"key id":    func(c *VerifyConfig) { c.Keys = map[string][]byte{"next": bytes.Repeat([]byte{23}, 32)} },
		"short key": func(c *VerifyConfig) { c.Keys = map[string][]byte{"current": bytes.Repeat([]byte{23}, 16)} },
	}
	for name, change := range mutate {
		t.Run(name, func(t *testing.T) {
			config := VerifyConfig{Issuer: "portal-test", Audience: "portal.app/inst-1", AppID: "status", InstanceID: "registration-1", BootID: "boot-1",
				Keys: map[string][]byte{"current": bytes.Repeat([]byte{23}, 32)}, ReplayCapacity: 4}
			change(&config)
			if _, err := NewVerifier(config).VerifyPublicAssertion(publicQueryVector, publicTarget, at); err == nil {
				t.Fatal("accepted")
			}
		})
	}
}

func TestPublicAssertionClaimShape(t *testing.T) {
	at := machineVectorNow.Add(time.Second)
	base := func() PublicClaims {
		return PublicClaims{Version: 1, KeyID: "current", Issuer: "portal-test", Audience: "portal.app/inst-1", AppID: "status", InstanceID: "registration-1", BootID: "boot-1",
			RequestID: "id-1", IssuedAt: machineVectorNow.Unix(), ExpiresAt: machineVectorNow.Unix() + 30, Method: "GET", Installation: "inst-1", Generation: 1,
			Route: "items", Path: "/v1/public/items", QueryDigest: PublicQueryDigest("")}
	}
	sign := func(c PublicClaims) string { return signSpecial("pub.", publicDomain, c) }
	if _, err := machineVerifier().VerifyPublicAssertion(sign(base()), "/v1/public/items", at); err != nil {
		t.Fatalf("control: %v", err)
	}
	bad := map[string]func(*PublicClaims){
		"lifetime":     func(c *PublicClaims) { c.ExpiresAt += 1 },
		"installation": func(c *PublicClaims) { c.Installation = "inst-2" },
		"version":      func(c *PublicClaims) { c.Version = 2 },
		"method":       func(c *PublicClaims) { c.Method = "POST" },
		"generation":   func(c *PublicClaims) { c.Generation = 0 },
		"route":        func(c *PublicClaims) { c.Route = "Items" },
		"path space":   func(c *PublicClaims) { c.Path = "/v1/machine/items" },
		"dot segment":  func(c *PublicClaims) { c.Path = "/v1/public/../x" },
		"request id":   func(c *PublicClaims) { c.RequestID = "" },
	}
	for name, change := range bad {
		t.Run(name, func(t *testing.T) {
			c := base()
			change(&c)
			if _, err := machineVerifier().VerifyPublicAssertion(sign(c), c.Path, at); err == nil {
				t.Fatal("accepted")
			}
		})
	}
	t.Run("unknown field", func(t *testing.T) {
		raw, _ := json.Marshal(base())
		extended := strings.TrimSuffix(string(raw), "}") + `,"viewer":"x"}`
		encoded := base64.RawURLEncoding.EncodeToString([]byte(extended))
		mac := hmac.New(sha256.New, bytes.Repeat([]byte{23}, 32))
		mac.Write([]byte(publicDomain))
		mac.Write([]byte(encoded))
		token := "pub." + encoded + "." + base64.RawURLEncoding.EncodeToString(mac.Sum(nil))
		if _, err := machineVerifier().VerifyPublicAssertion(token, "/v1/public/items", at); err == nil {
			t.Fatal("accepted")
		}
	})
}

func TestPublicAssertionReplayStore(t *testing.T) {
	at := machineVectorNow.Add(time.Second)
	v := NewVerifier(VerifyConfig{Issuer: "portal-test", Audience: "portal.app/inst-1", AppID: "status", InstanceID: "registration-1", BootID: "boot-1",
		Keys: map[string][]byte{"current": bytes.Repeat([]byte{23}, 32)}, ReplayCapacity: 1})
	if _, err := v.VerifyPublicAssertion(publicQueryVector, publicTarget, at); err != nil {
		t.Fatal(err)
	}
	if _, err := v.VerifyPublicAssertion(publicEmptyQueryVector, "/v1/public/items", at); err != ErrCapacity {
		t.Fatalf("full store: %v", err)
	}
}

func TestPublicAssertionReplayNamespace(t *testing.T) {
	// The same request ID in a viewer, machine or public assertion never collides.
	at := machineVectorNow.Add(time.Second)
	v := machineVerifier()
	v.seen["id-1"] = machineVectorNow.Unix() + 30
	v.seen["mch.id-1"] = machineVectorNow.Unix() + 30
	c := PublicClaims{Version: 1, KeyID: "current", Issuer: "portal-test", Audience: "portal.app/inst-1", AppID: "status", InstanceID: "registration-1", BootID: "boot-1",
		RequestID: "id-1", IssuedAt: machineVectorNow.Unix(), ExpiresAt: machineVectorNow.Unix() + 30, Method: "GET", Installation: "inst-1", Generation: 1,
		Route: "items", Path: "/v1/public/items", QueryDigest: PublicQueryDigest("")}
	token := signSpecial("pub.", publicDomain, c)
	if _, err := v.VerifyPublicAssertion(token, "/v1/public/items", at); err != nil {
		t.Fatal(err)
	}
	if _, ok := v.seen["pub.id-1"]; !ok {
		t.Fatal("request ID not recorded under the public namespace")
	}
}

func TestIngressAssertionFromPortalSigner(t *testing.T) {
	v := machineVerifier()
	at := machineVectorNow.Add(time.Second)
	c, err := v.VerifyIngressAssertion(ingressVector, ingressPath, ingressBody, at)
	if err != nil {
		t.Fatal(err)
	}
	if c.Route != "hooks" || c.Endpoint != "deploy" || c.Generation != 3 || c.Installation != "inst-1" || c.Method != "POST" || c.Path != ingressPath ||
		c.ReceivedMS != 1792627199500 || c.NonceDigest != ingressNonceDigest || c.BodyDigest != ingressBodyDigest || IngressDigest(ingressBody) != ingressBodyDigest {
		t.Fatalf("claims=%+v", c)
	}
	if _, err = v.VerifyIngressAssertion(ingressVector, ingressPath, ingressBody, at); err == nil {
		t.Fatal("replay accepted")
	}
}

func TestIngressAssertionRejections(t *testing.T) {
	at := machineVectorNow.Add(time.Second)
	body, sig, _ := strings.Cut(strings.TrimPrefix(ingressVector, "ing."), ".")
	cases := map[string]struct {
		token, path string
		body        []byte
		now         time.Time
	}{
		"viewer token":          {viewerToken(t), ingressPath, ingressBody, at},
		"viewer token prefixed": {"ing." + viewerToken(t), ingressPath, ingressBody, at},
		"machine token":         {machineVector, ingressPath, ingressBody, at},
		"machine as ingress":    {strings.Replace(machineVector, "mch.", "ing.", 1), "/v1/machine/components", ingressBody, at},
		"public token":          {publicQueryVector, ingressPath, ingressBody, at},
		"public as ingress":     {strings.Replace(publicQueryVector, "pub.", "ing.", 1), "/v1/public/items", ingressBody, at},
		"wrong domain":          {"ing." + body + "." + base64.RawURLEncoding.EncodeToString(signature(bytes.Repeat([]byte{23}, 32), body)), ingressPath, ingressBody, at},
		"public domain":         {"ing." + body + "." + base64.RawURLEncoding.EncodeToString(domainSignature(publicDomain, bytes.Repeat([]byte{23}, 32), body)), ingressPath, ingressBody, at},
		"expired":               {ingressVector, ingressPath, ingressBody, machineVectorNow.Add(30 * time.Second)},
		"not yet valid":         {ingressVector, ingressPath, ingressBody, machineVectorNow.Add(-10 * time.Second)},
		"tampered claims":       {"ing." + flipAt(body, 40) + "." + sig, ingressPath, ingressBody, at},
		"tampered signature":    {"ing." + body + "." + flipAt(sig, 5), ingressPath, ingressBody, at},
		"wrong path":            {ingressVector, "/v1/ingress/hooks/other", ingressBody, at},
		"path with query":       {ingressVector, ingressPath + "?x=1", ingressBody, at},
		"changed body":          {ingressVector, ingressPath, []byte(`{"event":"deploy","ok":false}`), at},
		"empty body":            {ingressVector, ingressPath, nil, at},
		"trailing dot":          {ingressVector + ".x", ingressPath, ingressBody, at},
		"empty":                 {"", ingressPath, ingressBody, at},
		"noncanonical base64":   {"ing." + body + "A." + sig, ingressPath, ingressBody, at},
	}
	for name, tc := range cases {
		t.Run(name, func(t *testing.T) {
			if _, err := machineVerifier().VerifyIngressAssertion(tc.token, tc.path, tc.body, tc.now); err == nil {
				t.Fatal("accepted")
			}
		})
	}
}

func TestIngressAssertionWrongInstallation(t *testing.T) {
	at := machineVectorNow.Add(time.Second)
	mutate := map[string]func(*VerifyConfig){
		"audience": func(c *VerifyConfig) { c.Audience = "portal.app/inst-2" },
		"issuer":   func(c *VerifyConfig) { c.Issuer = "other" },
		"app":      func(c *VerifyConfig) { c.AppID = "other" },
		"instance": func(c *VerifyConfig) { c.InstanceID = "registration-2" },
		"boot":     func(c *VerifyConfig) { c.BootID = "boot-2" },
		"key":      func(c *VerifyConfig) { c.Keys = map[string][]byte{"current": bytes.Repeat([]byte{24}, 32)} },
	}
	for name, change := range mutate {
		t.Run(name, func(t *testing.T) {
			config := VerifyConfig{Issuer: "portal-test", Audience: "portal.app/inst-1", AppID: "status", InstanceID: "registration-1", BootID: "boot-1",
				Keys: map[string][]byte{"current": bytes.Repeat([]byte{23}, 32)}, ReplayCapacity: 4}
			change(&config)
			if _, err := NewVerifier(config).VerifyIngressAssertion(ingressVector, ingressPath, ingressBody, at); err == nil {
				t.Fatal("accepted")
			}
		})
	}
}

func TestIngressAssertionClaimShape(t *testing.T) {
	at := machineVectorNow.Add(time.Second)
	base := func() IngressClaims {
		return IngressClaims{Version: 1, KeyID: "current", Issuer: "portal-test", Audience: "portal.app/inst-1", AppID: "status", InstanceID: "registration-1", BootID: "boot-1",
			RequestID: "id-1", IssuedAt: machineVectorNow.Unix(), ExpiresAt: machineVectorNow.Unix() + 30, Method: "POST", Installation: "inst-1", Generation: 1,
			Route: "hooks", Endpoint: "deploy", Path: ingressPath, ReceivedMS: machineVectorNow.UnixMilli(), NonceDigest: ingressNonceDigest, BodyDigest: ingressBodyDigest}
	}
	sign := func(c IngressClaims) string { return signSpecial("ing.", ingressDomain, c) }
	if _, err := machineVerifier().VerifyIngressAssertion(sign(base()), ingressPath, ingressBody, at); err != nil {
		t.Fatalf("control: %v", err)
	}
	bad := map[string]func(*IngressClaims){
		"lifetime":     func(c *IngressClaims) { c.ExpiresAt += 1 },
		"installation": func(c *IngressClaims) { c.Installation = "inst-2" },
		"version":      func(c *IngressClaims) { c.Version = 2 },
		"method":       func(c *IngressClaims) { c.Method = "GET" },
		"generation":   func(c *IngressClaims) { c.Generation = 0 },
		"route":        func(c *IngressClaims) { c.Route = "Hooks" },
		"endpoint":     func(c *IngressClaims) { c.Endpoint = "Deploy" },
		"path space":   func(c *IngressClaims) { c.Path = "/v1/public/hooks" },
		"nonce digest": func(c *IngressClaims) { c.NonceDigest = "abc" },
		"body digest":  func(c *IngressClaims) { c.BodyDigest = strings.ToUpper(ingressBodyDigest) },
		"request id":   func(c *IngressClaims) { c.RequestID = "" },
	}
	for name, change := range bad {
		t.Run(name, func(t *testing.T) {
			c := base()
			change(&c)
			if _, err := machineVerifier().VerifyIngressAssertion(sign(c), c.Path, ingressBody, at); err == nil {
				t.Fatal("accepted")
			}
		})
	}
}

func TestIngressAssertionReplayStore(t *testing.T) {
	at := machineVectorNow.Add(time.Second)
	v := NewVerifier(VerifyConfig{Issuer: "portal-test", Audience: "portal.app/inst-1", AppID: "status", InstanceID: "registration-1", BootID: "boot-1",
		Keys: map[string][]byte{"current": bytes.Repeat([]byte{23}, 32)}, ReplayCapacity: 1})
	// The slot is taken by another kind of assertion: ingress fails closed rather than evicting it.
	if _, err := v.VerifyPublicAssertion(publicQueryVector, publicTarget, at); err != nil {
		t.Fatal(err)
	}
	if _, err := v.VerifyIngressAssertion(ingressVector, ingressPath, ingressBody, at); err != ErrCapacity {
		t.Fatalf("full store: %v", err)
	}
	if _, err := v.VerifyPublicAssertion(publicQueryVector, publicTarget, at); err == nil {
		t.Fatal("public replay accepted")
	}
}
