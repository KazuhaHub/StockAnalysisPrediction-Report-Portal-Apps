package main

import (
	"bytes"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/http"
	"os"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"

	protocol "github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/extensionprotocol"
)

const (
	applicationID          = "scheduled-digest"
	defaultSocketPath      = "/run/portal-app/http/app.sock"
	defaultStatePath       = "/data/digest-state.json"
	registrationPath       = "/run/portal-app/broker/registration.json"
	taskRequestFormat      = "portal.app-task.request/1-dev.1"
	taskResponseFormat     = "portal.app-task.response/1-dev.1"
	serviceIdentityFormat  = "portal.app.service-identity/1-dev.1"
	backendRegistrationFmt = "portal.managed-backend-registration/1-dev.1"
	stateFormat            = "scheduled-digest.state/1-dev.1"
	maxTaskBody            = 12288
	maxResultBody          = 8192
)

type digestPayload struct {
	ScheduleID string  `json:"scheduleId"`
	ReportIDs  []int64 `json:"reportIds"`
}

type taskRequest struct {
	Format       string          `json:"format"`
	TaskID       string          `json:"task_id"`
	OccurrenceID string          `json:"occurrence_id"`
	Payload      json.RawMessage `json:"payload"`
}

type digestRun struct {
	OccurrenceID string `json:"occurrenceId"`
	GeneratedAt  string `json:"generatedAt"`
	ItemCount    int    `json:"itemCount"`
	Digest       string `json:"digest"`
	Duplicate    bool   `json:"duplicate"`
}

type digestState struct {
	Format     string               `json:"format"`
	ScheduleID string               `json:"scheduleId"`
	LastRun    *digestRun           `json:"lastRun"`
	RecentRuns []digestRun          `json:"recentRuns"`
	Runs       map[string]digestRun `json:"runs"`
}

type serviceIdentity struct {
	Format          string   `json:"format"`
	LeaseID         string   `json:"lease_id"`
	AppID           string   `json:"app_id"`
	InstallationID  string   `json:"installation_id"`
	ControllerEpoch string   `json:"controller_epoch"`
	Generation      string   `json:"generation"`
	PolicyRevision  string   `json:"policy_revision"`
	ReleaseSHA256   string   `json:"release_sha256"`
	Resources       []string `json:"resources"`
	IssuedMS        string   `json:"issued_ms"`
	ExpiresMS       string   `json:"expires_ms"`
	Mac             string   `json:"mac"`
}

type backendRegistration struct {
	Format   string `json:"format"`
	Metadata struct {
		Identity struct {
			AppID           string `json:"app_id"`
			DeploymentID    string `json:"deployment_id"`
			ControllerEpoch string `json:"controller_epoch"`
			InstallationID  string `json:"installation_id"`
			Generation      string `json:"generation"`
			PolicyRevision  string `json:"policy_revision"`
			ReleaseSHA256   string `json:"release_sha256"`
		} `json:"identity"`
		InstanceID string `json:"instance_id"`
		KeyID      string `json:"key_id"`
	} `json:"metadata"`
	Key []byte `json:"signing_key"`
}

func (r backendRegistration) signer(bootID string) (protocol.Signer, error) {
	if r.Format != backendRegistrationFmt ||
		r.Metadata.Identity.AppID != applicationID ||
		r.Metadata.Identity.DeploymentID == "" ||
		r.Metadata.Identity.InstallationID == "" ||
		r.Metadata.InstanceID == "" ||
		r.Metadata.KeyID == "" ||
		len(r.Key) != 32 ||
		bootID == "" || len(bootID) > 128 {
		return protocol.Signer{}, errors.New("registration identity changed")
	}
	return protocol.Signer{
		Issuer:     "portal.app/" + r.Metadata.Identity.DeploymentID,
		Audience:   "portal.app/" + r.Metadata.Identity.InstallationID,
		AppID:      r.Metadata.Identity.AppID,
		InstanceID: r.Metadata.InstanceID,
		BootID:     bootID,
		KeyID:      r.Metadata.KeyID,
		Key:        bytes.Clone(r.Key),
	}, nil
}

type digestStore struct {
	mu         sync.Mutex
	path       string
	loaded     bool
	memoryOnly bool
	state      digestState
	now        func() time.Time
}

func newDigestStore(path string) *digestStore {
	return &digestStore{
		path: path,
		state: digestState{
			Format: stateFormat, ScheduleID: "daily",
			RecentRuns: []digestRun{}, Runs: map[string]digestRun{},
		},
		now: func() time.Time { return time.Now().UTC() },
	}
}

