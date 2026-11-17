package status

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"os"

	protocol "github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/extensionprotocol"
)

const (
	applicationID              = "status"
	DefaultRegistrationPath    = "/run/portal-app/broker/registration.json"
	backendRegistrationFormat  = "portal.managed-backend-registration/1-dev.1"
	maxRegistrationSize        = 4096
	maxHandshakeBody           = 8192
	maxChallengeLength         = 4096
	backendProtocolVersion     = "portal.backend/1"
	backendDataFormatVersion   = "1"
	maxBackendBootIdentityText = 128
)

// backendRegistration is the platform's registration for this boot. It is read
// from the file the platform places in the sandbox and is never accepted from a
// request. Its key is the only key that may sign or verify backend assertions.
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

// Signer returns the protocol signer for one process boot.
func (r backendRegistration) Signer(bootID string) (protocol.Signer, error) {
	if r.Format != backendRegistrationFormat ||
		r.Metadata.Identity.AppID != applicationID ||
		r.Metadata.Identity.DeploymentID == "" ||
		r.Metadata.Identity.InstallationID == "" ||
		r.Metadata.InstanceID == "" ||
		r.Metadata.KeyID == "" ||
		len(r.Key) != 32 ||
		bootID == "" || len(bootID) > maxBackendBootIdentityText {
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

// PlatformIdentity names the installation and controller epoch the data is
// being served under. A platform restore changes the epoch, so a different value
// than the one recorded in the data means the data came from somewhere else.
func (r backendRegistration) PlatformIdentity() string {
	return r.Metadata.Identity.InstallationID + "/" + r.Metadata.Identity.ControllerEpoch
}

// LoadRegistration reads and strictly validates the registration file. The file
// must be canonical JSON and its key must hash to the declared key identifier.
func LoadRegistration(path string) (backendRegistration, error) {
	var registration backendRegistration
	raw, err := os.ReadFile(path)
	if err != nil || len(raw) == 0 || len(raw) > maxRegistrationSize {
		return backendRegistration{}, errors.New("registration unavailable")
	}
	defer clear(raw)
	if strictJSON(raw, &registration) != nil ||
		registration.Format != backendRegistrationFormat ||
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
