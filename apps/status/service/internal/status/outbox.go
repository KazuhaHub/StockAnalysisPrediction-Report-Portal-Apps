package status

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/netip"
	"net/url"
	"regexp"
	"strings"
	"time"

	protocol "github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/extensionprotocol"
)

type PublisherInput struct {
	ComponentID   string `json:"component_id"`
	PublisherName string `json:"publisher_name"`
	CredentialID  string `json:"credential_id"`
	Enabled       bool   `json:"enabled"`
	Revision      int64  `json:"revision"`
}

var publisherName = regexp.MustCompile(`^status-[a-f0-9]{32}$`)

func (s *Store) SavePublisher(v protocol.Viewer, in PublisherInput) error {
	if !isAdmin(v) {
		return ErrForbidden
	}
	if in.PublisherName != "status-"+in.ComponentID || !publisherName.MatchString(in.PublisherName) || in.Revision < 0 {
		return ErrInvalid
	}
	tx, err := s.db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()
	var kind string
	if tx.QueryRow(`SELECT kind FROM credentials WHERE id=?`, in.CredentialID).Scan(&kind) != nil || kind != "notification" {
		return ErrInvalid
	}
	var exists string
	if tx.QueryRow(`SELECT id FROM components WHERE id=?`, in.ComponentID).Scan(&exists) != nil {
		return ErrNotFound
	}
	now := time.Now().UnixMilli()
	if in.Revision == 0 {
		_, err = tx.Exec(`INSERT INTO notification_publishers(component_id,publisher_name,credential_id,enabled,revision,updated_at) VALUES(?,?,?,?,1,?)`, in.ComponentID, in.PublisherName, in.CredentialID, in.Enabled, now)
	} else {
		var result sql.Result
		result, err = tx.Exec(`UPDATE notification_publishers SET publisher_name=?,credential_id=?,enabled=?,revision=revision+1,updated_at=? WHERE component_id=? AND revision=?`, in.PublisherName, in.CredentialID, in.Enabled, now, in.ComponentID, in.Revision)
		if err == nil {
			n, _ := result.RowsAffected()
			if n != 1 {
				return ErrConflict
			}
		}
	}
	if err != nil {
		return ErrConflict
	}
	// Existing notices keep their payload and destination revision. A new pairing
	// cannot silently reroute text captured under an older security audience.
	if _, err := tx.Exec(`UPDATE notification_outbox SET state='review_required',lease_token='',lease_until=0,last_error='publisher_changed' WHERE component_id=? AND state IN('pending','retry','leased')`, in.ComponentID); err != nil {
		return err
	}
	if err := audit(tx, v, "publisher.save", in.ComponentID, now); err != nil {
		return err
	}
	return tx.Commit()
}

type Notice struct {
	ID, ComponentID, OccurrenceID, Payload, Lease, Token string
	PublisherRevision, CredentialRevision                int64
	Attempts                                             int
}
type PublishResult struct {
	RetryAfter         time.Duration
	EventID, ErrorCode string
	Conflict           bool
}

