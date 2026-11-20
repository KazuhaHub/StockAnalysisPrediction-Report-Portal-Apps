package extensionprotocol

import (
	"bytes"
	"encoding/base64"
	"strings"
	"testing"
	"time"
)

// Produced by the Portal's SignMachineAssertion with the fixture key below at machineVectorNow.
const machineVector = "mch.eyJ2IjoxLCJraWQiOiJjdXJyZW50IiwiaXNzIjoicG9ydGFsLXRlc3QiLCJhdWQiOiJwb3J0YWwuYXBwL2luc3QtMSIsImFwcCI6InN0YXR1cyIsImluc3RhbmNlIjoicmVnaXN0cmF0aW9uLTEiLCJib290IjoiYm9vdC0xIiwicmlkIjoiak9femJXdDhaQ0M0cnF1dG8yZVhuUTVMVjh2R05iQUEiLCJpYXQiOjE3OTI2MjcyMDAsImV4cCI6MTc5MjYyNzIzMCwibWV0aG9kIjoiR0VUIiwiaW5zdGFsbGF0aW9uIjoiaW5zdC0xIiwiZ2VuZXJhdGlvbiI6Mywicm91dGUiOiJjb21wb25lbnRzIiwicGF0aCI6Ii92MS9tYWNoaW5lL2NvbXBvbmVudHMiLCJxdWVyeV9zaGEyNTYiOiI5YzIxZDllNjQzZTFkY2JmNDdmN2I4MWY5N2Q1YTkxOTZjMjkwZTY4M2NmMTU0ZGFmODg1MWNjMjUwMDJlN2ViIiwiY2xpZW50X2lkIjoiYWJjZGVmZ2hpamtsIiwiY2xpZW50X2xhYmVsIjoibmlnaHRseSBleHBvcnQifQ.VQEdz9TydGpXt9040i_z9z2CfChIR9rJ3TxFMg8ZCU8"

// The same Portal signer's public assertion for another path, to prove no kind verifies as another.
const publicVector = "pub.eyJ2IjoxLCJraWQiOiJjdXJyZW50IiwiaXNzIjoicG9ydGFsLXRlc3QiLCJhdWQiOiJwb3J0YWwuYXBwL2luc3QtMSIsImFwcCI6InN0YXR1cyIsImluc3RhbmNlIjoicmVnaXN0cmF0aW9uLTEiLCJib290IjoiYm9vdC0xIiwianRpIjoiaVZodDhUUE1WOFp5Nkc4Z0NBX2RQOG1ka2R3V1dob2IiLCJpYXQiOjE3OTI2MjcyMDAsImV4cCI6MTc5MjYyNzIzMCwibWV0aG9kIjoiR0VUIiwiaW5zdGFsbGF0aW9uIjoiaW5zdC0xIiwiZ2VuZXJhdGlvbiI6Mywicm91dGUiOiJ4IiwicGF0aCI6Ii92MS9wdWJsaWMveCIsInF1ZXJ5X3NoYTI1NiI6ImUzYjBjNDQyOThmYzFjMTQ5YWZiZjRjODk5NmZiOTI0MjdhZTQxZTQ2NDliOTM0Y2E0OTU5OTFiNzg1MmI4NTUifQ.NgAd52jeCztQnh1bEL8ZUVH0ViWLuRzzp3os2OODmmQ"

const machineTarget = "/v1/machine/components?limit=10"

var machineVectorNow = time.Date(2026, 10, 22, 0, 0, 0, 0, time.UTC)

func machineVerifier() *Verifier {
	return NewVerifier(VerifyConfig{Issuer: "portal-test", Audience: "portal.app/inst-1", AppID: "status", InstanceID: "registration-1", BootID: "boot-1",
		Keys: map[string][]byte{"current": bytes.Repeat([]byte{23}, 32)}, ReplayCapacity: 4})
}

func TestMachineAssertionFromPortalSigner(t *testing.T) {
	v := machineVerifier()
	c, err := v.VerifyMachineAssertion(machineVector, machineTarget, machineVectorNow.Add(time.Second))
	if err != nil {
		t.Fatal(err)
	}
	if c.Route != "components" || c.Generation != 3 || c.Installation != "inst-1" || c.ClientID != "abcdefghijkl" || c.ClientLabel != "nightly export" || c.Path != "/v1/machine/components" {
		t.Fatalf("claims=%+v", c)
	}
	if _, err = v.VerifyMachineAssertion(machineVector, machineTarget, machineVectorNow.Add(time.Second)); err == nil {
		t.Fatal("replay accepted")
	}
}

