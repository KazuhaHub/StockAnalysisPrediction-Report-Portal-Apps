package status

import (
	"context"
	"encoding/json"
	"net"
	"net/http"
	"net/http/httptest"
	"net/netip"
	"strings"
	"testing"
	"time"
)

func TestDeepSeekBalanceKeepsExactCurrencyAmounts(t *testing.T) {
	config := ProbeConfig{Currency: "CNY", LowBalance: "10.00", RecoveryBalance: "20.00"}
	good := []byte(`{"is_available":true,"balance_infos":[{"currency":"CNY","total_balance":"12345678901234567890.12","granted_balance":"0.00","topped_up_balance":"12345678901234567890.12"},{"currency":"USD","total_balance":"1.23","granted_balance":"0","topped_up_balance":"1.23"}]}`)
	r := deepSeekResult(good, config)
	if r.Outcome != "success" || len(r.Measurements.Balances) != 2 || r.Measurements.Balances[0].Total != "12345678901234567890.12" {
		t.Fatalf("balance precision=%+v", r)
	}
	empty := deepSeekResult([]byte(`{"is_available":false,"balance_infos":[{"currency":"CNY","total_balance":"0","granted_balance":"0","topped_up_balance":"0"}]}`), config)
	if empty.Outcome != "failure" || empty.ReasonCode != "insufficient_funds" {
		t.Fatalf("empty=%+v", empty)
	}
	for _, bad := range []string{`{}`, `{"is_available":true,"balance_infos":[{"currency":"CNY","total_balance":"NaN"}]}`} {
		if r := deepSeekResult([]byte(bad), config); r.Outcome != "unknown" {
			t.Fatal("malformed balance became healthy")
		}
	}
	config.Currency = "JPY"
	if r := deepSeekResult(good, config); r.Outcome != "unknown" {
		t.Fatal("missing currency treated as zero or healthy")
	}
}
func TestQwenDistinguishesCreditAndCash(t *testing.T) {
	raw := []byte(`{"Code":"200","Success":true,"Data":{"Currency":"CNY","AvailableAmount":"100.50","AvailableCashAmount":"20.25","CreditAmount":"80.25","MybankCreditAmount":"0.00"}}`)
	r := qwenResult(raw, ProbeConfig{Currency: "CNY", LowBalance: "10", RecoveryBalance: "20"})
	if r.Outcome != "success" || r.Measurements.Capability != "account_billing_only" || r.Measurements.Balances[0].Cash != "20.25" || r.Measurements.Balances[0].Credit != "80.25" {
		t.Fatalf("billing=%+v", r)
	}
	for _, code := range []string{"NotApplicable", "NotAuthorized", "NoPermission", "AuthSiteFail"} {
		body, _ := json.Marshal(map[string]any{"Success": false, "Code": code})
		expected := "unknown"
		if code == "NotApplicable" {
			expected = "unsupported"
		}
		if r := qwenResult(body, ProbeConfig{}); r.Outcome != expected || len(r.Measurements.Balances) != 0 {
			t.Fatal("billing permission failure reported zero funds")
		}
	}
}
func TestProbeTransportPinsEveryDNSAnswerAndRefusesRedirect(t *testing.T) {
	config := ProbeConfig{URL: "https://check.example/health", Networks: []netip.Prefix{netip.MustParsePrefix("10.2.0.0/16")}}
	guard, err := newProbeTransport(config)
	if err != nil {
		t.Fatal(err)
	}
	guard.lookup = func(context.Context, string) ([]netip.Addr, error) {
		return []netip.Addr{netip.MustParseAddr("8.8.8.8"), netip.MustParseAddr("169.254.169.254")}, nil
	}
	dialed := false
	guard.dial = func(context.Context, string, string) (net.Conn, error) { dialed = true; return nil, ErrInvalid }
	if _, err := guard.dialContext(context.Background(), "tcp", "check.example:443"); err == nil || dialed {
		t.Fatal("mixed DNS reached metadata")
	}
}
func TestDifyReadProbeDoesNotRunWorkflow(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "GET" || r.URL.Path != "/v1/info" || r.Header.Get("Authorization") != "Bearer provider-key" {
			t.Error("probe invoked an unexpected operation")
		}
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"name":"test-app"}`))
	}))
	defer srv.Close()
	p := &Prober{clientForTest: func(ProbeConfig) (*http.Client, error) {
		return &http.Client{Timeout: time.Second, Transport: roundTripFunc(func(r *http.Request) (*http.Response, error) {
			u := strings.TrimPrefix(srv.URL, "http://")
			r.URL.Scheme = "http"
			r.URL.Host = u
			return http.DefaultTransport.RoundTrip(r)
		})}, nil
	}}
	result := p.Check(context.Background(), Monitor{Kind: "dify", Config: ProbeConfig{URL: "https://dify.example"}, Secret: CredentialSecret{APIKey: "provider-key"}})
	if result.Outcome != "success" {
		t.Fatalf("Dify probe=%+v", result)
	}
}

type roundTripFunc func(*http.Request) (*http.Response, error)

func (f roundTripFunc) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

func TestAlibabaACS3MatchesOfficialVector(t *testing.T) {
	r, _ := http.NewRequest("POST", "https://ecs.cn-shanghai.aliyuncs.com/?ImageId=win2019_1809_x64_dtc_zh-cn_40G_alibase_20230811.vhd&RegionId=cn-shanghai", nil)
	r.Header.Set("x-acs-action", "RunInstances")
	r.Header.Set("x-acs-version", "2014-05-26")
	r.Header.Set("x-acs-date", "2023-10-26T10:22:32Z")
	r.Header.Set("x-acs-signature-nonce", "3156853299f313e23d1673dc12e1703d")
	alibabaAuthorization(r, "YourAccessKeyId", "YourAccessKeySecret")
	if !strings.HasSuffix(r.Header.Get("Authorization"), "Signature=06563a9e1b43f5dfe96b81484da74bceab24a1d853912eee15083a6f0f3283c0") {
		t.Fatal("ACS3 signature differs from official fixed-input vector")
	}
}