func (s *Store) ClaimNotice(now time.Time) (Notice, bool, error) {
	var n Notice
	if s.setting("outbox_paused") == "1" {
		return n, false, nil
	}
	tx, err := s.db.Begin()
	if err != nil {
		return n, false, err
	}
	defer tx.Rollback()
	if _, err := tx.Exec(`UPDATE notification_outbox SET state='retry',lease_token='',lease_until=0,last_error='lease_expired' WHERE state='leased' AND lease_until<=?`, now.UnixMilli()); err != nil {
		return n, false, err
	}
	if _, err := tx.Exec(`UPDATE notification_outbox SET state='review_required',last_error='publisher_changed' WHERE state IN('pending','retry') AND NOT EXISTS(SELECT 1 FROM notification_publishers p WHERE p.component_id=notification_outbox.component_id AND p.enabled=1 AND p.revision=notification_outbox.publisher_revision)`); err != nil {
		return n, false, err
	}
	var sealed, credentialID string
	err = tx.QueryRow(`SELECT o.id,o.component_id,o.occurrence_id,o.payload,o.publisher_revision,o.attempts,c.id,c.revision,c.sealed_value FROM notification_outbox o JOIN notification_publishers p ON p.component_id=o.component_id AND p.revision=o.publisher_revision AND p.enabled=1 JOIN credentials c ON c.id=p.credential_id AND c.kind='notification' WHERE o.state IN('pending','retry') AND o.next_at<=? ORDER BY o.next_at,o.created_at,o.id LIMIT 1`, now.UnixMilli()).Scan(&n.ID, &n.ComponentID, &n.OccurrenceID, &n.Payload, &n.PublisherRevision, &n.Attempts, &credentialID, &n.CredentialRevision, &sealed)
	if errors.Is(err, sql.ErrNoRows) {
		if err := tx.Commit(); err != nil {
			return n, false, err
		}
		return n, false, nil
	}
	if err != nil {
		return n, false, err
	}
	plain, err := s.open(credentialID, "notification", sealed)
	if err != nil {
		return n, false, err
	}
	var secret CredentialSecret
	if json.Unmarshal(plain, &secret) != nil || secret.Token == "" {
		return n, false, ErrInvalid
	}
	n.Token = secret.Token
	n.Lease = newID()
	result, err := tx.Exec(`UPDATE notification_outbox SET state='leased',lease_token=?,lease_until=?,attempts=attempts+1,updated_at=? WHERE id=? AND state IN('pending','retry')`, n.Lease, now.Add(30*time.Second).UnixMilli(), now.UnixMilli(), n.ID)
	if err != nil {
		return n, false, err
	}
	count, _ := result.RowsAffected()
	if count != 1 {
		return n, false, nil
	}
	n.Attempts++
	if err := tx.Commit(); err != nil {
		return n, false, err
	}
	return n, true, nil
}
func (s *Store) NoticeCurrent(n Notice) bool {
	if s.setting("outbox_paused") == "1" {
		return false
	}
	var count int
	err := s.db.QueryRow(`SELECT COUNT(*) FROM notification_outbox o JOIN notification_publishers p ON p.component_id=o.component_id JOIN credentials c ON c.id=p.credential_id WHERE o.id=? AND o.state='leased' AND o.lease_token=? AND o.lease_until>? AND p.enabled=1 AND p.revision=? AND c.revision=?`, n.ID, n.Lease, time.Now().UnixMilli(), n.PublisherRevision, n.CredentialRevision).Scan(&count)
	return err == nil && count == 1
}
func (s *Store) FinishNotice(n Notice, result PublishResult, now time.Time) error {
	if !s.NoticeCurrent(n) {
		return ErrConflict
	}
	state, errorCode := "retry", result.ErrorCode
	delay := time.Duration(min(3600, 15*(1<<min(n.Attempts, 8)))) * time.Second
	next := now.Add(max(delay, min(time.Hour, max(time.Duration(0), result.RetryAfter)))).UnixMilli()
	if result.EventID != "" && len(result.EventID) <= 128 {
		state = "delivered"
		errorCode = ""
	} else if result.Conflict || n.Attempts >= 12 {
		state = "review_required"
	}
	switch errorCode {
	case "", "timeout", "unavailable", "rejected", "conflict", "invalid_response":
	default:
		errorCode = "unavailable"
	}
	updated, err := s.db.Exec(`UPDATE notification_outbox SET state=?,last_error=?,portal_event_id=?,next_at=?,lease_token='',lease_until=0,updated_at=? WHERE id=? AND state='leased' AND lease_token=? AND publisher_revision=? AND EXISTS(SELECT 1 FROM notification_publishers p JOIN credentials c ON c.id=p.credential_id WHERE p.component_id=notification_outbox.component_id AND p.enabled=1 AND p.revision=? AND c.revision=?)`, state, errorCode, result.EventID, next, now.UnixMilli(), n.ID, n.Lease, n.PublisherRevision, n.PublisherRevision, n.CredentialRevision)
	if err != nil {
		return err
	}
	count, _ := updated.RowsAffected()
	if count != 1 {
		return ErrConflict
	}
	return nil
}

type Publisher struct {
	Networks      []netip.Prefix
	URL           string
	clientForTest func(ProbeConfig) (*http.Client, error)
}