func TestMachineAssertionRejections(t *testing.T) {
	at := machineVectorNow.Add(time.Second)
	flip := func(s string, i int) string {
		b := []byte(s)
		if b[i] == 'A' {
			b[i] = 'B'
		} else {
			b[i] = 'A'
		}
		return string(b)
	}
	body, sig, _ := strings.Cut(strings.TrimPrefix(machineVector, "mch."), ".")
	cases := map[string]struct {
		token, target string
		now           time.Time
	}{
		"public assertion":    {publicVector, "/v1/public/x", at},
		"public as machine":   {strings.Replace(publicVector, "pub.", "mch.", 1), "/v1/public/x", at},
		"ingress prefix":      {strings.Replace(machineVector, "mch.", "ing.", 1), machineTarget, at},
		"viewer shape":        {strings.TrimPrefix(machineVector, "mch."), machineTarget, at},
		"wrong domain":        {"mch." + body + "." + base64.RawURLEncoding.EncodeToString(signature(bytes.Repeat([]byte{23}, 32), body)), machineTarget, at},
		"expired":             {machineVector, machineTarget, machineVectorNow.Add(30 * time.Second)},
		"not yet valid":       {machineVector, machineTarget, machineVectorNow.Add(-10 * time.Second)},
		"tampered claims":     {"mch." + flip(body, 40) + "." + sig, machineTarget, at},
		"tampered signature":  {"mch." + body + "." + flip(sig, 5), machineTarget, at},
		"wrong path":          {machineVector, "/v1/machine/other?limit=10", at},
		"wrong query":         {machineVector, "/v1/machine/components?limit=11", at},
		"missing query":       {machineVector, "/v1/machine/components", at},
		"trailing dot":        {machineVector + ".x", machineTarget, at},
		"empty":               {"", machineTarget, at},
		"noncanonical base64": {"mch." + body + "A." + sig, machineTarget, at},
	}
	for name, tc := range cases {
		t.Run(name, func(t *testing.T) {
			if _, err := machineVerifier().VerifyMachineAssertion(tc.token, tc.target, tc.now); err == nil {
				t.Fatal("accepted")
			}
		})
	}
}

func TestMachineAssertionBoundToInstallation(t *testing.T) {
	for _, mod := range []func(*VerifyConfig){
		func(c *VerifyConfig) { c.Audience = "portal.app/inst-2" },
		func(c *VerifyConfig) { c.Audience = "inst-1" },
		func(c *VerifyConfig) { c.Issuer = "other" },
		func(c *VerifyConfig) { c.AppID = "other" },
		func(c *VerifyConfig) { c.InstanceID = "other" },
		func(c *VerifyConfig) { c.BootID = "other" },
		func(c *VerifyConfig) { c.Keys = map[string][]byte{"current": bytes.Repeat([]byte{24}, 32)} },
		func(c *VerifyConfig) { c.Keys = map[string][]byte{"other": bytes.Repeat([]byte{23}, 32)} },
	} {
		cfg := VerifyConfig{Issuer: "portal-test", Audience: "portal.app/inst-1", AppID: "status", InstanceID: "registration-1", BootID: "boot-1", Keys: map[string][]byte{"current": bytes.Repeat([]byte{23}, 32)}}
		mod(&cfg)
		if _, err := NewVerifier(cfg).VerifyMachineAssertion(machineVector, machineTarget, machineVectorNow.Add(time.Second)); err == nil {
			t.Fatal("accepted for another installation or key")
		}
	}
}

func TestMachineReplayCapacityFailsClosed(t *testing.T) {
	v := machineVerifier()
	v.config.ReplayCapacity = 0 + 1
	v.seen["x"] = machineVectorNow.Add(time.Minute).Unix()
	if _, err := v.VerifyMachineAssertion(machineVector, machineTarget, machineVectorNow.Add(time.Second)); err != ErrCapacity {
		t.Fatalf("err=%v", err)
	}
}

func TestViewerVerifierRejectsMachineToken(t *testing.T) {
	_, v, now := fixture()
	if _, err := v.Verify(machineVector, "GET", machineTarget, nil, now); err == nil {
		t.Fatal("viewer verifier accepted a machine assertion")
	}
}
