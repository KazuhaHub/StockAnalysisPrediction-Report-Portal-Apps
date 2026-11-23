package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"os"
	"strconv"
	"sync"
	"time"

	protocol "github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/extensionprotocol"
)

// Platform contract: registration, boot handshake, background service
// identity and viewer assertions. The shapes follow the scheduled-digest
// reference backend; keep them in step with the platform contract docs.

const (
	applicationID          = "kazuha-hub-market-monitor"
	taskRequestFormat      = "portal.app-task.request/1-dev.1"
	taskResponseFormat     = "portal.app-task.response/1-dev.1"
	serviceIdentityFormat  = "portal.app.service-identity/1-dev.1"
	backendRegistrationFmt = "portal.managed-backend-registration/1-dev.1"
)

type taskRequest struct {
	Format       string          `json:"format"`
	TaskID       string          `json:"task_id"`
	OccurrenceID string          `json:"occurrence_id"`
	Payload      json.RawMessage `json:"payload"`
}

type taskResponse struct {
	Format         string          `json:"format"`
	Outcome        string          `json:"outcome"`
	ErrorCode      string          `json:"error_code,omitempty"`
	Result         json.RawMessage `json:"result,omitempty"`
	EvidenceSHA256 string          `json:"evidence_sha256,omitempty"`
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
		r.Metadata.InstanceID == "" || r.Metadata.KeyID == "" ||
		len(r.Key) != 32 || bootID == "" || len(bootID) > 128 {
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

func loadRegistration(path string) (backendRegistration, error) {
	var reg backendRegistration
	raw, err := os.ReadFile(path)
	if err != nil || len(raw) == 0 || len(raw) > 4096 {
		return reg, errors.New("registration unavailable")
	}
	defer clear(raw)
	if strictJSON(raw, &reg) != nil ||
		reg.Format != backendRegistrationFmt ||
		reg.Metadata.Identity.AppID != applicationID ||
		reg.Metadata.Identity.InstallationID == "" ||
		reg.Metadata.Identity.DeploymentID == "" ||
		reg.Metadata.Identity.ControllerEpoch == "" ||
		reg.Metadata.Identity.Generation == "" ||
		reg.Metadata.Identity.PolicyRevision == "" ||
		len(reg.Metadata.Identity.ReleaseSHA256) != 64 ||
		reg.Metadata.InstanceID == "" || reg.Metadata.KeyID == "" ||
		len(reg.Key) != 32 {
		clear(reg.Key)
		return backendRegistration{}, errors.New("registration changed")
	}
	canonical, err := json.Marshal(reg)
	if err != nil || !bytes.Equal(canonical, raw) {
		clear(canonical)
		clear(reg.Key)
		return backendRegistration{}, errors.New("registration not canonical")
	}
	clear(canonical)
	sum := sha256.Sum256(reg.Key)
	if hex.EncodeToString(sum[:]) != reg.Metadata.KeyID {
		clear(reg.Key)
		return backendRegistration{}, errors.New("registration key changed")
	}
	return reg, nil
}

// authority holds the current registration's viewer verifier. The verifier
// keeps the replay cache, so it is rebuilt only when the registration's key,
// instance or installation changes.
type authority struct {
	path   string
	bootID string
	now    func() time.Time

	mu        sync.Mutex
	verifiers map[string]*protocol.Verifier
	order     []string
}

// maxVerifiers bounds the per-registration verifiers kept. Keeping old ones
// means a registration that flips back reuses its replay cache instead of
// starting empty.
const maxVerifiers = 4

func newAuthority(path, bootID string) *authority {
	return &authority{path: path, bootID: bootID, now: time.Now, verifiers: map[string]*protocol.Verifier{}}
}

// verifyViewer returns the verified claims; routes that need the admin
// surface check Claims.Admin().
func (a *authority) verifyViewer(token, method, requestURI string, body []byte) (protocol.Claims, error) {
	if token == "" {
		return protocol.Claims{}, errors.New("assertion missing")
	}
	reg, err := loadRegistration(a.path)
	defer clear(reg.Key)
	if err != nil {
		return protocol.Claims{}, err
	}
	signer, err := reg.signer(a.bootID)
	defer clear(signer.Key)
	if err != nil {
		return protocol.Claims{}, err
	}
	identity := signer.KeyID + "\x00" + signer.InstanceID + "\x00" + signer.Audience + "\x00" + signer.Issuer
	a.mu.Lock()
	verifier, ok := a.verifiers[identity]
	if !ok {
		verifier = protocol.NewVerifier(protocol.VerifyConfig{
			Issuer: signer.Issuer, Audience: signer.Audience, AppID: signer.AppID,
			InstanceID: signer.InstanceID, BootID: signer.BootID,
			Keys: map[string][]byte{signer.KeyID: signer.Key},
		})
		a.verifiers[identity] = verifier
		a.order = append(a.order, identity)
		if len(a.order) > maxVerifiers {
			delete(a.verifiers, a.order[0])
			a.order = a.order[1:]
		}
	}
	a.mu.Unlock()
	return verifier.Verify(token, method, requestURI, body, a.now())
}

func (a *authority) answerChallenge(challenge string) (string, error) {
	reg, err := loadRegistration(a.path)
	defer clear(reg.Key)
	if err != nil {
		return "", err
	}
	signer, err := reg.signer(a.bootID)
	defer clear(signer.Key)
	if err != nil {
		return "", err
	}
	return signer.AnswerChallenge(challenge, a.bootID, a.now())
}

// validateServiceIdentity checks the background service identity against the
// current registration. Its MAC is keyed with the installation identity seed,
// which only Portal holds, so the backend cannot verify it: Portal verifies it
// before dispatch, and the boundary here is the per-installation socket that
// only the platform can reach. The checks below catch drift and misrouting.
func (a *authority) validateServiceIdentity(raw string, resource string) error {
	reg, err := loadRegistration(a.path)
	defer clear(reg.Key)
	if err != nil {
		return err
	}
	if len(raw) == 0 || len(raw) > 8192 {
		return errors.New("service identity unavailable")
	}
	var grant serviceIdentity
	if strictJSON([]byte(raw), &grant) != nil ||
		grant.Format != serviceIdentityFormat ||
		grant.AppID != applicationID ||
		grant.InstallationID != reg.Metadata.Identity.InstallationID ||
		grant.ControllerEpoch != reg.Metadata.Identity.ControllerEpoch ||
		grant.LeaseID == "" ||
		grant.Generation != reg.Metadata.Identity.Generation ||
		grant.PolicyRevision != reg.Metadata.Identity.PolicyRevision ||
		grant.ReleaseSHA256 != reg.Metadata.Identity.ReleaseSHA256 ||
		len(grant.Mac) != 64 || !sortedContains(grant.Resources, resource) {
		return errors.New("service identity changed")
	}
	now := a.now().UnixMilli()
	issued, _ := strconv.ParseInt(grant.IssuedMS, 10, 64)
	expires, _ := strconv.ParseInt(grant.ExpiresMS, 10, 64)
	if issued <= 0 || issued > now+5000 || expires <= now || expires-issued > 300000 {
		return errors.New("service identity expired")
	}
	return nil
}

// sortedContains requires a strictly ascending, non-empty resource list.
func sortedContains(values []string, required string) bool {
	previous, found := "", false
	for _, value := range values {
		if value == "" || previous >= value {
			return false
		}
		previous = value
		found = found || value == required
	}
	return found
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
