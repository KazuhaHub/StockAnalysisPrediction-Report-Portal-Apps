// Command portal-dev-client stands in for Portal when a backend runs on a
// developer's machine. DEVELOPMENT ONLY: its registration key is a random one
// it generates (register --key-hex fixes one for tests), so it can sign viewer
// assertions and task identities only for a backend that was started with the
// registration it wrote. It cannot act as Portal against a real installation,
// whose registration key it never sees, and it refuses any registration it did
// not write (deployment ID portal-dev-local).
//
//	register --dir DIR --app-id ID      write DIR/registration.json (new dev key unless it exists)
//	call     --socket S --registration R [--role r] [--subject s] [--ou o]... [--body-file F] METHOD PATH
//	task     --socket S --registration R [--occurrence ID] PAYLOAD_JSON
//	ready    --socket S                 GET /health/ready (no identity, no handshake)
//	purge    --dir DIR                  delete everything inside DIR (run as root to reset local data)
//
// call and task do the boot handshake first (the backend's boot ID is only
// learned that way), then send one request over the backend's Unix socket and
// print "HTTP <status>" and the response body.
package main

import (
	"bytes"
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"

	protocol "github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/extensionprotocol"
)

const (
	// DevDeployment marks a registration written by this tool. A real Portal
	// deployment ID is a UUID, so a real registration can never carry it.
	DevDeployment    = "portal-dev-local"
	devInstallation  = "00000000-0000-4000-8000-000000000d01"
	devEpoch         = "00000000-0000-4000-8000-000000000d02"
	devLease         = "00000000-0000-4000-8000-000000000d03"
	devTask          = "00000000-0000-4000-8000-000000000d04"
	registrationName = "registration.json"
	registrationFmt  = "portal.managed-backend-registration/1-dev.1"
	taskRequestFmt   = "portal.app-task.request/1-dev.1"
	serviceIdentFmt  = "portal.app.service-identity/1-dev.1"
)

// registration mirrors the backend's view of the file Portal's runner delivers.
// The field order is the canonical encoding: a backend re-marshals what it
// read and refuses a file that differs.
type registration struct {
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

func newRegistration(appID string, key []byte) registration {
	sum := sha256.Sum256(key)
	var r registration
	r.Format = registrationFmt
	r.Metadata.Identity.AppID = appID
	r.Metadata.Identity.DeploymentID = DevDeployment
	r.Metadata.Identity.ControllerEpoch = devEpoch
	r.Metadata.Identity.InstallationID = devInstallation
	r.Metadata.Identity.Generation = "1"
	r.Metadata.Identity.PolicyRevision = "1"
	r.Metadata.Identity.ReleaseSHA256 = strings.Repeat("d", 64)
	r.Metadata.InstanceID = strings.Repeat("e", 64)
	r.Metadata.KeyID = hex.EncodeToString(sum[:])
	r.Key = key
	return r
}

func readRegistration(path string) (registration, error) {
	var r registration
	raw, err := os.ReadFile(path)
	if err != nil {
		return r, err
	}
	if json.Unmarshal(raw, &r) != nil || r.Format != registrationFmt || r.Metadata.Identity.DeploymentID != DevDeployment || len(r.Key) != 32 {
		return r, errors.New("not a registration written by portal-dev-client register; this tool never works with a real one")
	}
	return r, nil
}

func (r registration) signer(boot string) protocol.Signer {
	id := r.Metadata.Identity
	return protocol.Signer{
		Issuer: "portal.app/" + id.DeploymentID, Audience: "portal.app/" + id.InstallationID,
		AppID: id.AppID, InstanceID: r.Metadata.InstanceID, BootID: boot,
		KeyID: r.Metadata.KeyID, Key: bytes.Clone(r.Key),
	}
}

type backend struct {
	client *http.Client
	reg    registration
	boot   string
}

func dial(socket string) *http.Client {
	return &http.Client{
		Timeout: 30 * time.Second,
		Transport: &http.Transport{DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
			var d net.Dialer
			return d.DialContext(ctx, "unix", socket)
		}},
	}
}

