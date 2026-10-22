package status

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"crypto/tls"
	"encoding/hex"
	"encoding/json"
	"io"
	"math/big"
	"net"
	"net/http"
	"net/netip"
	"net/url"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"

	protocol "github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/extensionprotocol"
	"github.com/jackc/pgx/v5"
)

type Balance struct {
	Currency string `json:"currency"`
	Total    string `json:"total,omitempty"`
	Granted  string `json:"granted,omitempty"`
	ToppedUp string `json:"topped_up,omitempty"`
	Cash     string `json:"cash,omitempty"`
	Credit   string `json:"credit,omitempty"`
}
type Measurements struct {
	LatencyMS  int64     `json:"latency_ms,omitempty"`
	Capability string    `json:"capability,omitempty"`
	Balances   []Balance `json:"balances,omitempty"`
}
type Result struct {
	RetryAfter   time.Duration
	Outcome      string
	ReasonCode   string
	Measurements Measurements
	DurationMS   int64
}
type Monitor struct {
	ID, ComponentID, Kind, Label, CredentialID, Lease string
	Revision, CredentialRevision                      int64
	IntervalSeconds, TimeoutSeconds                   int
	Config                                            ProbeConfig
	Secret                                            CredentialSecret
}
type Prober struct {
	clientForTest func(ProbeConfig) (*http.Client, error)
}

var decimalPattern = regexp.MustCompile(`^-?(?:0|[1-9][0-9]{0,39})(?:\.[0-9]{1,12})?$`)

func decimal(value string) (*big.Rat, bool) {
	if !decimalPattern.MatchString(value) {
		return nil, false
	}
	n, ok := new(big.Rat).SetString(value)
	return n, ok
}
func thresholdOutcome(amount string, c ProbeConfig) string {
	value, ok := decimal(amount)
	if !ok {
		return "unknown"
	}
	low := c.LowBalance
	if low == "" {
		low = "0"
	}
	threshold, ok := decimal(low)
	if !ok {
		return "unknown"
	}
	if value.Cmp(threshold) <= 0 {
		return "degraded"
	}
	// Values in the hysteresis band keep an existing degraded state. They are
	// deliberately not counted as recovery samples by the reducer.
	recovery := c.RecoveryBalance
	if recovery != "" {
		high, ok := decimal(recovery)
		if !ok || high.Cmp(threshold) < 0 {
			return "unknown"
		}
		if value.Cmp(high) < 0 {
			return "hold"
		}
	}
	return "success"
}
func unknown(reason string) Result { return Result{Outcome: "unknown", ReasonCode: reason} }
func deepSeekResult(raw []byte, c ProbeConfig) Result {
	var in struct {
		Available *bool `json:"is_available"`
		Balances  []struct {
			Currency string `json:"currency"`
			Total    string `json:"total_balance"`
			Granted  string `json:"granted_balance"`
			ToppedUp string `json:"topped_up_balance"`
		} `json:"balance_infos"`
	}
	if json.Unmarshal(raw, &in) != nil || in.Available == nil || len(in.Balances) == 0 || len(in.Balances) > 8 {
		return unknown("invalid_balance_response")
	}
	r := Result{Outcome: "unknown", ReasonCode: "currency_unavailable", Measurements: Measurements{Capability: "account_balance"}}
	seen := map[string]bool{}
	for _, b := range in.Balances {
		if (b.Currency != "CNY" && b.Currency != "USD") || seen[b.Currency] {
			return unknown("invalid_balance_response")
		}
		seen[b.Currency] = true
		for _, v := range []string{b.Total, b.Granted, b.ToppedUp} {
			if _, ok := decimal(v); !ok {
				return unknown("invalid_balance_response")
			}
		}
		r.Measurements.Balances = append(r.Measurements.Balances, Balance{Currency: b.Currency, Total: b.Total, Granted: b.Granted, ToppedUp: b.ToppedUp})
		if b.Currency == c.Currency {
			r.Outcome = thresholdOutcome(b.Total, c)
			r.ReasonCode = "balance_read"
			if r.Outcome == "degraded" {
				r.ReasonCode = "low_balance"
			}
		}
	}
	if !*in.Available {
		r.Outcome = "failure"
		r.ReasonCode = "insufficient_funds"
	}
	return r
}
func qwenResult(raw []byte, c ProbeConfig) Result {
	var in struct {
		Success bool   `json:"Success"`
		Code    string `json:"Code"`
		Data    struct {
			Currency  string `json:"Currency"`
			Available string `json:"AvailableAmount"`
			Cash      string `json:"AvailableCashAmount"`
			Credit    string `json:"CreditAmount"`
		} `json:"Data"`
	}
	if json.Unmarshal(raw, &in) != nil {
		return unknown("invalid_balance_response")
	}
	if !in.Success {
		switch in.Code {
		case "NotApplicable":
			return Result{Outcome: "unsupported", ReasonCode: "billing_unsupported", Measurements: Measurements{Capability: "account_billing_only"}}
		case "NotAuthorized", "NoPermission":
			return unknown("billing_permission_required")
		case "AuthSiteFail":
			return unknown("billing_site_mismatch")
		default:
			return unknown("billing_unavailable")
		}
	}
	if in.Data.Currency != c.Currency {
		return unknown("currency_unavailable")
	}
	for _, v := range []string{in.Data.Available, in.Data.Cash, in.Data.Credit} {
		if _, ok := decimal(v); !ok {
			return unknown("invalid_balance_response")
		}
	}
	outcome := thresholdOutcome(in.Data.Available, c)
	reason := "balance_read"
	if outcome == "degraded" {
		reason = "low_credit"
	}
	return Result{Outcome: outcome, ReasonCode: reason, Measurements: Measurements{Capability: "account_billing_only", Balances: []Balance{{Currency: in.Data.Currency, Total: in.Data.Available, Cash: in.Data.Cash, Credit: in.Data.Credit}}}}
}

