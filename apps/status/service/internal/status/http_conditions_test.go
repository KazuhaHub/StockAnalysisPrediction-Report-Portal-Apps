package status

import (
	"context"
	"io"
	"net/http"
	"strings"
	"testing"
)

func TestHTTPProbeEvaluatesSavedStatusAndLiteralBodyConditions(t *testing.T) {
	for _, sample := range []struct {
		status          int
		body            string
		config          ProbeConfig
		outcome, reason string
	}{
		{200, `{"ready":true}`, ProbeConfig{ExpectedStatus: 200, BodyContains: `"ready":true`}, "success", "reachable"},
		{200, `{"ready":false}`, ProbeConfig{ExpectedStatus: 200, BodyContains: `"ready":true`}, "failure", "condition_mismatch"},
		{202, "pending", ProbeConfig{ExpectedStatus: 204}, "failure", "condition_mismatch"},
		{204, "", ProbeConfig{ExpectedStatus: 204}, "success", "reachable"},
		{200, strings.Repeat("x", 65537), ProbeConfig{}, "unknown", "invalid_response"},
	} {
		prober := Prober{clientForTest: func(ProbeConfig) (*http.Client, error) {
			return &http.Client{Transport: roundTripFunc(func(*http.Request) (*http.Response, error) {
				return &http.Response{StatusCode: sample.status, Header: http.Header{}, Body: io.NopCloser(strings.NewReader(sample.body))}, nil
			})}, nil
		}}
		sample.config.URL = "https://fixture.example/health"
		result := prober.Check(context.Background(), Monitor{Kind: "http", Config: sample.config})
		if result.Outcome != sample.outcome || result.ReasonCode != sample.reason {
			t.Fatalf("HTTP %d result=%+v", sample.status, result)
		}
	}
}
func TestHTTPConditionValidationIsBoundedAndNotAppliedToProviders(t *testing.T) {
	for _, raw := range []string{`{"url":"https://fixture.example","expected_status":99}`, `{"url":"https://fixture.example","expected_status":600}`, `{"url":"https://fixture.example","body_contains":"` + strings.Repeat("x", 257) + `"}`} {
		monitor := MonitorInput{Kind: "http", Label: "Readiness", Config: []byte(raw), IntervalSeconds: 60, TimeoutSeconds: 5}
		if err := validateMonitor(&monitor); err != ErrInvalid {
			t.Fatalf("invalid condition accepted=%v", err)
		}
	}
	monitor := MonitorInput{Kind: "dify", Label: "Dify", CredentialID: "credential", Config: []byte(`{"url":"https://fixture.example","expected_status":200}`), IntervalSeconds: 60, TimeoutSeconds: 5}
	if err := validateMonitor(&monitor); err != ErrInvalid {
		t.Fatal("generic condition changed Dify semantics")
	}
}