func (b *backend) do(method, path string, header http.Header, body []byte) (int, []byte, error) {
	req, err := http.NewRequest(method, "http://app.invalid"+path, bytes.NewReader(body))
	if err != nil {
		return 0, nil, err
	}
	for name, values := range header {
		req.Header[name] = values
	}
	res, err := b.client.Do(req)
	if err != nil {
		return 0, nil, err
	}
	defer res.Body.Close()
	raw, err := io.ReadAll(io.LimitReader(res.Body, 2<<20))
	return res.StatusCode, raw, err
}

// handshake does what Portal does at every backend start: prove the registration
// key to the backend and learn its boot ID.
func (b *backend) handshake() error {
	host := b.reg.signer("")
	challenge, err := host.NewChallenge(time.Now())
	if err != nil {
		return err
	}
	body, _ := json.Marshal(map[string]string{"challenge": challenge})
	status, raw, err := b.do(http.MethodPost, "/v1/handshake", http.Header{"Content-Type": {"application/json"}}, body)
	if err != nil {
		return err
	}
	var answer struct {
		Answer string `json:"answer"`
	}
	if status != http.StatusOK || json.Unmarshal(raw, &answer) != nil {
		return fmt.Errorf("handshake refused (HTTP %d): is the backend running with this registration? %s", status, strings.TrimSpace(string(raw)))
	}
	b.boot, err = host.VerifyAnswer(challenge, answer.Answer, time.Now())
	return err
}

func generateKey() ([]byte, error) {
	key := make([]byte, 32)
	_, err := rand.Read(key)
	return key, err
}

type multi []string

func (m *multi) String() string     { return strings.Join(*m, ",") }
func (m *multi) Set(v string) error { *m = append(*m, v); return nil }