func (s *digestStore) load() error {
	if s.loaded {
		return nil
	}
	raw, err := os.ReadFile(s.path)
	if errors.Is(err, os.ErrNotExist) {
		s.loaded = true
		return nil
	}
	if err != nil {
		if memoryStateAllowed(err) {
			s.memoryOnly, s.loaded = true, true
			return nil
		}
		return err
	}
	var state digestState
	if json.Unmarshal(raw, &state) != nil || state.Format != stateFormat ||
		state.ScheduleID == "" || len(state.RecentRuns) > 16 ||
		state.Runs == nil || len(state.Runs) > 128 {
		return errors.New("digest state identity changed")
	}
	s.state, s.loaded = state, true
	return nil
}

func memoryStateAllowed(err error) bool {
	return errors.Is(err, os.ErrPermission) ||
		errors.Is(err, syscall.EROFS)
}

func (s *digestStore) snapshot() digestState {
	s.mu.Lock()
	defer s.mu.Unlock()
	_ = s.load()
	copy := s.state
	copy.RecentRuns = append([]digestRun(nil), s.state.RecentRuns...)
	copy.Runs = nil
	return copy
}

func (s *digestStore) apply(request taskRequest, payload digestPayload, raw []byte) (digestRun, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if err := s.load(); err != nil {
		return digestRun{}, err
	}
	sum := sha256.Sum256(append(append([]byte(request.TaskID+"\x00"), raw...), 0))
	digest := hex.EncodeToString(sum[:])
	if previous, ok := s.state.Runs[request.TaskID]; ok {
		if previous.Digest != digest || previous.OccurrenceID != request.OccurrenceID {
			return digestRun{}, errors.New("digest task identity changed")
		}
		previous.Duplicate = true
		return previous, nil
	}
	run := digestRun{
		OccurrenceID: request.OccurrenceID,
		GeneratedAt:  s.now().UTC().Format(time.RFC3339Nano),
		ItemCount:    len(payload.ReportIDs),
		Digest:       digest,
	}
	s.state.ScheduleID = payload.ScheduleID
	s.state.LastRun = &run
	s.state.Runs[request.TaskID] = run
	s.state.RecentRuns = append([]digestRun{run}, s.state.RecentRuns...)
	if len(s.state.RecentRuns) > 16 {
		s.state.RecentRuns = s.state.RecentRuns[:16]
	}
	if err := s.persist(); err != nil && !memoryStateAllowed(err) {
		return digestRun{}, err
	}
	return run, nil
}

func (s *digestStore) persist() error {
	if s.memoryOnly {
		return nil
	}
	raw, err := json.Marshal(s.state)
	if err != nil || len(raw) > 65536 {
		return errors.New("digest state exceeds bounds")
	}
	temporary := s.path + ".tmp"
	file, err := os.OpenFile(temporary, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0600)
	if err != nil {
		if memoryStateAllowed(err) {
			s.memoryOnly = true
			return nil
		}
		return err
	}
	if _, err := file.Write(raw); err != nil {
		file.Close()
		return err
	}
	if err := file.Sync(); err != nil {
		file.Close()
		return err
	}
	if err := file.Close(); err != nil {
		return err
	}
	if err := os.Rename(temporary, s.path); err != nil {
		return err
	}
	return nil
}

type application struct {
	store        *digestStore
	registration string
	bootID       string
}

func (a application) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	switch {
	case r.Method == http.MethodPost && r.URL.Path == "/v1/handshake":
		a.handleHandshake(w, r)
	case r.Method == http.MethodGet && r.URL.Path == "/health/ready":
		if r.URL.RawQuery != "" || r.Header.Get("Authorization") != "" ||
			r.Header.Get("Cookie") != "" {
			http.Error(w, "refused", http.StatusBadRequest)
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{
			"protocol": "portal.backend/1", "ready": true, "data_format": "1",
		})
	case r.Method == http.MethodGet && r.URL.Path == "/v1/digest":
		if r.URL.RawQuery != "" || r.Header.Get("Cookie") != "" ||
			r.Header.Get("Authorization") != "" {
			http.Error(w, "refused", http.StatusBadRequest)
			return
		}
		writeJSON(w, http.StatusOK, a.store.snapshot())
	case r.Method == http.MethodPost && r.URL.Path == "/v1/tasks/digest":
		a.handleTask(w, r)
	default:
		http.NotFound(w, r)
	}
}