func (p *Publisher) Publish(ctx context.Context, n Notice) PublishResult {
	u, err := url.Parse(p.URL)
	if err != nil || u.Scheme != "https" || u.Hostname() == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" || (u.Path != "" && u.Path != "/") {
		return PublishResult{ErrorCode: "unavailable"}
	}
	target := strings.TrimSuffix(p.URL, "/") + "/api/v1/notifications"
	prober := Prober{clientForTest: p.clientForTest}
	client, err := prober.client(ProbeConfig{URL: target, Networks: p.Networks})
	if err != nil {
		return PublishResult{ErrorCode: "unavailable"}
	}
	defer client.CloseIdleConnections()
	identityRequest, err := http.NewRequestWithContext(ctx, "GET", target+"/publisher", nil)
	if err != nil {
		return PublishResult{ErrorCode: "unavailable"}
	}
	identityRequest.Header.Set("Authorization", "Bearer "+n.Token)
	identityResponse, err := client.Do(identityRequest)
	if err != nil {
		return PublishResult{ErrorCode: "unavailable"}
	}
	identityRaw, readErr := io.ReadAll(io.LimitReader(identityResponse.Body, 4097))
	identityResponse.Body.Close()
	var identity struct {
		OK        bool   `json:"ok"`
		Publisher string `json:"publisher"`
	}
	if identityResponse.StatusCode == 429 || identityResponse.StatusCode >= 500 {
		return PublishResult{ErrorCode: "unavailable", RetryAfter: retryAfter(identityResponse.Header.Get("Retry-After"), time.Now())}
	}
	if identityResponse.StatusCode == 401 || identityResponse.StatusCode == 403 {
		return PublishResult{ErrorCode: "rejected", Conflict: true}
	}
	if readErr != nil || len(identityRaw) > 4096 || identityResponse.StatusCode != 200 || json.Unmarshal(identityRaw, &identity) != nil || !identity.OK {
		return PublishResult{ErrorCode: "invalid_response"}
	}
	if identity.Publisher != "service.status-"+n.ComponentID {
		return PublishResult{ErrorCode: "rejected", Conflict: true}
	}
	request, err := http.NewRequestWithContext(ctx, "POST", target, strings.NewReader(n.Payload))
	if err != nil {
		return PublishResult{ErrorCode: "unavailable"}
	}
	request.Header.Set("Authorization", "Bearer "+n.Token)
	request.Header.Set("Content-Type", "application/json")
	response, err := client.Do(request)
	if err != nil {
		if ctx.Err() != nil {
			return PublishResult{ErrorCode: "timeout"}
		}
		return PublishResult{ErrorCode: "unavailable"}
	}
	defer response.Body.Close()
	if response.StatusCode == 409 {
		return PublishResult{ErrorCode: "conflict", Conflict: true}
	}
	if response.StatusCode == 401 || response.StatusCode == 403 {
		return PublishResult{ErrorCode: "rejected", Conflict: true}
	}
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return PublishResult{ErrorCode: "unavailable", RetryAfter: retryAfter(response.Header.Get("Retry-After"), time.Now())}
	}
	raw, err := io.ReadAll(io.LimitReader(response.Body, 4097))
	if err != nil || len(raw) > 4096 {
		return PublishResult{ErrorCode: "invalid_response"}
	}
	var result struct {
		OK bool   `json:"ok"`
		ID string `json:"id"`
	}
	if json.Unmarshal(raw, &result) != nil || !result.OK || result.ID == "" || len(result.ID) > 128 {
		return PublishResult{ErrorCode: "invalid_response"}
	}
	return PublishResult{EventID: result.ID}
}
func queueFingerprint(tx *sql.Tx) (string, error) {
	rows, err := tx.Query(`SELECT id,state,attempts,publisher_revision,occurrence_id,payload,lease_token,lease_until FROM notification_outbox WHERE state<>'delivered' ORDER BY id`)
	if err != nil {
		return "", err
	}
	defer rows.Close()
	hash := sha256.New()
	enc := json.NewEncoder(hash)
	for rows.Next() {
		var id, state, occurrence, payload, lease string
		var attempts int
		var revision, until int64
		if err := rows.Scan(&id, &state, &attempts, &revision, &occurrence, &payload, &lease, &until); err != nil {
			return "", err
		}
		if err := enc.Encode([]any{id, state, attempts, revision, occurrence, payload, lease, until}); err != nil {
			return "", err
		}
	}
	if err := rows.Err(); err != nil {
		return "", err
	}
	return hex.EncodeToString(hash.Sum(nil)), nil
}
func (s *Store) QueueFingerprint() (string, error) {
	tx, err := s.db.Begin()
	if err != nil {
		return "", err
	}
	defer tx.Rollback()
	return queueFingerprint(tx)
}
func (s *Store) Resume(v protocol.Viewer, fingerprint string, probes, outbox bool) error {
	if !isAdmin(v) {
		return ErrForbidden
	}
	tx, err := s.db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()
	current, err := queueFingerprint(tx)
	if err != nil {
		return err
	}
	if fingerprint != current {
		return ErrConflict
	}
	if probes {
		var paused string
		tx.QueryRow(`SELECT value FROM settings WHERE key='probes_paused'`).Scan(&paused)
		if paused == "1" {
			now := time.Now().UnixMilli()
			if err := closeEvidence(tx, "1=1", nil, now); err != nil {
				return err
			}
			if err := audit(tx, v, "probes.resume", "service", now); err != nil {
				return err
			}
		}
		if err := setSetting(tx, "probes_paused", "0"); err != nil {
			return err
		}
	}
	if outbox {
		if err := setSetting(tx, "outbox_paused", "0"); err != nil {
			return err
		}
	}
	if err := audit(tx, v, "service.resume", "service", time.Now().UnixMilli()); err != nil {
		return err
	}
	return tx.Commit()
}
func (s *Store) PublishLoop(ctx context.Context, publisher *Publisher) {
	ticker := time.NewTicker(time.Second)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case now := <-ticker.C:
			notice, ok, err := s.ClaimNotice(now)
			if err != nil || !ok {
				continue
			}
			if !s.NoticeCurrent(notice) {
				continue
			}
			timeout, cancel := context.WithTimeout(ctx, 15*time.Second)
			settings := s.Settings()
			sender := *publisher
			sender.URL = settings.PortalURL
			sender.Networks = settings.PortalNetworks
			result := sender.Publish(timeout, notice)
			cancel()
			if ctx.Err() == nil {
				_ = s.FinishNotice(notice, result, time.Now())
			}
		}
	}
}