func run(args []string, stdout, stderr io.Writer) int {
	fail := func(err error) int {
		fmt.Fprintln(stderr, "portal-dev-client:", err)
		return 1
	}
	if len(args) == 0 {
		return fail(errors.New("usage: register | call | task (see the command comment)"))
	}
	flags := flag.NewFlagSet(args[0], flag.ContinueOnError)
	flags.SetOutput(stderr)
	switch args[0] {
	case "register":
		dir := flags.String("dir", "", "directory that receives registration.json")
		appID := flags.String("app-id", "", "application ID")
		keyHex := flags.String("key-hex", "", "fixed 32-byte key in hex (tests only; default: random)")
		if flags.Parse(args[1:]) != nil || *dir == "" || *appID == "" {
			return fail(errors.New("register needs --dir and --app-id"))
		}
		path := *dir + "/" + registrationName
		if existing, err := readRegistration(path); err == nil && existing.Metadata.Identity.AppID == *appID && *keyHex == "" {
			fmt.Fprintln(stdout, "registration kept:", path)
			return 0
		}
		key, err := generateKey()
		if *keyHex != "" {
			key, err = hex.DecodeString(*keyHex)
		}
		if err != nil || len(key) != 32 {
			return fail(errors.New("the key must be 32 bytes"))
		}
		raw, err := json.Marshal(newRegistration(*appID, key))
		if err != nil {
			return fail(err)
		}
		if err := os.MkdirAll(*dir, 0o755); err != nil {
			return fail(err)
		}
		// The container user (65532) must be able to read it.
		if err := os.WriteFile(path, raw, 0o644); err != nil {
			return fail(err)
		}
		fmt.Fprintln(stdout, "registration written (DEV ONLY key):", path)
		return 0
	case "ready":
		socket := flags.String("socket", "", "backend Unix socket")
		if flags.Parse(args[1:]) != nil || *socket == "" {
			return fail(errors.New("--socket is required"))
		}
		status, raw, err := (&backend{client: dial(*socket)}).do(http.MethodGet, "/health/ready", nil, nil)
		if err != nil {
			return fail(err)
		}
		fmt.Fprintf(stdout, "HTTP %d\n%s\n", status, strings.TrimSpace(string(raw)))
		if status != http.StatusOK {
			return 1
		}
		return 0
	case "purge":
		dir := flags.String("dir", "", "directory to empty")
		if flags.Parse(args[1:]) != nil || *dir == "" || *dir == "/" {
			return fail(errors.New("purge needs --dir (not /)"))
		}
		entries, err := os.ReadDir(*dir)
		if err != nil {
			return fail(err)
		}
		for _, entry := range entries {
			if err := os.RemoveAll(*dir + "/" + entry.Name()); err != nil {
				return fail(err)
			}
		}
		return 0
	case "call", "task":
		socket := flags.String("socket", "", "backend Unix socket")
		regPath := flags.String("registration", "", "registration.json written by register")
		subject := flags.String("subject", hex.EncodeToString(sha256Sum("dev-viewer")), "viewer subject (opaque, 64 hex in Portal)")
		role := flags.String("role", "user", "viewer role")
		bodyFile := flags.String("body-file", "", "request body (call)")
		occurrence := flags.String("occurrence", "", "task occurrence ID (task; default: new)")
		var ous multi
		flags.Var(&ous, "ou", "viewer OU (repeatable)")
		if flags.Parse(args[1:]) != nil || *socket == "" || *regPath == "" {
			return fail(errors.New("--socket and --registration are required"))
		}
		reg, err := readRegistration(*regPath)
		if err != nil {
			return fail(err)
		}
		b := &backend{client: dial(*socket), reg: reg}
		if err := b.handshake(); err != nil {
			return fail(err)
		}
		var status int
		var raw []byte
		if args[0] == "call" {
			rest := flags.Args()
			if len(rest) != 2 {
				return fail(errors.New("call needs METHOD and PATH"))
			}
			method, path := strings.ToUpper(rest[0]), rest[1]
			var body []byte
			if *bodyFile != "" {
				if body, err = os.ReadFile(*bodyFile); err != nil {
					return fail(err)
				}
			}
			token, err := reg.signer(b.boot).Sign(method, path, body,
				protocol.Viewer{Subject: *subject, Role: *role, OUs: ous}, time.Now())
			if err != nil {
				return fail(err)
			}
			header := http.Header{protocol.Header: {token}}
			if len(body) > 0 {
				header.Set("Content-Type", "application/json")
			}
			status, raw, err = b.do(method, path, header, body)
			if err != nil {
				return fail(err)
			}
		} else {
			rest := flags.Args()
			if len(rest) != 1 {
				return fail(errors.New("task needs one JSON payload"))
			}
			if *occurrence == "" {
				*occurrence = "dev:" + strconv.FormatInt(time.Now().UnixNano(), 36)
			}
			body, _ := json.Marshal(map[string]any{"format": taskRequestFmt, "task_id": devTask,
				"occurrence_id": *occurrence, "payload": json.RawMessage(rest[0])})
			status, raw, err = b.do(http.MethodPost, "/v1/tasks/run", http.Header{
				"Content-Type":              {"application/json"},
				"X-Portal-Service-Identity": {serviceIdentity(reg, time.Now())},
			}, body)
			if err != nil {
				return fail(err)
			}
		}
		fmt.Fprintf(stdout, "HTTP %d\n%s", status, raw)
		if len(raw) > 0 && raw[len(raw)-1] != '\n' {
			fmt.Fprintln(stdout)
		}
		return 0
	}
	return fail(fmt.Errorf("unknown command %q", args[0]))
}

// serviceIdentity fabricates the identity Portal attaches to a background task.
// Its MAC is keyed with a seed only Portal holds, so a backend cannot verify it
// and checks the fields instead; this one passes those checks and nothing else.
func serviceIdentity(r registration, now time.Time) string {
	id := r.Metadata.Identity
	raw, _ := json.Marshal(map[string]any{
		"format": serviceIdentFmt, "lease_id": devLease, "app_id": id.AppID,
		"installation_id": id.InstallationID, "controller_epoch": id.ControllerEpoch,
		"generation": id.Generation, "policy_revision": id.PolicyRevision,
		"release_sha256": id.ReleaseSHA256, "resources": []string{"tasks.schedule"},
		"issued_ms":  strconv.FormatInt(now.Add(-time.Second).UnixMilli(), 10),
		"expires_ms": strconv.FormatInt(now.Add(time.Minute).UnixMilli(), 10),
		"mac":        strings.Repeat("0", 64),
	})
	return string(raw)
}

func sha256Sum(text string) []byte {
	sum := sha256.Sum256([]byte(text))
	return sum[:]
}

func main() { os.Exit(run(os.Args[1:], os.Stdout, os.Stderr)) }