func (a application) handleHandshake(w http.ResponseWriter, r *http.Request) {
	if r.URL.RawQuery != "" || r.Header.Get("Cookie") != "" ||
		r.Header.Get("Authorization") != "" ||
		r.Header.Get("Content-Type") != "application/json" {
		http.Error(w, "refused", http.StatusBadRequest)
		return
	}
	raw, err := io.ReadAll(io.LimitReader(r.Body, maxResultBody+1))
	if err != nil || len(raw) == 0 || len(raw) > maxResultBody {
		http.Error(w, "refused", http.StatusBadRequest)
		return
	}
	var request struct {
		Challenge string `json:"challenge"`
	}
	if strictJSON(raw, &request) != nil || request.Challenge == "" ||
		len(request.Challenge) > 4096 {
		http.Error(w, "refused", http.StatusBadRequest)
		return
	}
	registrationPath := a.registration
	if registrationPath == "" {
		registrationPath = "/run/portal-app/broker/registration.json"
	}
	registration, err := loadRegistration(registrationPath)
	defer clear(registration.Key)
	if err != nil {
		http.Error(w, "refused", http.StatusServiceUnavailable)
		return
	}
	signer, err := registration.signer(a.bootID)
	if err != nil {
		http.Error(w, "refused", http.StatusServiceUnavailable)
		return
	}
	defer clear(signer.Key)
	answer, err := signer.AnswerChallenge(
		request.Challenge, a.bootID, time.Now())
	if err != nil {
		http.Error(w, "refused", http.StatusBadRequest)
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{"answer": answer})
}

func (a application) handleTask(w http.ResponseWriter, r *http.Request) {
	if r.URL.RawQuery != "" || r.Header.Get("Cookie") != "" ||
		r.Header.Get("Authorization") != "" ||
		r.Header.Get("Content-Type") != "application/json" {
		taskFailure(w, "digest_request_invalid")
		return
	}
	raw, err := io.ReadAll(io.LimitReader(r.Body, maxTaskBody+1))
	if err != nil || len(raw) == 0 || len(raw) > maxTaskBody {
		taskFailure(w, "digest_request_invalid")
		return
	}
	var request taskRequest
	if strictJSON(raw, &request) != nil || request.Format != taskRequestFormat ||
		request.TaskID == "" || request.OccurrenceID == "" ||
		!strings.HasPrefix(request.OccurrenceID, "digest:") {
		taskFailure(w, "digest_request_invalid")
		return
	}
	registrationPath := a.registration
	if registrationPath == "" {
		registrationPath = "/run/portal-app/broker/registration.json"
	}
	registration, err := loadRegistration(registrationPath)
	defer clear(registration.Key)
	if err != nil || validateServiceIdentity(
		r.Header.Get("X-Portal-Service-Identity"), registration) != nil {
		taskFailure(w, "digest_authority_invalid")
		return
	}
	var payload digestPayload
	if strictJSON(request.Payload, &payload) != nil ||
		!validSlug(payload.ScheduleID) || len(payload.ReportIDs) > 32 ||
		!positiveIDs(payload.ReportIDs) {
		taskFailure(w, "digest_payload_invalid")
		return
	}
	canonical, err := json.Marshal(payload)
	if err != nil || len(canonical) > maxResultBody {
		taskFailure(w, "digest_payload_invalid")
		return
	}
	run, err := a.store.apply(request, payload, canonical)
	if err != nil {
		taskFailure(w, "digest_identity_conflict")
		return
	}
	result, err := json.Marshal(run)
	if err != nil || len(result) > maxResultBody {
		taskFailure(w, "digest_result_invalid")
		return
	}
	sum := sha256.Sum256(result)
	taskSuccess(w, result, hex.EncodeToString(sum[:]))
}

func loadRegistration(path string) (backendRegistration, error) {
	var registration backendRegistration
	raw, err := os.ReadFile(path)
	if err != nil || len(raw) == 0 || len(raw) > 4096 {
		clear(registration.Key)
		return registration, errors.New("registration unavailable")
	}
	defer clear(raw)
	if strictJSON(raw, &registration) != nil ||
		registration.Format != backendRegistrationFmt ||
		registration.Metadata.Identity.AppID != applicationID ||
		registration.Metadata.Identity.InstallationID == "" ||
		registration.Metadata.Identity.DeploymentID == "" ||
		registration.Metadata.Identity.ControllerEpoch == "" ||
		registration.Metadata.Identity.Generation == "" ||
		registration.Metadata.Identity.PolicyRevision == "" ||
		len(registration.Metadata.Identity.ReleaseSHA256) != 64 ||
		registration.Metadata.InstanceID == "" ||
		registration.Metadata.KeyID == "" ||
		len(registration.Key) != 32 {
		clear(registration.Key)
		return backendRegistration{}, errors.New("registration changed")
	}
	canonical, err := json.Marshal(registration)
	if err != nil || !bytes.Equal(canonical, raw) {
		clear(canonical)
		clear(registration.Key)
		return backendRegistration{}, errors.New("registration not canonical")
	}
	clear(canonical)
	digest := sha256.Sum256(registration.Key)
	if hex.EncodeToString(digest[:]) != registration.Metadata.KeyID {
		clear(registration.Key)
		return backendRegistration{}, errors.New("registration key changed")
	}
	return registration, nil
}