type probeTransport struct {
	host   string
	port   uint16
	policy protocol.Policy
	lookup func(context.Context, string) ([]netip.Addr, error)
	dial   func(context.Context, string, string) (net.Conn, error)
}

func newProbeTransport(c ProbeConfig) (*probeTransport, error) {
	u, err := url.Parse(c.URL)
	if err != nil || u.Hostname() == "" || u.User != nil || u.Fragment != "" || (u.Scheme != "https" && !(u.Scheme == "http" && c.PlainHTTP && len(c.Networks) > 0)) {
		return nil, ErrInvalid
	}
	port := uint16(443)
	if u.Scheme == "http" {
		port = 80
	}
	if u.Port() != "" {
		n, err := strconv.ParseUint(u.Port(), 10, 16)
		if err != nil || n == 0 {
			return nil, ErrInvalid
		}
		port = uint16(n)
	}
	return &probeTransport{host: u.Hostname(), port: port, policy: protocol.Policy{Networks: c.Networks, PlainHTTP: c.PlainHTTP}, lookup: func(ctx context.Context, host string) ([]netip.Addr, error) {
		return net.DefaultResolver.LookupNetIP(ctx, "ip", host)
	}, dial: (&net.Dialer{Timeout: 5 * time.Second}).DialContext}, nil
}
func (p *probeTransport) dialContext(ctx context.Context, network, address string) (net.Conn, error) {
	host, port, err := net.SplitHostPort(address)
	if err != nil || !strings.EqualFold(host, p.host) || port != strconv.Itoa(int(p.port)) {
		return nil, ErrInvalid
	}
	ips, err := p.lookup(ctx, host)
	if err != nil || len(ips) == 0 || len(ips) > 32 {
		return nil, ErrInvalid
	}
	for _, ip := range ips {
		if !p.policy.AllowsIP(ip) {
			return nil, ErrInvalid
		}
	}
	for _, ip := range ips {
		conn, err := p.dial(ctx, network, net.JoinHostPort(ip.Unmap().String(), port))
		if err == nil {
			return conn, nil
		}
		if ctx.Err() != nil {
			break
		}
	}
	return nil, ErrInvalid
}
func (p *Prober) client(c ProbeConfig) (*http.Client, error) {
	if p.clientForTest != nil {
		return p.clientForTest(c)
	}
	guard, err := newProbeTransport(c)
	if err != nil {
		return nil, err
	}
	return &http.Client{Timeout: 15 * time.Second, Transport: &http.Transport{Proxy: nil, DialContext: guard.dialContext, TLSClientConfig: &tls.Config{MinVersion: tls.VersionTLS12}, TLSHandshakeTimeout: 5 * time.Second, ResponseHeaderTimeout: 10 * time.Second, MaxResponseHeaderBytes: 32768, MaxConnsPerHost: 1, DisableKeepAlives: true}, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}, nil
}
func (p *Prober) Check(ctx context.Context, m Monitor) (result Result) {
	start := time.Now()
	defer func() {
		result.DurationMS = time.Since(start).Milliseconds()
		result.Measurements.LatencyMS = result.DurationMS
	}()
	if m.Kind == "postgres" {
		return postgresCheck(ctx, m)
	}
	c := m.Config
	method := "GET"
	switch m.Kind {
	case "dify":
		c.URL = strings.TrimSuffix(c.URL, "/")
		if strings.HasSuffix(c.URL, "/v1") {
			c.URL += "/info"
		} else {
			c.URL += "/v1/info"
		}
	case "deepseek":
		c.URL = "https://api.deepseek.com/user/balance"
	case "qwen":
		method = "POST"
		c.URL = "https://business.aliyuncs.com/"
		if c.Site == "international" {
			c.URL = "https://business.ap-southeast-1.aliyuncs.com/"
		}
	case "http":
	default:
		return Result{Outcome: "unsupported", ReasonCode: "unsupported_probe"}
	}
	client, err := p.client(c)
	if err != nil {
		return unknown("invalid_destination")
	}
	defer client.CloseIdleConnections()
	req, err := http.NewRequestWithContext(ctx, method, c.URL, nil)
	if err != nil {
		return unknown("invalid_destination")
	}
	req.Header.Set("Accept", "application/json")
	if m.Kind == "dify" || m.Kind == "deepseek" || (m.Kind == "http" && m.Secret.APIKey != "") {
		req.Header.Set("Authorization", "Bearer "+m.Secret.APIKey)
	}
	if m.Kind == "qwen" {
		signAlibaba(req, m.Secret, time.Now(), newID())
	}
	response, err := client.Do(req)
	if err != nil {
		if m.Kind == "deepseek" || m.Kind == "qwen" {
			return unknown("network_unavailable")
		}
		return Result{Outcome: "failure", ReasonCode: "network_unavailable"}
	}
	defer response.Body.Close()
	if m.Kind == "qwen" && (response.StatusCode == 401 || response.StatusCode == 403) {
		return unknown("billing_permission_required")
	}
	if response.StatusCode == 401 || response.StatusCode == 403 {
		if m.Kind == "deepseek" {
			return unknown("authentication_failed")
		}
		return Result{Outcome: "failure", ReasonCode: "authentication_failed"}
	}
	if response.StatusCode == 429 {
		return Result{Outcome: "unknown", ReasonCode: "rate_limited", RetryAfter: retryAfter(response.Header.Get("Retry-After"), time.Now())}
	}
	if response.StatusCode >= 300 && response.StatusCode < 400 {
		return unknown("redirect_refused")
	}
	raw, err := io.ReadAll(io.LimitReader(response.Body, 65537))
	if err != nil || len(raw) > 65536 {
		return unknown("invalid_response")
	}
	if m.Kind == "qwen" {
		return qwenResult(raw, m.Config)
	}
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		if m.Kind == "deepseek" {
			return unknown("upstream_unavailable")
		}
		return Result{Outcome: "failure", ReasonCode: "upstream_unavailable"}
	}
	switch m.Kind {
	case "deepseek":
		return deepSeekResult(raw, m.Config)
	case "dify":
		if !json.Valid(raw) {
			return unknown("invalid_response")
		}
	}
	return Result{Outcome: "success", ReasonCode: "reachable", Measurements: Measurements{Capability: "read_access_only"}}
}
func postgresCheck(ctx context.Context, m Monitor) Result {
	c := m.Config
	guard, err := newProbeTransport(ProbeConfig{URL: "https://" + net.JoinHostPort(c.Host, strconv.Itoa(int(c.Port))), Networks: c.Networks})
	if err != nil {
		return unknown("invalid_destination")
	}
	// Parse only a constant DSN. All target and credential fields are assigned as
	// data, preventing injected driver parameters or SQL in the configured values.
	cfg, err := pgx.ParseConfig("sslmode=verify-full")
	if err != nil {
		return Result{Outcome: "failure", ReasonCode: "database_unavailable"}
	}
	cfg.Host, cfg.Port, cfg.Database, cfg.User, cfg.Password = c.Host, c.Port, c.Database, m.Secret.Username, m.Secret.Password
	cfg.Fallbacks = nil
	cfg.DialFunc = guard.dialContext
	cfg.ConnectTimeout = 5 * time.Second
	cfg.TLSConfig = &tls.Config{ServerName: c.Host, MinVersion: tls.VersionTLS12}
	conn, err := pgx.ConnectConfig(ctx, cfg)
	if err != nil {
		return Result{Outcome: "failure", ReasonCode: "database_unavailable"}
	}
	defer conn.Close(context.Background())
	var value int
	if conn.QueryRow(ctx, `SELECT 1`).Scan(&value) != nil || value != 1 {
		return Result{Outcome: "failure", ReasonCode: "database_query_failed"}
	}
	return Result{Outcome: "success", ReasonCode: "reachable", Measurements: Measurements{Capability: "read_query_only"}}
}

