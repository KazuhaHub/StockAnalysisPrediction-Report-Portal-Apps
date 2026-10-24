package status

import (
	"bytes"
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	protocol "github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/extensionprotocol"
	"io"
	"net"
	"net/http"
	"net/http/cookiejar"
	"net/http/httptest"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

// This optional integration uses an isolated real Portal binary and temporary
// SQLite databases. All destinations and credentials are local fixtures.
func TestPortalNotificationCaptureAndChannelQuota(t *testing.T) {
	binary := os.Getenv("PORTAL_BINARY")
	if binary == "" {
		t.Skip("PORTAL_BINARY is required for the real Portal delivery drill")
	}
	// Caller infrastructure overrides must never escape into a fixture process.
	t.Setenv("RP_DB_DRIVER", "postgres")
	t.Setenv("RP_DB_DSN", "fixture-must-not-be-used")
	t.Setenv("RP_LISTEN", "invalid-fixture-listen")
	folder := t.TempDir()
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	address := listener.Addr().String()
	listener.Close()
	base := "http://" + address
	config := filepath.Join(folder, "portal.yaml")
	configBody := fmt.Sprintf("listen: %q\nsecret_key: %q\ndb_driver: sqlite\ndb_path: %q\n", address, "fixture-"+newID()+newID(), filepath.Join(folder, "portal.db"))
	if err := os.WriteFile(config, []byte(configBody), 0600); err != nil {
		t.Fatal(err)
	}
	environment := []string{}
	for _, value := range os.Environ() {
		if !strings.HasPrefix(value, "RP_") {
			environment = append(environment, value)
		}
	}
	environment = append(environment, "RP_CONFIG="+config)
	password := "Fixture-" + newID()
	seed := exec.Command(binary, "adduser", "admin", password, "admin")
	seed.Env = environment
	if err := seed.Run(); err != nil {
		t.Fatalf("fixture account setup: %v", err)
	}
	process := exec.Command(binary)
	process.Env = environment
	if err := process.Start(); err != nil {
		t.Fatal(err)
	}
	stopped := make(chan struct{})
	go func() { _ = process.Wait(); close(stopped) }()
	t.Cleanup(func() {
		_ = process.Process.Signal(os.Interrupt)
		select {
		case <-stopped:
		case <-time.After(5 * time.Second):
			_ = process.Process.Kill()
			<-stopped
		}
	})
	jar, _ := cookiejar.New(nil)
	admin := &http.Client{Jar: jar, Timeout: 3 * time.Second}
	deadline := time.Now().Add(15 * time.Second)
	for {
		response, err := admin.Get(base + "/healthz")
		if err == nil {
			response.Body.Close()
			if response.StatusCode == 200 {
				break
			}
		}
		select {
		case <-stopped:
			t.Fatal("Portal fixture exited before readiness")
		default:
		}
		if time.Now().After(deadline) {
			t.Fatal("Portal fixture did not become ready")
		}
		time.Sleep(25 * time.Millisecond)
	}
	call := func(method, path string, input any) map[string]json.RawMessage {
		t.Helper()
		raw, err := json.Marshal(input)
		if err != nil {
			t.Fatal(err)
		}
		request, err := http.NewRequest(method, base+path, bytes.NewReader(raw))
		if err != nil {
			t.Fatal(err)
		}
		request.Header.Set("Content-Type", "application/json")
		response, err := admin.Do(request)
		if err != nil {
			t.Fatal(err)
		}
		defer response.Body.Close()
		if response.StatusCode >= 300 {
			t.Fatalf("fixture API %s %s returned %d", method, path, response.StatusCode)
		}
		var result map[string]json.RawMessage
		if json.NewDecoder(response.Body).Decode(&result) != nil {
			t.Fatal("invalid fixture API response")
		}
		return result
	}
	call("POST", "/api/login", map[string]any{"username": "admin", "password": password})
	store := testStore(t)
	adminViewer := protocol.Viewer{Subject: "admin", Role: "admin"}
	modelCredential, err := store.SaveCredential(adminViewer, CredentialInput{Kind: "deepseek", Label: "Private billing credential", Secret: json.RawMessage(`{"api_key":"fixture-private-model-key"}`)})
	if err != nil {
		t.Fatal(err)
	}
	billingConfig := ProbeConfig{AccountRef: "billing-account-private", Currency: "CNY", LowBalance: "100", RecoveryBalance: "200"}
	billingRaw, _ := json.Marshal(billingConfig)
	billing, err := store.SaveComponent(adminViewer, ComponentInput{Label: "Private funding account", Enabled: true, Monitors: []MonitorInput{{Label: "Private model balance", Kind: "deepseek", CredentialID: modelCredential.ID, Config: billingRaw, Enabled: true, IntervalSeconds: 300, TimeoutSeconds: 5}}})
	if err != nil {
		t.Fatal(err)
	}
	component := billing.ID
	var receiverCalls atomic.Int32
	type receipt struct {
		body    []byte
		headers http.Header
		at      time.Time
	}
	received := make(chan receipt, 4)
	signingSecret := "fixture-signing-" + newID()
	receiver := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		raw, _ := io.ReadAll(io.LimitReader(r.Body, 65537))
		select {
		case received <- receipt{raw, r.Header.Clone(), time.Now()}:
		default:
			t.Error("unexpected receiver overflow")
		}
		if receiverCalls.Add(1) == 1 {
			w.Header().Set("Retry-After", "7")
			w.WriteHeader(429)
			return
		}
		w.WriteHeader(204)
	}))
	defer receiver.Close()
	channelResult := call("POST", "/api/admin/notifications/channels", map[string]any{"label": "Status fixture receiver", "adapter": "webhook", "enabled": true, "url": receiver.URL, "signing_secret": signingSecret})
	var channel struct {
		ID string `json:"id"`
	}
	if json.Unmarshal(channelResult["channel"], &channel) != nil || channel.ID == "" {
		t.Fatal("missing fixture channel")
	}
	eventType := "extension.service.status-" + component + ".notice"
	tokenResult := call("POST", "/api/admin/tokens", map[string]any{"name": "Status fixture publisher", "scope": "notify:status-" + component})
	var token string
	if json.Unmarshal(tokenResult["token"], &token) != nil || token == "" {
		t.Fatal("missing fixture publisher")
	}
	call("POST", "/api/admin/notifications/routes", map[string]any{"label": "Status fixture route", "channel_id": channel.ID, "events": []string{eventType}, "recipient_mode": "destination", "enabled": true})
	secret, _ := json.Marshal(map[string]string{"token": token})
	credential, err := store.SaveCredential(adminViewer, CredentialInput{Kind: "notification", Label: "Isolated Portal publisher", Secret: secret})
	if err != nil {
		t.Fatal(err)
	}
	if err := store.SavePublisher(adminViewer, PublisherInput{ComponentID: component, PublisherName: "status-" + component, CredentialID: credential.ID, Enabled: true}); err != nil {
		t.Fatal(err)
	}
	at := time.Now().Add(time.Minute)
	for range 3 {
		monitor, ok, err := store.ClaimDue(at)
		if err != nil || !ok {
			t.Fatal("fixture probe unavailable")
		}
		result := deepSeekResult([]byte(`{"is_available":true,"balance_infos":[{"currency":"CNY","total_balance":"12.3456","granted_balance":"0","topped_up_balance":"12.3456"}]}`), billingConfig)
		if err := store.Record(monitor, result, at); err != nil {
			t.Fatal(err)
		}
		at = at.Add(6 * time.Minute)
	}
	now := time.Now().Add(time.Hour)
	notice, ok, err := store.ClaimNotice(now)
	if err != nil || !ok {
		t.Fatal("missing Status transition")
	}
	if notice.Token != token || !store.NoticeCurrent(notice) {
		t.Fatal("claimed notice did not load the current dedicated token")
	}
	destination, _ := url.Parse(base)
	transport := http.DefaultTransport.(*http.Transport).Clone()
	defer transport.CloseIdleConnections()
	var posts atomic.Int32
	captured := make(chan string, 1)
	publisher := Publisher{URL: "https://portal.fixture", clientForTest: func(ProbeConfig) (*http.Client, error) {
		return &http.Client{Timeout: 3 * time.Second, Transport: roundTripFunc(func(r *http.Request) (*http.Response, error) {
			if r.URL.Host != "portal.fixture" {
				return nil, fmt.Errorf("publication destination changed")
			}
			outgoing := r.Clone(r.Context())
			copied := *r.URL
			outgoing.URL = &copied
			outgoing.URL.Scheme = "http"
			outgoing.URL.Host = destination.Host
			if r.Method == "POST" {
				switch posts.Add(1) {
				case 1:
					return &http.Response{StatusCode: 429, Header: http.Header{"Retry-After": []string{"120"}}, Body: io.NopCloser(strings.NewReader(`{"ok":false}`))}, nil
				case 2:
					response, err := transport.RoundTrip(outgoing)
					if err != nil {
						return nil, err
					}
					var accepted struct {
						ID string `json:"id"`
					}
					_ = json.NewDecoder(response.Body).Decode(&accepted)
					response.Body.Close()
					if response.StatusCode != 200 || accepted.ID == "" {
						return nil, fmt.Errorf("fixture capture failed")
					}
					captured <- accepted.ID
					<-r.Context().Done()
					return nil, r.Context().Err()
				}
			}
			return transport.RoundTrip(outgoing)
		})}, nil
	}}
	result := publisher.Publish(context.Background(), notice)
	if result.EventID != "" || result.RetryAfter != 120*time.Second || result.Conflict {
		t.Fatalf("capture quota result=%+v", result)
	}
	if err := store.FinishNotice(notice, result, now); err != nil {
		t.Fatal(err)
	}
	if _, ok, err := store.ClaimNotice(now.Add(119 * time.Second)); err != nil || ok {
		t.Fatal("Status retried before Retry-After")
	}
	second, ok, err := store.ClaimNotice(now.Add(2 * time.Minute))
	if err != nil || !ok {
		t.Fatal("cooldown did not release notice")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	result = publisher.Publish(ctx, second)
	cancel()
	if result.EventID != "" || result.ErrorCode != "timeout" {
		t.Fatalf("lost capture acknowledgement=%+v", result)
	}
	var eventID string
	select {
	case eventID = <-captured:
	case <-time.After(time.Second):
		t.Fatal("Portal did not durably capture before timeout")
	}
	if err := store.FinishNotice(second, result, now.Add(2*time.Minute)); err != nil {
		t.Fatal(err)
	}
	retry, ok, err := store.ClaimNotice(now.Add(time.Hour))
	if err != nil || !ok {
		t.Fatal("timeout retry unavailable")
	}
	if retry.Payload != notice.Payload || retry.OccurrenceID != notice.OccurrenceID {
		t.Fatal("Status retry changed immutable occurrence")
	}
	result = publisher.Publish(context.Background(), retry)
	if result.EventID != eventID {
		t.Fatal("Portal did not deduplicate the timed-out capture")
	}
	if err := store.FinishNotice(retry, result, now.Add(time.Hour)); err != nil {
		t.Fatal(err)
	}
	var state string
	if err := store.db.QueryRow(`SELECT state FROM notification_outbox WHERE id=?`, notice.ID).Scan(&state); err != nil || state != "delivered" {
		t.Fatal("Status capture acknowledgement was not saved")
	}
	var first, secondReceipt receipt
	select {
	case first = <-received:
	case <-time.After(3 * time.Second):
		t.Fatal("Portal did not reach the configured test channel")
	}
	select {
	case secondReceipt = <-received:
	case <-time.After(15 * time.Second):
		t.Fatal("Portal did not retry its quota-limited channel")
	}
	if secondReceipt.at.Sub(first.at) < 7*time.Second {
		t.Fatal("Portal ignored channel Retry-After")
	}
	if !bytes.Equal(first.body, secondReceipt.body) {
		t.Fatal("channel retry changed payload")
	}
	for _, item := range []receipt{first, secondReceipt} {
		mac := hmac.New(sha256.New, []byte(signingSecret))
		mac.Write(item.body)
		if item.headers.Get("X-Report-Portal-Signature") != "sha256="+hex.EncodeToString(mac.Sum(nil)) {
			t.Fatal("receiver signature invalid")
		}
		if item.headers.Get("X-Report-Portal-Event-ID") != eventID || item.headers.Get("X-Report-Portal-Event") != eventType {
			t.Fatal("receiver event identity changed")
		}
		for _, private := range []string{token, "fixture-private-model-key", "billing-account-private", "12.3456", "CNY", "Private funding account"} {
			if bytes.Contains(item.body, []byte(private)) {
				t.Fatal("receiver exposed financial or private configuration")
			}
		}
	}
	if first.headers.Get("X-Report-Portal-Delivery-ID") == "" || first.headers.Get("X-Report-Portal-Delivery-ID") != secondReceipt.headers.Get("X-Report-Portal-Delivery-ID") {
		t.Fatal("retry created a different channel delivery")
	}
	deadline = time.Now().Add(3 * time.Second)
	for {
		response := call("GET", "/api/admin/notifications/deliveries?channel_id="+channel.ID, nil)
		var deliveries []struct {
			State    string `json:"state"`
			Attempts int    `json:"attempts"`
			EventID  string `json:"event_id"`
		}
		if json.Unmarshal(response["deliveries"], &deliveries) != nil {
			t.Fatal("invalid history")
		}
		if len(deliveries) == 1 && deliveries[0].State == "accepted" {
			if deliveries[0].Attempts != 2 || deliveries[0].EventID != eventID || receiverCalls.Load() != 2 {
				t.Fatal("capture retry created extra receiver work")
			}
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("channel acceptance was not durably recorded")
		}
		time.Sleep(25 * time.Millisecond)
	}
}
