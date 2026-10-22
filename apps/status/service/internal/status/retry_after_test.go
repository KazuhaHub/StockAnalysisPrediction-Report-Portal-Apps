package status

import (
	"context"
	"errors"
	"io"
	"net/http"
	"strings"
	"testing"
	"time"
)

func TestBalanceObservationFailureRemainsUnknown(t *testing.T) {
	for _, kind := range []string{"deepseek", "qwen"} {
		prober := Prober{clientForTest: func(ProbeConfig) (*http.Client, error) {
			return &http.Client{Transport: roundTripFunc(func(*http.Request) (*http.Response, error) { return nil, errors.New("fixture transport failure") })}, nil
		}}
		result := prober.Check(context.Background(), Monitor{Kind: kind})
		if result.Outcome != "unknown" || result.ReasonCode != "network_unavailable" || len(result.Measurements.Balances) != 0 {
			t.Fatalf("unavailable billing inferred balance failure: %+v", result)
		}
	}
}
func TestBillingAuthenticationFailureRemainsUnknown(t *testing.T) {
	prober := Prober{clientForTest: func(ProbeConfig) (*http.Client, error) {
		return &http.Client{Transport: roundTripFunc(func(*http.Request) (*http.Response, error) {
			return &http.Response{StatusCode: 401, Header: http.Header{}, Body: io.NopCloser(strings.NewReader("fixture"))}, nil
		})}, nil
	}}
	result := prober.Check(context.Background(), Monitor{Kind: "deepseek"})
	if result.Outcome != "unknown" || result.ReasonCode != "authentication_failed" {
		t.Fatalf("authentication inferred exhaustion: %+v", result)
	}
}
func TestProviderRetryAfterDefersNextObservation(t *testing.T) {
	prober := Prober{clientForTest: func(ProbeConfig) (*http.Client, error) {
		return &http.Client{Transport: roundTripFunc(func(*http.Request) (*http.Response, error) {
			return &http.Response{StatusCode: 429, Header: http.Header{"Retry-After": []string{"120"}}, Body: io.NopCloser(strings.NewReader(""))}, nil
		})}, nil
	}}
	result := prober.Check(context.Background(), Monitor{Kind: "http", Config: ProbeConfig{URL: "https://fixture.example"}})
	if result.Outcome != "unknown" || result.RetryAfter != 120*time.Second {
		t.Fatalf("retry hint=%+v", result)
	}
	s := testStore(t)
	monitoredComponent(t, s)
	now := time.Now().Add(time.Minute)
	monitor, ok, err := s.ClaimDue(now)
	if err != nil || !ok {
		t.Fatal("claim failed")
	}
	if err := s.Record(monitor, result, now); err != nil {
		t.Fatal(err)
	}
	if _, ok, err := s.ClaimDue(now.Add(90 * time.Second)); err != nil || ok {
		t.Fatalf("provider cooldown ignored=%v %v", ok, err)
	}
}
func TestPublisherPreflightQuotaRetriesWithoutChangingIdentity(t *testing.T) {
	s, _ := outboxFixture(t)
	now := time.Now().Add(time.Hour)
	notice, ok, err := s.ClaimNotice(now)
	if err != nil || !ok {
		t.Fatal("claim failed")
	}
	publisher := Publisher{URL: "https://portal.example", clientForTest: func(ProbeConfig) (*http.Client, error) {
		return &http.Client{Transport: roundTripFunc(func(*http.Request) (*http.Response, error) {
			return &http.Response{StatusCode: 429, Header: http.Header{"Retry-After": []string{"120"}}, Body: io.NopCloser(strings.NewReader(""))}, nil
		})}, nil
	}}
	result := publisher.Publish(context.Background(), notice)
	if result.Conflict || result.RetryAfter != 120*time.Second {
		t.Fatalf("transient preflight quota became permanent review: %+v", result)
	}
	if err := s.FinishNotice(notice, result, now); err != nil {
		t.Fatal(err)
	}
	if _, ok, err := s.ClaimNotice(now.Add(time.Minute)); err != nil || ok {
		t.Fatal("publisher ignored quota cooldown")
	}
	retry, ok, err := s.ClaimNotice(now.Add(3 * time.Minute))
	if err != nil || !ok || retry.Payload != notice.Payload || retry.OccurrenceID != notice.OccurrenceID {
		t.Fatal("quota retry lost immutable event")
	}
}

func TestRetryAfterBoundsAndHTTPDate(t *testing.T) {
	now := time.Now().UTC().Truncate(time.Second)
	for _, sample := range []struct {
		value string
		want  time.Duration
	}{
		{"-1", 0}, {"bad", 0}, {"0", 0}, {"999999", time.Hour},
		{now.Add(90 * time.Second).Format(http.TimeFormat), 90 * time.Second},
		{now.Add(-time.Second).Format(http.TimeFormat), 0},
	} {
		if got := retryAfter(sample.value, now); got != sample.want {
			t.Fatalf("Retry-After %q=%s want=%s", sample.value, got, sample.want)
		}
	}
}
func TestPublisherPostQuotaRemainsRetryable(t *testing.T) {
	s, _ := outboxFixture(t)
	now := time.Now().Add(time.Hour)
	notice, ok, err := s.ClaimNotice(now)
	if err != nil || !ok {
		t.Fatal("claim failed")
	}
	posts := 0
	publisher := Publisher{URL: "https://portal.example", clientForTest: func(ProbeConfig) (*http.Client, error) {
		return &http.Client{Transport: roundTripFunc(func(r *http.Request) (*http.Response, error) {
			if r.Method == "GET" {
				return &http.Response{StatusCode: 200, Header: http.Header{}, Body: io.NopCloser(strings.NewReader(`{"ok":true,"publisher":"service.status-` + notice.ComponentID + `"}`))}, nil
			}
			posts++
			return &http.Response{StatusCode: 429, Header: http.Header{"Retry-After": []string{"180"}}, Body: io.NopCloser(strings.NewReader(""))}, nil
		})}, nil
	}}
	result := publisher.Publish(context.Background(), notice)
	if result.Conflict || result.RetryAfter != 180*time.Second || posts != 1 {
		t.Fatalf("post quota result=%+v posts=%d", result, posts)
	}
	if err := s.FinishNotice(notice, result, now); err != nil {
		t.Fatal(err)
	}
	if _, ok, err := s.ClaimNotice(now.Add(2 * time.Minute)); err != nil || ok {
		t.Fatal("post quota cooldown ignored")
	}
	retry, ok, err := s.ClaimNotice(now.Add(4 * time.Minute))
	if err != nil || !ok || retry.OccurrenceID != notice.OccurrenceID || retry.Payload != notice.Payload {
		t.Fatal("post quota changed occurrence")
	}
}