// Alibaba's ACS3 signature keeps credentials out of the URL. The only runtime
// operation is the fixed, read-only BssOpenApi QueryAccountBalance action.
func signAlibaba(r *http.Request, secret CredentialSecret, now time.Time, nonce string) {
	r.Header.Set("x-acs-action", "QueryAccountBalance")
	r.Header.Set("x-acs-version", "2017-12-14")
	r.Header.Set("x-acs-date", now.UTC().Format("2006-01-02T15:04:05Z"))
	r.Header.Set("x-acs-signature-nonce", nonce)
	if secret.SecurityToken != "" {
		r.Header.Set("x-acs-security-token", secret.SecurityToken)
	}
	alibabaAuthorization(r, secret.AccessKeyID, secret.AccessKeySecret)
}
func hashHex(raw []byte) string { hash := sha256.Sum256(raw); return hex.EncodeToString(hash[:]) }
func alibabaAuthorization(r *http.Request, id, secret string) {
	hash := hashHex(nil)
	r.Header.Set("x-acs-content-sha256", hash)
	headers := map[string]string{"host": r.URL.Host}
	for name, values := range r.Header {
		lower := strings.ToLower(name)
		if strings.HasPrefix(lower, "x-acs-") || lower == "content-type" {
			headers[lower] = strings.TrimSpace(values[0])
		}
	}
	keys := make([]string, 0, len(headers))
	for k := range headers {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	canonicalHeaders := ""
	for _, key := range keys {
		canonicalHeaders += key + ":" + headers[key] + "\n"
	}
	signed := strings.Join(keys, ";")
	canonical := r.Method + "\n/\n" + r.URL.RawQuery + "\n" + canonicalHeaders + "\n" + signed + "\n" + hash
	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write([]byte("ACS3-HMAC-SHA256\n" + hashHex([]byte(canonical))))
	r.Header.Set("Authorization", "ACS3-HMAC-SHA256 Credential="+id+",SignedHeaders="+signed+",Signature="+hex.EncodeToString(mac.Sum(nil)))
}