func positiveIDs(values []int64) bool {
	for _, value := range values {
		if value < 1 {
			return false
		}
	}
	return true
}

func validateServiceIdentity(raw string, registration backendRegistration) error {
	if len(raw) == 0 || len(raw) > 8192 {
		return errors.New("service identity unavailable")
	}
	var grant serviceIdentity
	if strictJSON([]byte(raw), &grant) != nil ||
		grant.Format != serviceIdentityFormat ||
		grant.AppID != applicationID ||
		grant.InstallationID != registration.Metadata.Identity.InstallationID ||
		grant.Generation != registration.Metadata.Identity.Generation ||
		grant.PolicyRevision != registration.Metadata.Identity.PolicyRevision ||
		grant.ReleaseSHA256 != registration.Metadata.Identity.ReleaseSHA256 ||
		len(grant.Mac) != 64 ||
		!contains(grant.Resources, "reports.read") ||
		!contains(grant.Resources, "tasks.schedule") {
		return errors.New("service identity changed")
	}
	now, issued, expires := time.Now().UnixMilli(),
		parseInt(grant.IssuedMS), parseInt(grant.ExpiresMS)
	if issued <= 0 || expires <= now || expires-issued > 300000 {
		return errors.New("service identity expired")
	}
	return nil
}

func contains(values []string, required string) bool {
	previous := ""
	for _, value := range values {
		if value == "" || previous >= value {
			return false
		}
		previous = value
		if value == required {
			return true
		}
	}
	return false
}

func validSlug(value string) bool {
	if len(value) < 1 || len(value) > 64 ||
		value[0] < 'a' || value[0] > 'z' {
		return false
	}
	for _, character := range value[1:] {
		if character < 'a' || character > 'z' {
			if character < '0' || character > '9' {
				if character != '-' {
					return false
				}
			}
		}
	}
	return true
}

func parseInt(value string) int64 {
	number, _ := strconv.ParseInt(value, 10, 64)
	return number
}

func strictJSON(raw []byte, target any) error {
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	if decoder.Decode(target) != nil {
		return errors.New("invalid JSON")
	}
	if _, err := decoder.Token(); err != io.EOF {
		return errors.New("trailing JSON")
	}
	return nil
}

func taskSuccess(w http.ResponseWriter, result json.RawMessage, evidence string) {
	writeJSON(w, http.StatusOK, map[string]any{
		"format": taskResponseFormat, "outcome": "succeeded",
		"result": result, "evidence_sha256": evidence,
	})
}

func taskFailure(w http.ResponseWriter, code string) {
	writeJSON(w, http.StatusOK, map[string]any{
		"format": taskResponseFormat, "outcome": "failed", "error_code": code,
	})
}

func writeJSON(w http.ResponseWriter, status int, value any) {
	raw, err := json.Marshal(value)
	if err != nil || len(raw) > maxResultBody {
		http.Error(w, "refused", http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_, _ = w.Write(raw)
}

func main() {
	socket := os.Getenv("PORTAL_APP_HTTP_SOCKET")
	if socket == "" {
		socket = defaultSocketPath
	}
	statePath := os.Getenv("PORTAL_DIGEST_STATE_PATH")
	if statePath == "" {
		statePath = defaultStatePath
	}
	listener, err := net.Listen("unix", socket)
	if err != nil {
		os.Exit(2)
	}
	defer listener.Close()
	if err := os.Chmod(socket, 0600); err != nil {
		os.Exit(3)
	}
	var boot [16]byte
	if _, err := rand.Read(boot[:]); err != nil {
		os.Exit(5)
	}
	server := &http.Server{
		ReadHeaderTimeout: time.Second,
		ReadTimeout:       2 * time.Second,
		WriteTimeout:      2 * time.Second,
		IdleTimeout:       time.Second,
		MaxHeaderBytes:    65536,
		Handler: application{
			store: newDigestStore(statePath), registration: registrationPath,
			bootID: hex.EncodeToString(boot[:]),
		},
	}
	if err := server.Serve(listener); err != nil {
		os.Exit(4)
	}
}
